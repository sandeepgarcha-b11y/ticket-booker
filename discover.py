"""One-off discovery script.

Runs on a GitHub Actions runner (which can reach atgtickets.com, unlike the
dev sandbox) to learn how the calendar page exposes ticket availability:

  1. Tries a plain HTTP GET (cheap path) and reports whether the HTML already
     contains availability data (e.g. an embedded __NEXT_DATA__ / JSON blob).
  2. Loads the page in headless Chromium, records every XHR/fetch the page
     makes, and prints the ones that look like availability/performance APIs
     together with a snippet of their JSON response. That reveals the real
     endpoint we can poll directly.
  3. Dumps the rendered text + counts of bookable-looking elements.

Everything is printed to stdout so it can be read back from the Actions logs.
Nothing here notifies anyone; it is purely investigative.
"""

import json
import os
import re
import sys

URL = os.environ.get(
    "SHOW_URL",
    "https://www.atgtickets.com/shows/1536/ambassadors-theatre/calendar/2026-06-30",
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

KEYWORDS = [
    "availab", "performance", "session", "soldout", "sold out", "sold-out",
    "minprice", "min_price", "book now", "buy ticket", "no tickets",
    "instock", "in stock", "calendar",
]


def banner(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def plain_http():
    banner("1. PLAIN HTTP GET")
    try:
        import requests
    except ImportError:
        print("requests not installed")
        return
    try:
        r = requests.get(URL, headers=BROWSER_HEADERS, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"request failed: {e!r}")
        return
    html = r.text
    print(f"status={r.status_code} final_url={r.url}")
    print(f"content_type={r.headers.get('content-type')} length={len(html)}")
    low = html.lower()
    for kw in KEYWORDS:
        c = low.count(kw)
        if c:
            print(f"  keyword {kw!r}: {c} hits")

    # Embedded JSON blobs commonly used by React/Next sites.
    for pat, label in [
        (r"__NEXT_DATA__\s*=\s*({.*?})\s*</script>", "__NEXT_DATA__"),
        (r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', "__NEXT_DATA__ (json script)"),
        (r"window\.__PRELOADED_STATE__\s*=\s*({.*?});", "__PRELOADED_STATE__"),
        (r"window\.__INITIAL_STATE__\s*=\s*({.*?});", "__INITIAL_STATE__"),
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            blob = m.group(1)
            print(f"  FOUND embedded blob: {label} ({len(blob)} chars)")
            try:
                data = json.loads(blob)
                print("  top-level keys:", list(data)[:40])
            except Exception as e:  # noqa: BLE001
                print(f"  (could not json-parse: {e})")
    # Any API-ish URLs referenced in the HTML.
    urls = set(re.findall(r'https?://[^\s"\'<>]{0,200}', html))
    apiish = sorted(u for u in urls if re.search(r"api|graphql|availab|performance", u, re.I))
    print("  API-ish URLs in HTML:")
    for u in apiish[:40]:
        print("   ", u)


def with_browser():
    banner("2. HEADLESS CHROMIUM + NETWORK CAPTURE")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed")
        return

    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=BROWSER_HEADERS["User-Agent"],
            locale="en-GB",
        )
        page = ctx.new_page()

        def on_response(resp):
            try:
                url = resp.url
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype or re.search(r"api|graphql|availab|performance|calendar|session", url, re.I):
                    captured.append((resp.status, ctype, url, resp))
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
        except Exception as e:  # noqa: BLE001
            print(f"navigation note: {e}")
        page.wait_for_timeout(4000)

        print(f"final url: {page.url}")
        print(f"title: {page.title()!r}")

        banner("2a. CANDIDATE API RESPONSES")
        for status, ctype, url, resp in captured:
            print(f"\n--- {status} {ctype}\n{url}")
            if "json" in ctype:
                try:
                    body = resp.text()
                    if any(k in body.lower() for k in ("availab", "performance", "session", "soldout", "price")):
                        print("  >>> looks availability-related; snippet:")
                        print("  " + body[:1500].replace("\n", " "))
                except Exception as e:  # noqa: BLE001
                    print(f"  (could not read body: {e})")

        banner("2b. RENDERED CONTENT")
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""
        print("rendered innerText (first 3000 chars):")
        print(body_text[:3000])

        banner("2c. BOOKABLE-ELEMENT PROBE")
        probe = page.evaluate(
            """() => {
                const out = {};
                const grab = (sel) => Array.from(document.querySelectorAll(sel));
                out.anchors_booking = grab('a[href*="book" i], a[href*="checkout" i], a[href*="select" i]')
                    .slice(0,40).map(a => ({t:(a.innerText||'').trim().slice(0,40), href:a.href}));
                out.buttons = grab('button').slice(0,60).map(b => (b.innerText||'').trim()).filter(Boolean);
                out.soldout_nodes = grab('*')
                    .filter(e => /sold ?out|no availab|no tickets/i.test(e.childElementCount===0 ? (e.innerText||'') : ''))
                    .slice(0,30).map(e => (e.innerText||'').trim().slice(0,50));
                out.time_like = (document.body.innerText.match(/\\b\\d{1,2}[:.]\\d{2}\\s?(am|pm)?\\b/gi)||[]).slice(0,30);
                return out;
            }"""
        )
        print(json.dumps(probe, indent=2)[:4000])

        browser.close()


if __name__ == "__main__":
    print(f"Discovering: {URL}")
    plain_http()
    try:
        with_browser()
    except Exception as e:  # noqa: BLE001
        print(f"browser stage failed: {e!r}")
    print("\nDISCOVERY DONE")
