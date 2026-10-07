# Odvut Activity Leaderboard

Public, mobile-friendly leaderboard for the Telegram INFO GROUP Activity Bot.

## Features
- Current month leaderboard
- Optional month selector (`YYYY-MM`)
- Eligible-only public leaderboard (minimum 5 active days)
- Same 0–100 Activity Score formula as the bot
- Search by Telegram username or Telegram ID
- Shows score, rank, active days, messages and estimated activity time
- Telegram profile photo proxy without exposing `BOT_TOKEN` to the browser
- `/health` endpoint for Render/UptimeRobot
- Supabase PostgreSQL as the only data store

## Environment variables
- `DATABASE_URL` — same Supabase PostgreSQL connection string used by the bot
- `BOT_TOKEN` — same Telegram bot token; server-side only
- `GROUP_ID` — the INFO GROUP numeric chat ID

## Render
Build: `pip install -r requirements.txt`

Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app`

Health check: `/health`

## Security
Never put `DATABASE_URL` or `BOT_TOKEN` in HTML/JavaScript or commit them to GitHub.
