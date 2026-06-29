# ticket-booker

Watches an [ATG Tickets](https://www.atgtickets.com) show calendar and sends a
**Telegram** message the moment a performance becomes bookable.

Currently watching:
[Ambassadors Theatre — show 1536, from 2026-06-30](https://www.atgtickets.com/shows/1536/ambassadors-theatre/calendar/2026-06-30)

## How it works

A GitHub Actions workflow (`.github/workflows/poll.yml`) runs every ~5 minutes
(GitHub's minimum cron granularity). Each run loads the calendar page in
headless Chromium and intercepts the JSON the page itself fetches from ATG's
`calendar-service` GraphQL endpoint. Each performance carries an
`availabilityStatus` (SOLDOUT / LOW / MEDIUM / GOOD …); anything that isn't
clearly sold-out counts as bookable. That set is compared against the last-seen
set in `state.json`, and you get a Telegram ping for anything **newly** bookable.
State is committed back so you only get alerted once per drop, not every 5 min.

Polling is one lightweight page load per run (~288/day) — polite to the site.

> Scheduled workflows only run from the **default branch**, so this must be on
> `main` to fire. Actions minutes are free on **public** repos.

## Setup (one-time)

### 1. Create a Telegram bot
1. In Telegram, message [@BotFather](https://t.me/BotFather) → `/newbot`, follow
   the prompts. Copy the **bot token** it gives you.
2. Send any message to your new bot (so it's allowed to message you).
3. Get your **chat id**: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id`.

### 2. Add the secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | the BotFather token |
| `TELEGRAM_CHAT_ID`   | your chat id |

(Optional) Override the watched show with a repository **variable** `SHOW_URL`.

### 3. Done
The workflow runs automatically. To watch a different show/date, change
`SHOW_URL` (variable) or the default in `poll.yml`.

## Testing it

Actions tab → **poll** → **Run workflow** → tick **debug**. A debug run prints
exactly what it detected (bookable performances, sold-out markers, a sample of
the page) without notifying or writing state — useful for confirming detection.

## Files

- `poll.py` — the poller (Playwright + Telegram).
- `.github/workflows/poll.yml` — the 5-minute schedule.
- `discover.py` / `.github/workflows/discover.yml` — one-off investigative tool
  that dumps the page's network calls and DOM, used to tune detection.
- `state.json` — last-seen bookable set (auto-updated by the workflow).
