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
- No public member search or personal-activity lookup
- Leaderboard shows profile name, profile photo and score only
- Telegram Mini App support with server-side `initData` verification
- `Get Your Activity Card` button in the Check Activity section
- Professional Activity Card with PNG download
- Native Telegram download, Story sharing and group-chat media sharing from the Mini App
- Admin Activity Card funny-comment mode
- `/health` endpoint for Render/UptimeRobot
- Supabase PostgreSQL as the only data store

## Environment variables
Set these on the **website's Render Web Service**:

- `DATABASE_URL` — same Supabase PostgreSQL connection string used by the bot
- `BOT_TOKEN` — **same Telegram bot token used by the activity bot**; server-side only
- `GROUP_ID` — the INFO GROUP numeric chat ID
- `ADMIN_ID` — Telegram ID of the main admin (used for admin card behavior)

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

## Telegram Mini App
The website can be opened as a Telegram Mini App. The `Get Your Activity Card` button uses Telegram `initData` and the server verifies it before returning the logged-in user's own activity.

For the activity bot, add `WEBAPP_URL` with the exact HTTPS Render URL of this website. The bot can expose the Mini App with `/leaderboard` and the Telegram chat menu button.

Do not trust a browser-supplied Telegram user ID; the website verifies `X-Telegram-Init-Data` with the bot token.

### Telegram media sharing
The Mini App temporarily uploads the rendered PNG to the website so Telegram can fetch it over HTTPS. Story sharing uses `shareToStory`; group sharing uses Telegram `shareMessage` with a prepared photo message restricted to group chats. Temporary card media expires after about one hour.


### Avatar v3 fix
The leaderboard warms Telegram profile-photo cache concurrently before returning results, preventing the first few avatar requests from monopolizing the single Gunicorn worker.
