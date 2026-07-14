"""Watch a Twickets event for resale availability and alert via Telegram.

Twickets exposes a lightweight JSON availability API (no browser or bot-evasion
needed):

    https://www.twickets.live/services/tours/<TOUR_ID>/availability?api_key=<KEY>
    -> {"responseData": {"low": [...], "good": [...]}, "responseCode": 100}

`low` and `good` are the listings currently on sale (by availability tier); both
empty means nothing is available. Each run fetches this, diffs the set of
listings against the last-seen set in twickets_state.json, and pings Telegram
when something NEW appears. State is only rewritten when the set changes.

Env vars:
  TWICKETS_TOUR_ID     tour/event id (default: the 1536 run)
  TWICKETS_API_KEY     public site api key
  EVENT_URL            link included in the alert
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  STATE_PATH           default twickets_state.json
  DEBUG                if truthy: print findings, don't notify/persist
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

TOUR_ID = os.environ.get("TWICKETS_TOUR_ID", "1921213724417335296")
API_KEY = os.environ.get("TWICKETS_API_KEY", "83d6ec0c-54bb-4da3-b2a1-f3cb47b984f1")
SHOW_NAME = os.environ.get("SHOW_NAME", "1536")
EVENT_URL = os.environ.get("EVENT_URL", f"https://www.twickets.live/en/tour/1536/{TOUR_ID}")
STATE_PATH = os.environ.get("STATE_PATH", "twickets_state.json")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def log(*a):
    print(*a, flush=True)


def fetch_availability():
    """Return (low_list, good_list) from the Twickets availability API."""
    url = f"https://www.twickets.live/services/tours/{TOUR_ID}/availability?api_key={API_KEY}"
    r = requests.get(
        url,
        headers={"User-Agent": UA, "Accept": "application/json", "Referer": EVENT_URL},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    rd = data.get("responseData") or {}
    return rd.get("low") or [], rd.get("good") or []


def key(item):
    """Stable dedupe key for a listing (handles ids or nested objects)."""
    if isinstance(item, (str, int)):
        return str(item)
    return json.dumps(item, sort_keys=True)


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
            f,
            indent=2,
        )


def main():
    low, good = fetch_availability()
    current = {key(x) for x in low} | {key(x) for x in good}
    log(f"twickets: low={len(low)} good={len(good)} total_listings={len(current)}")

    if os.environ.get("MODE", "").lower() == "test":
        n = len(current)
        state = f"{n} listing(s) currently on sale" if n else "nothing on sale right now"
        notify(
            f"✅ Twickets watcher is live for {SHOW_NAME}.\n"
            f"Right now: {state}.\n\n"
            "You'll get a message here the moment resale tickets appear.\n"
            f"{EVENT_URL}"
        )
        log("[test] sent test message; not persisting")
        return 0

    if DEBUG:
        log(f"low sample: {json.dumps(low[:3])}")
        log(f"good sample: {json.dumps(good[:3])}")
        log("[debug] not notifying / not persisting")
        return 0

    prev = load_prev()
    newly = current - prev
    if newly:
        notify(
            f"🎟️ Resale tickets on Twickets — {SHOW_NAME}\n"
            f"{len(good)} good + {len(low)} lower availability listing(s) now on sale.\n\n"
            f"{EVENT_URL}"
        )
    else:
        log("No new listings.")

    if current != prev:
        save_state(current)
        log("state changed; persisted")
    else:
        log("state unchanged; not persisting")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as e:
        # Transient network/API hiccup — log and exit 0 so we don't email a
        # spurious failure notification for a blip.
        log(f"[warn] request failed: {e!r}")
        sys.exit(0)
