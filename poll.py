"""Poll an ATG Tickets show calendar and alert (via Telegram) when tickets
become bookable.

Runs on a GitHub Actions schedule. Each run:
  1. Loads the show's calendar page in headless Chromium (the page is a JS app
     and the site 403s plain bots, so a real browser is the reliable path).
  2. Extracts the set of *bookable* performances currently shown.
  3. Compares against the previously-seen set persisted in state.json.
  4. If anything is newly bookable, sends a Telegram message.
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


def log(*a):
    print(*a, flush=True)


# --- browser-side extraction -------------------------------------------------
# Returns, from the rendered page:
#   bookable:  list of {label, href} for performances that can be booked now
#   sold_out:  list of labels explicitly marked sold out / unavailable
#   sample:    a slice of rendered text (debug aid)
# The selectors are intentionally broad: ATG marks bookable performances with a
# link into the booking/seat-selection flow, and sold-out ones with disabled
# controls or "sold out" text. We treat "has an enabled booking link" as the
# availability signal and exclude anything flagged sold out / disabled.
EXTRACT_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const isHidden = (el) => {
    const st = window.getComputedStyle(el);
    return st.display === 'none' || st.visibility === 'hidden' || el.offsetParent === null && st.position !== 'fixed';
  };
  const soldRe = /(sold\s*out|no\s+availab|no\s+tickets|unavailable|fully\s+booked)/i;

  // Candidate booking links: into the booking / seat-selection / basket flow.
  const linkSel = 'a[href*="book" i], a[href*="basket" i], a[href*="checkout" i], a[href*="select" i], a[href*="seat" i], a[href*="performance" i]';
  const bookable = [];
  const seen = new Set();
  document.querySelectorAll(linkSel).forEach((a) => {
    if (isHidden(a)) return;
    const cls = (a.className || '') + ' ' + (a.getAttribute('aria-disabled') || '');
    if (/disabled/i.test(cls)) return;
    // Build a human label from the link and its surrounding context.
    let ctx = a;
    for (let i = 0; i < 4 && ctx && ctx.parentElement; i++) ctx = ctx.parentElement;
    const ctxText = norm(ctx ? ctx.innerText : a.innerText);
    if (soldRe.test(ctxText) && !/book|buy/i.test(norm(a.innerText))) return;
    const label = norm(a.innerText) || ctxText.slice(0, 60);
    const key = a.href + '|' + label;
    if (seen.has(key)) return;
    seen.add(key);
    bookable.push({ label, href: a.href });
  });

  // Enabled "Book"/"Buy" buttons (some flows use buttons, not links).
  document.querySelectorAll('button').forEach((b) => {
    if (isHidden(b) || b.disabled) return;
    const t = norm(b.innerText);
    if (/^(book|buy|select)\b/i.test(t)) {
      let ctx = b;
      for (let i = 0; i < 4 && ctx && ctx.parentElement; i++) ctx = ctx.parentElement;
      const label = norm(ctx ? ctx.innerText : t).slice(0, 80);
      const key = 'btn|' + label;
      if (!seen.has(key)) { seen.add(key); bookable.push({ label, href: location.href }); }
    }
  });

  const sold_out = [];
  document.querySelectorAll('*').forEach((el) => {
    if (el.childElementCount === 0) {
      const t = norm(el.innerText);
      if (t && soldRe.test(t) && t.length < 80) sold_out.push(t);
    }
  });

  return {
    bookable,
    sold_out: Array.from(new Set(sold_out)).slice(0, 40),
    sample: norm(document.body.innerText).slice(0, 1500),
    title: document.title,
  };
}
"""


def fetch_state():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
        page = ctx.new_page()
        # Drop heavy resources we don't need — lighter on us and on ATG's CDN.
        page.route(
            re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|otf|mp4|css)(\?|$)", re.I),
            lambda route: route.abort(),
        )
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
        except Exception as e:  # noqa: BLE001
            log(f"[warn] navigation: {e}")
        # Give late XHR-driven availability a moment to render.
        page.wait_for_timeout(3500)
        result = page.evaluate(EXTRACT_JS)
        result["final_url"] = page.url
        browser.close()
        return result


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
            return set(json.load(f).get("bookable", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(labels):
    with open(STATE_PATH, "w") as f:
        json.dump(
            {"bookable": sorted(labels), "updated": datetime.now(timezone.utc).isoformat()},
            f,
            indent=2,
        )


def main():
    log(f"Polling {URL}")
    result = fetch_state()
    bookable = result.get("bookable", [])
    current = {b["label"] for b in bookable if b.get("label")}

    log(f"title={result.get('title')!r} final_url={result.get('final_url')}")
    log(f"bookable_count={len(bookable)} sold_out_count={len(result.get('sold_out', []))}")
    if DEBUG:
        log("--- bookable ---")
        for b in bookable[:40]:
            log(f"  {b['label']!r} -> {b['href']}")
        log("--- sold_out ---")
        for s in result.get("sold_out", [])[:40]:
            log(f"  {s!r}")
        log("--- rendered sample ---")
        log(result.get("sample", ""))
        log("\n[debug] not notifying / not persisting state")
        return 0

    prev = load_prev()
    newly = current - prev
    if newly:
        lines = "\n".join(f"• {x}" for x in sorted(newly))
        notify(
            f"🎟️ Tickets available!\n{result.get('title') or 'Show'}\n\n{lines}\n\n{URL}"
        )
    else:
        log("No newly-bookable performances.")

    save_state(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
