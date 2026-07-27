#!/usr/bin/env bash
#
# Run the 1536 Twickets resale watcher CONTINUOUSLY on your own machine.
#
# Why: from your home internet (a residential IP) with no GitHub cron gaps, this
# polls every few SECONDS instead of ~12s+, so you hear about a drop almost the
# instant it's listed — the single biggest thing that helps you actually catch
# one. Keep this window open; it texts your Telegram exactly like the cloud one.
#
# Usage:
#   1) Install Python 3 (python.org) if you don't have it.
#   2) In a terminal, from this folder:
#        export TELEGRAM_BOT_TOKEN="<your bot token from BotFather>"
#        bash run_local.sh
#      (Your chat id is already set below. Press Ctrl-C to stop.)
#
set -euo pipefail

export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN first: export TELEGRAM_BOT_TOKEN=...}"
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-1391681044}"
export SHOW_NAME="${SHOW_NAME:-1536}"
export TWICKETS_TOUR_ID="${TWICKETS_TOUR_ID:-1921213724417335296}"
export EVENT_URL="${EVENT_URL:-https://www.twickets.live/en/tour/1536/1921213724417335296}"
export POLL_INTERVAL="${POLL_INTERVAL:-5}"       # seconds between checks
export LOOP_DURATION="${LOOP_DURATION:-604800}"  # keep running ~7 days
export STATE_PATH="${STATE_PATH:-twickets_local_state.json}"

python3 -m pip install --quiet --user "requests>=2.31" || true
echo "Watching 1536 on Twickets every ${POLL_INTERVAL}s — leave this open. Ctrl-C to stop."
exec python3 twickets.py
