"""One-off discovery for a Twickets event page.

Learns how Twickets exposes resale listings for an event (embedded JSON, a
catalogue/listings API, or DOM), and whether the site blocks datacenter IPs.
Prints to stdout for reading from Actions logs. Investigative only.
"""

import json
import os
import re

URL = os.environ.get("EVENT_URL") or (
    "https://www.twickets.live/en/tour/1536/1921213724417335296"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
KW = ["ticket", "listing", "catalog", "availab", "inventory", "event",
      "price", "block", "seat", "quantity", "sold"]


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
    m = re.search(r'application/json[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        print(f"  embedded json script ({len(m.group(1))} chars): {m.group(1)[:400]}")


def with_browser():
    banner("2. HEADLESS CHROMIUM")
    from playwright.sync_api import sync_playwright
    seen = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(user_agent=UA, locale="en-GB")
        page = ctx.new_page()

        def on_resp(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    seen.append(resp)
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

        banner("2a. ALL JSON RESPONSES (ticket-related flagged)")
        for resp in seen:
            u = resp.url
            flag = bool(re.search(r"catalog|listing|ticket|event|availab|inventory|block", u, re.I))
            print(f"\n--- {resp.status} {'<<TICKETISH>>' if flag else ''}\n{u}")
            if flag:
                try:
                    body = resp.text()
                    print("  snippet: " + body[:1500].replace("\n", " "))
                except Exception as e:  # noqa: BLE001
                    print(f"  (read failed: {e})")

        banner("2b. RENDERED CONTENT")
        try:
            txt = page.inner_text("body")
        except Exception:
            txt = ""
        print(txt[:2500])

        banner("2c. LISTING PROBE")
        probe = page.evaluate(
            r"""() => {
              const norm = s => (s||'').replace(/\s+/g,' ').trim();
              const body = norm(document.body.innerText);
              return {
                no_tickets: /no tickets|not available|sold out|check back|be the first/i.test(body),
                price_hits: (body.match(/£\s?\d+/g)||[]).slice(0,20),
                buy_buttons: Array.from(document.querySelectorAll('button,a'))
                  .map(e=>norm(e.innerText)).filter(t=>/buy|view|ticket|notif|alert/i.test(t)).slice(0,20),
              };
            }"""
        )
        print(json.dumps(probe, indent=2)[:2500])
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
