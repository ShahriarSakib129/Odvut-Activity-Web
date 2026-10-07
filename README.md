# Odvut Activity Leaderboard

Public, mobile-friendly leaderboard for the Telegram INFO GROUP Activity Bot.

## Telegram profile picture
The website gets the member's **current Telegram profile picture** server-side through the Telegram Bot API and serves it through `/avatar/<telegram_user_id>`.

The browser never receives `BOT_TOKEN`.

The existing activity bot does **not** need a new database column for this feature. The website can retrieve a user's current photo directly from Telegram using the same bot token.

A short in-memory cache is used to reduce repeated Telegram API requests.

## Features
- Current month leaderboard
- Optional month selector (`YYYY-MM`)
- Eligible-only public leaderboard (minimum 5 active days)
- Same 0–100 Activity Score formula as the bot
- Search by Telegram username or Telegram ID
- Shows score, rank, active days, messages and estimated activity time
- Telegram profile photo on leaderboard and member search result
- `/health` endpoint for Render/UptimeRobot
- Supabase PostgreSQL as the only data store

## Environment variables
Set these on the **website's Render Web Service**:

- `DATABASE_URL` — same Supabase PostgreSQL connection string used by the bot
- `BOT_TOKEN` — **same Telegram bot token used by the activity bot**; server-side only
- `GROUP_ID` — the INFO GROUP numeric chat ID

### Important
`BOT_TOKEN` must be added to the **website Render service**, even if the bot already has it in a different Render service. Environment variables are service-specific.

Do not put `BOT_TOKEN` in HTML, JavaScript, GitHub, or a public `.env` file.

## Render
Build:
`pip install -r requirements.txt`

Start:
`gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app`

Health check:
`/health`

## UptimeRobot
Monitor the website's `/health` URL with an HTTP monitor. The endpoint returns HTTP 200 when the web service is running.
