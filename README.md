# ticket-booker

A small scheduled watcher that keeps an eye on a booking page and sends a
**Telegram** message when availability changes.

## How it works

A GitHub Actions workflow (`.github/workflows/poll.yml`) runs on a schedule.
Each run checks the configured page, works out what's currently available,
compares it against the last-seen state, and pings you on Telegram if anything
new opens up. State is kept between runs so you're only alerted once per change,
not on every run.

> Scheduled workflows only run from the **default branch**, so this lives on
> `main`. Actions minutes are free on **public** repos.

## Setup (one-time)

### 1. Create a Telegram bot
1. In Telegram, message [@BotFather](https://t.me/BotFather) → `/newbot` and
   follow the prompts. Copy the **bot token**.
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

The target page can be set via a repository **variable** `SHOW_URL` (otherwise
the default in `poll.py` is used).

### 3. Done
The workflow runs automatically once it's on `main` and the secrets are set.

## Testing it

Actions tab → **poll** → **Run workflow** → tick **debug**. A debug run prints
what it found without notifying or writing state — handy for a quick check.

## Files

- `poll.py` — the watcher.
- `.github/workflows/poll.yml` — the schedule.
- `state.json` — last-seen state (auto-updated by the workflow).
