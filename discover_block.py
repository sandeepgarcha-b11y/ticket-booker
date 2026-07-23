"""One-off: given a live Twickets block id, find the correct per-listing buy URL
and any per-block detail endpoint (price/date), so alerts can deep-link straight
to checkout. Uses Hamilton (which currently has listings) to probe formats.
"""
import os
import requests

TOUR = os.environ.get("TWICKETS_TOUR_ID", "1208379530461323264")  # Hamilton (has listings)
KEY = os.environ.get("TWICKETS_API_KEY", "83d6ec0c-54bb-4da3-b2a1-f3cb47b984f1")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json,text/html", "Accept-Language": "en-GB"}

av = requests.get(
    f"https://www.twickets.live/services/tours/{TOUR}/availability?api_key={KEY}",
    headers=H, timeout=30).json()
rd = av.get("responseData") or {}
ids = (rd.get("low") or []) + (rd.get("good") or [])
print("block ids:", ids[:5])
if not ids:
    print("no live listings to probe; aborting")
    raise SystemExit(0)
bid = ids[0]

print("\n=== candidate BUY-PAGE urls ===")
for u in [
    f"https://www.twickets.live/app/block/{bid}",
    f"https://www.twickets.live/en/app/block/{bid}",
    f"https://www.twickets.live/block/{bid}",
    f"https://www.twickets.live/en/block/{bid}",
    f"https://www.twickets.live/en/listing/{bid}",
]:
    try:
        r = requests.get(u, headers=H, timeout=25, allow_redirects=True)
        b = r.text.lower()
        print(f"{u}\n   -> {r.status_code} final={r.url} len={len(r.text)} "
              f"buyish={'basket' in b or 'checkout' in b or 'buy' in b} price={'£' in r.text}")
    except Exception as e:  # noqa: BLE001
        print(f"{u} ERR {e!r}")

print("\n=== candidate per-block JSON endpoints ===")
for u in [
    f"https://www.twickets.live/services/blocks/{bid}?api_key={KEY}",
    f"https://www.twickets.live/services/catalogue/{bid}?api_key={KEY}",
    f"https://www.twickets.live/services/inventory/blocks/{bid}?api_key={KEY}",
    f"https://www.twickets.live/services/g2/inventory/listings/{bid}?api_key={KEY}",
]:
    try:
        r = requests.get(u, headers=H, timeout=25)
        print(f"{u}\n   -> {r.status_code} ct={r.headers.get('content-type')} "
              f"snippet={r.text[:400].replace(chr(10),' ')}")
    except Exception as e:  # noqa: BLE001
        print(f"{u} ERR {e!r}")
print("\nDONE")
