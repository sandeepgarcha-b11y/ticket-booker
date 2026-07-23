"""Watch a Twickets event for resale availability and alert via Telegram.

Twickets exposes a lightweight JSON availability API (no browser needed):

    https://www.twickets.live/services/tours/<TOUR_ID>/availability?api_key=<KEY>
    -> {"responseData": {"low": [<blockId>...], "good": [<blockId>...]}, ...}

Each element is a listing "block" id. Empty arrays = nothing on sale. For each
NEW block we also pull its detail (section/row/price) and build a direct buy
link, so the alert is one tap from checkout.

Modes:
  MODE=test            send a Telegram "watcher is live" message
  DEBUG=1              print findings, don't notify/persist
  LOOP_DURATION=<sec>  if >0, poll every POLL_INTERVAL seconds for this long
                       (used by the 1536 watcher for near-real-time coverage)
  otherwise            single check

Env: TWICKETS_TOUR_ID, TWICKETS_API_KEY, EVENT_URL, TELEGRAM_BOT_TOKEN,
     TELEGRAM_CHAT_ID, STATE_PATH, POLL_INTERVAL, LOOP_DURATION.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

TOUR_ID = os.environ.get("TWICKETS_TOUR_ID", "1921213724417335296")
API_KEY = os.environ.get("TWICKETS_API_KEY", "83d6ec0c-54bb-4da3-b2a1-f3cb47b984f1")
EVENT_URL = os.environ.get("EVENT_URL", f"https://www.twickets.live/en/tour/1536/{TOUR_ID}")
STATE_PATH = os.environ.get("STATE_PATH", "twickets_state.json")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
LOOP_DURATION = int(os.environ.get("LOOP_DURATION", "0"))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json", "Referer": EVENT_URL}


def log(*a):
    print(*a, flush=True)


def fetch_availability():
    """Return (low_list, good_list) of block ids from the availability API."""
    url = f"https://www.twickets.live/services/tours/{TOUR_ID}/availability?api_key={API_KEY}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    rd = r.json().get("responseData") or {}
    return rd.get("low") or [], rd.get("good") or []


def key(item):
    return item if isinstance(item, str) else json.dumps(item, sort_keys=True)


def block_url(bid):
    return f"https://www.twickets.live/app/block/{bid}"


def block_detail(bid):
    """Best-effort 'Stalls row F · £275 each · x2' descriptor, or '' on any error."""
    try:
        r = requests.get(
            f"https://www.twickets.live/services/g2/inventory/listings/{bid}?api_key={API_KEY}",
            headers=HEADERS, timeout=8,
        )
        arr = r.json().get("responseData") or []
        if not arr:
            return ""
        d = arr[0]
        bits = []
        sect = d.get("section") or d.get("area")
        if sect:
            bits.append(str(sect).title())
        if d.get("row"):
            bits.append(f"row {d['row']}")
        prices = (d.get("pricing") or {}).get("prices") or []
        if prices and prices[0].get("netSellingPrice"):
            bits.append(f"£{prices[0]['netSellingPrice'] / 100:.0f} each")
        if prices:
            bits.append(f"x{len(prices)}")
        return " · ".join(bits)
    except Exception:  # noqa: BLE001
        return ""


def notify(text):
    if not (TG_TOKEN and TG_CHAT):
        log("[notify] Telegram not configured; would have sent:\n" + text)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": "true"},
        timeout=30,
    )
    if r.status_code != 200:
        log(f"[notify] telegram error {r.status_code}: {r.text[:300]}")
        return False
    log("[notify] sent")
    return True


def load_prev():
    try:
        with open(STATE_PATH) as f:
            return set(json.load(f).get("listing_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(ids):
    with open(STATE_PATH, "w") as f:
        json.dump(
            {"listing_ids": sorted(ids), "updated": datetime.now(timezone.utc).isoformat()},
            f, indent=2,
        )


def alert(new_ids, low, good):
    lines = []
    for b in sorted(new_ids):
        d = block_detail(b)
        lines.append(f"• {d}\n  {block_url(b)}" if d else f"• {block_url(b)}")
    notify(
        f"🎟️ 1536 resale on Twickets — {len(new_ids)} new listing(s)!\n"
        f"({len(good)} good + {len(low)} lower availability)\n\n"
        + "\n".join(lines[:12])
        + f"\n\nAll: {EVENT_URL}"
    )


def poll_and_alert(known):
    low, good = fetch_availability()
    current = {key(x) for x in low} | {key(x) for x in good}
    new = current - known
    log(f"twickets: low={len(low)} good={len(good)} total={len(current)} new={len(new)}")
    if new:
        alert(new, low, good)
    return current


def run_test():
    low, good = fetch_availability()
    n = len(low) + len(good)
    state = f"{n} listing(s) currently on sale" if n else "nothing on sale right now"
    notify(
        "✅ Twickets watcher is live for 1536.\n"
        f"Right now: {state}.\n\n"
        "You'll get a message with a direct buy link the moment resale tickets appear.\n"
        f"{EVENT_URL}"
    )
    log("[test] sent")
    return 0


def main():
    if os.environ.get("MODE", "").lower() == "test":
        return run_test()

    if DEBUG:
        low, good = fetch_availability()
        current = {key(x) for x in low} | {key(x) for x in good}
        log(f"twickets: low={len(low)} good={len(good)} total={len(current)}")
        log(f"low sample: {json.dumps(low[:3])}")
        log("[debug] not notifying / not persisting")
        return 0

    known = load_prev()

    if LOOP_DURATION > 0:
        deadline = time.time() + LOOP_DURATION
        log(f"loop mode: {LOOP_DURATION}s total, every {POLL_INTERVAL}s")
        while True:
            try:
                current = poll_and_alert(known)
                if current != known:
                    known = current
                    save_state(known)
            except requests.RequestException as e:
                log(f"[warn] request failed: {e!r}")
            if time.time() >= deadline:
                break
            time.sleep(POLL_INTERVAL)
        log("loop finished")
        return 0

    # single check
    current = poll_and_alert(known)
    if current != known:
        save_state(current)
        log("state changed; persisted")
    else:
        log("state unchanged; not persisting")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as e:
        log(f"[warn] request failed: {e!r}")
        sys.exit(0)
