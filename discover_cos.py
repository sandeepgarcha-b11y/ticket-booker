"""One-off discovery for a COS product page.

Learns how the page exposes per-size stock so the stock watcher can be built
against real data. Prints everything to stdout to be read from Actions logs.
Investigative only — notifies no one.
"""

import json
import os
import re

URL = os.environ.get(
    "PRODUCT_URL",
    "https://www.cos.com/en-gb/men/menswear/trousers/relaxed-fit/wideleg/product/"
    "cropped-elasticated-relaxed-fit-wide-leg-trousers-beige-1272664004",
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
KW = ["stock", "size", "variant", "availab", "notify", "soldout", "sold out",
      "outofstock", "out of stock", "instock", "in stock", "ean", "sku"]


def banner(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def plain_http():
    banner("1. PLAIN HTTP GET")
    import requests
    try:
        r = requests.get(URL, headers={"User-Agent": UA, "Accept-Language": "en-GB"}, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"request failed: {e!r}")
        return
    html = r.text
    print(f"status={r.status_code} final={r.url} len={len(html)} ctype={r.headers.get('content-type')}")
    low = html.lower()
    for kw in KW:
        c = low.count(kw)
        if c:
            print(f"  keyword {kw!r}: {c}")
    for pat, label in [
        (r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', "__NEXT_DATA__"),
        (r'application/ld\+json[^>]*>(.*?)</script>', "ld+json"),
        (r"window\.__INITIAL_STATE__\s*=\s*({.*?});", "__INITIAL_STATE__"),
    ]:
        for m in re.finditer(pat, html, re.DOTALL):
            blob = m.group(1).strip()
            print(f"\n  FOUND {label} ({len(blob)} chars)")
            try:
                data = json.loads(blob)
                # ld+json often carries offers/availability directly.
                txt = json.dumps(data)
                snippet = ""
                m2 = re.search(r'("offers".{0,600}|"availability".{0,300})', txt)
                if m2:
                    snippet = m2.group(1)
                print("   keys:", list(data)[:30] if isinstance(data, dict) else f"(list len {len(data)})")
                if snippet:
                    print("   offers/availability snippet:", snippet[:600])
            except Exception as e:  # noqa: BLE001
                print(f"   (parse failed: {e})")


def with_browser():
    banner("2. HEADLESS CHROMIUM")
    from playwright.sync_api import sync_playwright
    captured = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(user_agent=UA, locale="en-GB")
        page = ctx.new_page()

        def on_resp(resp):
            try:
                u = resp.url
                ct = resp.headers.get("content-type", "")
                if "json" in ct and re.search(r"product|stock|variant|availab|size|cart|inventory", u, re.I):
                    captured.append(resp)
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_resp)
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
        except Exception as e:  # noqa: BLE001
            print(f"nav note: {e}")
        page.wait_for_timeout(4000)
        print(f"final url: {page.url}")
        print(f"title: {page.title()!r}")

        banner("2a. CANDIDATE JSON RESPONSES")
        for resp in captured:
            print(f"\n--- {resp.status} {resp.headers.get('content-type','')}\n{resp.url}")
            try:
                body = resp.text()
                if any(k in body.lower() for k in ("stock", "availab", "variant", "size", "ean", "sku")):
                    print("  >>> stock-related; snippet:")
                    print("  " + body[:1800].replace("\n", " "))
            except Exception as e:  # noqa: BLE001
                print(f"  (read failed: {e})")

        banner("2b. SIZE-SELECTOR PROBE")
        probe = page.evaluate(
            r"""() => {
              const norm = s => (s||'').replace(/\s+/g,' ').trim();
              const out = {};
              // Size controls are usually buttons/labels/inputs in a fieldset.
              const cands = Array.from(document.querySelectorAll(
                'button, [role=radio], label, li, a')).filter(e => {
                  const t = norm(e.innerText);
                  return /^(xxs|xs|s|m|l|xl|xxl|\d{1,2})$/i.test(t) || /size/i.test(e.className||'');
                });
              out.size_like = cands.slice(0,40).map(e => ({
                tag: e.tagName,
                text: norm(e.innerText).slice(0,20),
                disabled: e.disabled || e.getAttribute('aria-disabled') || /disabled|sold|oos|out/i.test(e.className||''),
                cls: (e.className||'').slice(0,80),
              }));
              out.notify_buttons = Array.from(document.querySelectorAll('button,a'))
                .map(e=>norm(e.innerText)).filter(t=>/notify|back in stock|out of stock|sold out/i.test(t)).slice(0,10);
              return out;
            }"""
        )
        print(json.dumps(probe, indent=2)[:4000])
        b.close()


if __name__ == "__main__":
    print(f"Discovering: {URL}")
    try:
        plain_http()
    except Exception as e:  # noqa: BLE001
        print(f"plain_http failed: {e!r}")
    try:
        with_browser()
    except Exception as e:  # noqa: BLE001
        print(f"browser failed: {e!r}")
    print("\nDISCOVERY DONE")
