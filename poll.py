"""Poll an ATG Tickets show calendar and alert (via Telegram) when tickets
become bookable.

How it detects availability
---------------------------
The calendar page is a JS app that fetches its data from a GraphQL endpoint
(`calendar-service.core.platform.atgtickets.com`). Rather than scrape the DOM
or reverse-engineer that query, we load the page in headless Chromium and let it
make its own (correctly-authenticated) request, then intercept the JSON
response. Each performance carries an `availabilityStatus` such as SOLDOUT,
LOW, MEDIUM or GOOD; anything that isn't a clearly non-bookable status counts as
available.

Each run:
  1. Loads the show's calendar page, captures the calendar-service JSON.
  2. Builds the set of currently-bookable performances.
  3. Diffs against the set last seen in state.json.
  4. Telegrams you about anything NEWLY bookable (so no repeat spam).
  5. Writes the new set back to state.json (the workflow commits it).

Env vars:
  SHOW_URL              calendar URL to watch
  TELEGRAM_BOT_TOKEN    bot token from @BotFather
  TELEGRAM_CHAT_ID      your chat id
  STATE_PATH            where to persist state (default: state.json)
  DEBUG                 if truthy: print diagnostics, do NOT notify or persist
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo

    LONDON = ZoneInfo("Europe/London")
except Exception:  # noqa: BLE001
    LONDON = timezone.utc

URL = os.environ.get(
    "SHOW_URL",
    "https://www.atgtickets.com/shows/1536/ambassadors-theatre/calendar/2026-06-30",
)
STATE_PATH = os.environ.get("STATE_PATH", "state.json")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# availabilityStatus values that mean "you cannot buy a ticket". Anything else
# (GOOD / MEDIUM / LOW / LIMITED / AVAILABLE / a new value we haven't seen) is
# treated as bookable — we'd rather alert on an unexpected status than miss a
# genuine drop.
NON_BOOKABLE = {
    "SOLDOUT", "SOLD", "UNAVAILABLE", "CANCELLED", "CANCELED", "OFFSALE",
    "NOTONSALE", "COMINGSOON", "PAST", "PASTPERFORMANCE", "EXPIRED",
    "NOPERFORMANCE", "NONE", "",
}


def log(*a):
    print(*a, flush=True)


def norm_status(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def perf_label(perf):
    """Human-readable label like 'Tue 30 Jun 2026 19:30 (Evening) from £160'."""
    iso = (perf.get("dates") or {}).get("performanceDate") or ""
    when = iso
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LONDON)
        when = dt.strftime("%a %d %b %Y %H:%M")
    except Exception:  # noqa: BLE001
        pass
    desc = perf.get("performanceTimeDescription") or ""
    price = (perf.get("price") or {}).get("minPrice")
    bits = [when]
    if desc:
        bits.append(f"({desc})")
    if price:
        bits.append(f"from £{price}")
    return " ".join(bits)


def fetch_performances():
    """Return ({perf_id: perf_dict}, page_title) from the calendar-service JSON."""
    from playwright.sync_api import sync_playwright

    responses = []
    title = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
        page = ctx.new_page()
        # Skip heavy assets we don't need — lighter on us and on ATG's CDN.
        page.route(
            re.compile(r"\.(png|jpe?g|gif|webp|svg|woff2?|ttf|otf|mp4|css)(\?|$)", re.I),
            lambda route: route.abort(),
        )
        page.on(
            "response",
            lambda resp: responses.append(resp) if "calendar-service" in resp.url else None,
        )
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
        except Exception as e:  # noqa: BLE001
            log(f"[warn] navigation: {e}")
        page.wait_for_timeout(3000)
        try:
            title = page.title()
        except Exception:  # noqa: BLE001
            pass

        perfs = {}
        for resp in responses:
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                continue
            show = (((payload or {}).get("data") or {}).get("getShow") or {}).get("show") or {}
            for perf in show.get("performances") or []:
                pid = perf.get("id")
                if pid:
                    perfs[pid] = perf
        browser.close()
    return perfs, title


def notify(text):
    if not (TG_TOKEN and TG_CHAT):
        log("[notify] Telegram not configured; would have sent:\n" + text)
        return False
    import requests

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
            return set(json.load(f).get("available_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(available):
    """available: dict perf_id -> label"""
    with open(STATE_PATH, "w") as f:
        json.dump(
            {
                "available_ids": sorted(available),
                "available": [available[i] for i in sorted(available)],
                "updated": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )


def main():
    log(f"Polling {URL}")
    perfs, title = fetch_performances()
    log(f"title={title!r} performances_seen={len(perfs)}")

    if not perfs:
        log("[warn] No performances captured from calendar-service. The page "
            "structure or endpoint may have changed — check a debug run.")

    available = {}   # id -> label
    counts = {}
    for pid, perf in perfs.items():
        status = norm_status(perf.get("availabilityStatus"))
        counts[status or "(empty)"] = counts.get(status or "(empty)", 0) + 1
        if status not in NON_BOOKABLE:
            available[pid] = f"{perf_label(perf)} [{perf.get('availabilityStatus')}]"

    log(f"status_breakdown={counts}")
    log(f"bookable_now={len(available)}")

    if DEBUG:
        log("--- bookable performances ---")
        for pid in sorted(available, key=lambda i: available[i]):
            log(f"  {available[pid]}")
        log("\n[debug] not notifying / not persisting state")
        return 0

    prev = load_prev()
    newly = [available[i] for i in available if i not in prev]
    if newly:
        lines = "\n".join(f"• {x}" for x in sorted(newly))
        notify(f"🎟️ Tickets available — {title or '1536'}\n\n{lines}\n\n{URL}")
    else:
        log("Nothing newly bookable.")

    save_state(available)
    return 0


if __name__ == "__main__":
    sys.exit(main())
