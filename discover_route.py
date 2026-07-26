"""Find the REAL Twickets listing/buy URL by rendering a live event (Hamilton,
which has listings) in a headless browser: extract the actual anchor hrefs of
listing cards, and navigate to candidate block URLs to see what really renders.
"""
import os
import re
import json

TOUR = os.environ.get("TWICKETS_TOUR_ID", "1208379530461323264")  # Hamilton
KEY = "83d6ec0c-54bb-4da3-b2a1-f3cb47b984f1"
TOUR_URL = os.environ.get("EVENT_URL", f"https://www.twickets.live/en/tour/hamilton-the-musical/{TOUR}")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

import requests
av = requests.get(f"https://www.twickets.live/services/tours/{TOUR}/availability?api_key={KEY}",
                  headers={"User-Agent": UA}, timeout=30).json()
rd = av.get("responseData") or {}
ids = (rd.get("low") or []) + (rd.get("good") or [])
print("live block ids:", ids[:5])

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    page = b.new_context(user_agent=UA, locale="en-GB").new_page()
    page.goto(TOUR_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(4000)
    print("\n=== anchor hrefs on tour page (listing/event/block-ish) ===")
    hrefs = page.eval_on_selector_all(
        "a", "els => els.map(e => e.getAttribute('href')).filter(Boolean)")
    seen = set()
    for h in hrefs:
        if re.search(r"block|listing|event|checkout|buy|\d{6,}", h) and h not in seen:
            seen.add(h)
            print(" ", h)

    if ids:
        bid = ids[0]
        for path in [f"/en/event/{bid}", f"/app/block/{bid}"]:
            url = "https://www.twickets.live" + path
            print(f"\n=== navigate {url} ===")
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(3500)
                body = page.inner_text("body")
                print("final url:", page.url)
                print("title:", repr(page.title()))
                low = body.lower()
                print("shows_price:", "£" in body,
                      "| no_longer/unavailable:", bool(re.search(r"no longer|not available|unavailable|sold|expired|can'?t find|not found", low)),
                      "| buy/basket:", bool(re.search(r"add to basket|buy|checkout|proceed", low)))
                print("body snippet:", re.sub(r"\s+", " ", body)[:500])
            except Exception as e:  # noqa: BLE001
                print("nav error:", repr(e))
    b.close()
print("\nDONE")
