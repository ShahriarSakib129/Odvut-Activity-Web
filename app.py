import os
import re
import hmac
import hashlib
import json
from datetime import datetime
import time
from zoneinfo import ZoneInfo
from io import BytesIO
import base64
import secrets
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import Flask, jsonify, render_template, request, Response, url_for
from urllib.parse import parse_qsl

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
DHAKA = ZoneInfo("Asia/Dhaka")

MIN_ACTIVE_DAYS = 5
ACTIVE_DAYS_CAP = 20
ACTIVE_HOURS_CAP = 20
MESSAGE_COUNT_CAP = 500
WEIGHT_DAYS = 0.40
WEIGHT_TIME = 0.35
WEIGHT_MESSAGES = 0.25

USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{1,32}$")

# Small in-memory cache so a leaderboard does not call Telegram repeatedly.
PHOTO_CACHE = {}
PHOTO_CACHE_TTL = 21600  # 6 hours
PHOTO_FAILURE_TTL = 60   # retry temporary Telegram failures quickly
PHOTO_CACHE_LOCK = threading.Lock()
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/tmp/odvut_activity_media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_TTL = 3600
AVATAR_EXECUTOR = ThreadPoolExecutor(max_workers=8)

ADMIN_COMMENTS = [
    "👑 আপনি Admin! আপনার আবার Activity Score কীসের? আপনি তো activity-র হিসাব রাখেন! 😎",
    "😂 আপনি হিসাব রাখেন সবার, আপনার হিসাব রাখবে কে?",
    "🫡 Admin সাহেব, নিজের rank নিয়ে এত চিন্তা কেন? Group সামলান!",
    "🏆 আপনার Rank: Admin Supreme! এই leaderboard-এ সেই rank-এর জায়গা নেই।",
    "📢 আপনি Admin, আপনার activity গোপনীয়… অন্তত এই বটের কাছে! 🤫",
    "🤣 আপনি /myrank দিয়েছেন কেন? নিজের কাছে নিজের রিপোর্ট জমা দেবেন নাকি?",
    "👀 Admin হয়েও নিজের activity দেখতে চান? সন্দেহজনক ব্যাপার!",
    "☕ আগে চা খান Admin সাহেব, Activity Score দিয়ে কী করবেন?",
    "🫵 আপনি তো নিয়ম বানান! নিজের জন্য আবার নিয়মের দরকার কী?",
    "🚨 সতর্কবার্তা: Admin-এর অতিরিক্ত rank-checking শনাক্ত করা হয়েছে!",
    "🤖 আমার database-এ আপনার rank নেই, কারণ আপনাকে হিসাবের বাইরে রাখা হয়েছে!",
    "😎 আপনি leaderboard দেখেন, leaderboard আপনাকে দেখে না!",
    "📊 আপনার Activity Report: Admin হওয়াটাই আপনার সবচেয়ে বড় activity!",
    "😂 আপনি কি নিজেকেও group থেকে ban করে activity বাড়াতে চান?",
    "👑 Admin-এর rank জানতে হলে আগে Bot-এর permission নিতে হবে!",
    "🫡 আপনার কাজ member-দের active রাখা, নিজের score দেখে active হওয়া নয়!",
    "🤔 আপনি Admin, নাকি নিজের fan club-এর president?",
    "📢 এই command সাধারণ সদস্যদের জন্য। Admin-দের জন্য আছে শুধু দায়িত্ব আর দুশ্চিন্তা!",
    "💀 আবার /myrank? Admin সাহেব, আপনার কি leaderboard-এর সঙ্গে personal শত্রুতা আছে?",
    "🎖️ অভিনন্দন! আপনি আজও Admin পদে বহাল আছেন। এর চেয়ে বড় achievement আর কী!",
]


def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def current_month():
    return datetime.now(DHAKA).strftime("%Y-%m")


def valid_month(value):
    if not value:
        return current_month()
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("Invalid month")
    parsed = datetime.strptime(value, "%Y-%m")
    if parsed.strftime("%Y-%m") != value:
        raise ValueError("Invalid month")
    return value


def score(row):
    days = min(max(float(row.get("active_days") or 0), 0), ACTIVE_DAYS_CAP) / ACTIVE_DAYS_CAP * 100
    hours = (row.get("activity_time_seconds") or 0) / 3600
    time = min(max(hours, 0), ACTIVE_HOURS_CAP) / ACTIVE_HOURS_CAP * 100
    messages = min(max(float(row.get("message_count") or 0), 0), MESSAGE_COUNT_CAP) / MESSAGE_COUNT_CAP * 100
    return round(days * WEIGHT_DAYS + time * WEIGHT_TIME + messages * WEIGHT_MESSAGES, 2)


def duration(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def fetch_rows(month):
    group_id = int(GROUP_ID)
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT user_id, username, first_name, month,
                       message_count, active_days, activity_time_seconds
                FROM public.activity_logs
                WHERE chat_id = %s AND month = %s
            """, (group_id, month))
            rows = cur.fetchall()
    for r in rows:
        r["score"] = score(r)
        r["estimated_time"] = duration(r.get("activity_time_seconds"))
        r["eligible"] = int(r.get("active_days") or 0) >= MIN_ACTIVE_DAYS
    return sorted(rows, key=lambda r: (-r["score"], -int(r.get("active_days") or 0), -int(r.get("activity_time_seconds") or 0), -int(r.get("message_count") or 0), int(r["user_id"])))


def public_row(r, rank=None):
    return {
        "user_id": int(r["user_id"]),
        "username": r.get("username") or "",
        "first_name": r.get("first_name") or "Member",
        "score": r["score"],
        "rank": rank,
        "eligible": r["eligible"],
    }


def telegram_file_bytes_for_user(user_id):
    """Fetch and cache the actual Telegram profile image bytes.

    Caching the bytes (rather than only file_id) prevents every leaderboard
    image request from making two Telegram API calls. Temporary failures are
    cached only briefly so a transient timeout does not make an avatar stay
    blank for hours.
    """
    if not BOT_TOKEN:
        return None, None

    user_id = int(user_id)
    now = time.time()
    with PHOTO_CACHE_LOCK:
        cached = PHOTO_CACHE.get(user_id)
    if cached:
        age = now - cached.get("time", 0)
        ttl = PHOTO_FAILURE_TTL if cached.get("failed") else PHOTO_CACHE_TTL
        if age < ttl:
            return cached.get("data"), cached.get("content_type")

    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    try:
        resp = requests.get(
            f"{api}/getUserProfilePhotos",
            params={"user_id": user_id, "offset": 0, "limit": 1},
            timeout=6,
        )
        resp.raise_for_status()
        result = resp.json().get("result") or {}
        photos = result.get("photos") or []
        if not photos:
            with PHOTO_CACHE_LOCK:
                PHOTO_CACHE[user_id] = {"time": now, "data": None, "content_type": None, "failed": True}
            return None, None

        # Telegram normally returns several PhotoSize entries; use the
        # largest one (last entry) for the leaderboard/card.
        sizes = photos[0] or []
        file_id = (sizes[-1] or {}).get("file_id") if sizes else None
        if not file_id:
            raise RuntimeError("Telegram returned a profile photo without file_id")

        file_resp = requests.get(
            f"{api}/getFile",
            params={"file_id": file_id},
            timeout=6,
        )
        file_resp.raise_for_status()
        file_path = (file_resp.json().get("result") or {}).get("file_path")
        if not file_path:
            raise RuntimeError("Telegram returned no file_path")

        image_resp = requests.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
            timeout=8,
        )
        image_resp.raise_for_status()
        data = image_resp.content
        if not data:
            raise RuntimeError("Telegram returned an empty image")
        content_type = image_resp.headers.get("Content-Type", "image/jpeg")
        with PHOTO_CACHE_LOCK:
            PHOTO_CACHE[user_id] = {
                "time": time.time(),
                "data": data,
                "content_type": content_type,
                "failed": False,
            }
        return data, content_type
    except Exception as exc:
        app.logger.warning("Profile photo fetch failed for user %s: %s", user_id, exc)
        with PHOTO_CACHE_LOCK:
            PHOTO_CACHE[user_id] = {"time": time.time(), "data": None, "content_type": None, "failed": True}
        return None, None



def validate_telegram_init_data(init_data):
    if not BOT_TOKEN or not init_data:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        auth_date = int(data.get("auth_date", "0"))
        if not auth_date or time.time() - auth_date > 86400:
            return None
        user = json.loads(data.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception:
        return None




def authenticated_miniapp_user():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    return validate_telegram_init_data(init_data)


def cleanup_media():
    cutoff = time.time() - MEDIA_TTL
    try:
        for path in MEDIA_DIR.glob("*.png"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def save_media_bytes(data):
    cleanup_media()
    token = secrets.token_urlsafe(24)
    path = MEDIA_DIR / f"{token}.png"
    path.write_bytes(data)
    return token

def rank_for_user(month, user_id):
    eligible_rows = [r for r in fetch_rows(month) if r["eligible"]]
    return next((i + 1 for i, r in enumerate(eligible_rows) if int(r["user_id"]) == int(user_id)), None)


def member_payload(row, month, rank=None, is_admin=False):
    return {
        "user_id": int(row["user_id"]),
        "username": row.get("username") or "",
        "first_name": row.get("first_name") or "Member",
        "score": row["score"],
        "rank": rank,
        "eligible": row["eligible"],
        "is_admin": bool(is_admin),
        "active_days": int(row.get("active_days") or 0),
        "message_count": int(row.get("message_count") or 0),
        "estimated_time": duration(row.get("activity_time_seconds")),
        "month": month,
    }


@app.get("/")
def index():
    return render_template("index.html", month=current_month())


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "Odvut Activity Leaderboard"})


@app.get("/api/leaderboard")
def leaderboard():
    try:
        month = valid_month(request.args.get("month"))
        rows = fetch_rows(month)
        eligible = [r for r in rows if r["eligible"]]
        # Public leaderboard: eligible members only, matching /top rules.
        eligible = eligible[:100]
        data = [public_row(r, i + 1) for i, r in enumerate(eligible)]
        # Warm the avatar cache concurrently before returning the leaderboard.
        # With Gunicorn's single worker, doing these network calls one-by-one
        # can make only the first few browser image requests complete in time.
        futures = [AVATAR_EXECUTOR.submit(telegram_file_bytes_for_user, m["user_id"]) for m in data]
        for future in futures:
            try:
                future.result(timeout=25)
            except Exception:
                pass
        return jsonify({"ok": True, "month": month, "count": len(data), "members": data})
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid month. Use YYYY-MM."}), 400
    except Exception:
        app.logger.exception("Leaderboard query failed")
        return jsonify({"ok": False, "error": "Leaderboard unavailable."}), 500


@app.get("/api/me")
def my_activity():
    """Return only the authenticated Telegram user's activity/card data.

    Admins are intentionally not tracked by the activity bot, so an admin
    gets a synthetic admin payload instead of a misleading "no activity"
    error. No user ID from the browser is trusted.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_telegram_init_data(init_data)
    if not user:
        return jsonify({"ok": False, "error": "Open this Activity Mini App from Telegram."}), 401

    try:
        month = valid_month(request.args.get("month"))
        user_id = int(user["id"])
        is_admin = bool(ADMIN_ID and user_id == int(ADMIN_ID))

        # Admins are excluded from activity tracking. Still allow the admin
        # to open their own card and receive the special admin message.
        if is_admin:
            return jsonify({
                "ok": True,
                "month": month,
                "member": {
                    "user_id": user_id,
                    "username": user.get("username") or "",
                    "first_name": user.get("first_name") or "Admin",
                    "photo_url": user.get("photo_url") or "",
                    "score": 0,
                    "rank": None,
                    "eligible": False,
                    "is_admin": True,
                    "active_days": 0,
                    "message_count": 0,
                    "estimated_time": "0m",
                    "month": month,
                },
            })

        with db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT user_id, username, first_name, message_count, active_days, activity_time_seconds
                    FROM public.activity_logs
                    WHERE chat_id=%s AND month=%s AND user_id=%s
                    LIMIT 1
                """, (int(GROUP_ID), month, user_id))
                row = cur.fetchone()

        if not row:
            return jsonify({"ok": False, "error": "এই মাসে আপনার কোনো activity record পাওয়া যায়নি।"}), 404

        row["score"] = score(row)
        row["eligible"] = int(row.get("active_days") or 0) >= MIN_ACTIVE_DAYS
        payload = member_payload(row, month, rank_for_user(month, user_id), False)
        # Telegram's verified Mini App identity is authoritative for the
        # display name/username when available.
        payload["first_name"] = user.get("first_name") or payload["first_name"]
        payload["username"] = user.get("username") or payload["username"]
        payload["photo_url"] = user.get("photo_url") or ""
        return jsonify({"ok": True, "month": month, "member": payload})
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid month. Use YYYY-MM."}), 400
    except Exception:
        app.logger.exception("Mini App activity lookup failed")
        return jsonify({"ok": False, "error": "Activity unavailable."}), 500




@app.post("/api/card-media")
def card_media():
    """Store a freshly rendered personal card temporarily for Telegram sharing/downloading."""
    user = authenticated_miniapp_user()
    if not user:
        return jsonify({"ok": False, "error": "Open this Activity Mini App from Telegram."}), 401
    upload = request.files.get("file")
    if not upload:
        return jsonify({"ok": False, "error": "Card image is missing."}), 400
    data = upload.read()
    if not data or len(data) > 6 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Card image is too large."}), 400
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return jsonify({"ok": False, "error": "Only PNG card images are accepted."}), 400
    token = save_media_bytes(data)
    base = os.getenv("PUBLIC_URL", "").rstrip("/") or f"https://{request.host}"
    return jsonify({
        "ok": True,
        "url": f"{base}/media/activity/{token}.png",
        "download_url": f"{base}/media/download/{token}.png",
    })


def _media_path(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return None
    path = MEDIA_DIR / f"{token}.png"
    return path if path.exists() else None


@app.get("/media/activity/<token>.png")
def card_media_file(token):
    path = _media_path(token)
    if not path:
        return jsonify({"ok": False, "error": "Media expired."}), 404
    return Response(
        path.read_bytes(),
        mimetype="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline; filename=\"odvut-info-activity-card.png\"",
        },
    )


@app.get("/media/download/<token>.png")
def card_media_download(token):
    path = _media_path(token)
    if not path:
        return jsonify({"ok": False, "error": "Media expired."}), 404
    return Response(
        path.read_bytes(),
        mimetype="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": 'attachment; filename="odvut-info-activity-card.png"',
            "Access-Control-Allow-Origin": "https://web.telegram.org",
        },
    )


@app.post("/api/prepare-share")
def prepare_share():
    """Prepare the user's card as a Telegram media message for WebApp.shareMessage."""
    user = authenticated_miniapp_user()
    if not user:
        return jsonify({"ok": False, "error": "Open this Activity Mini App from Telegram."}), 401
    payload = request.get_json(silent=True) or {}
    media_url = str(payload.get("media_url") or "")
    caption = str(payload.get("caption") or "ODVUT INFO Activity Card")[:1024]
    expected_base = os.getenv("PUBLIC_URL", "").rstrip("/") or f"https://{request.host}"
    if not media_url.startswith(expected_base + "/media/activity/"):
        return jsonify({"ok": False, "error": "Invalid card media URL."}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": False, "error": "BOT_TOKEN is not configured."}), 500

    result = {
        "type": "photo",
        "id": secrets.token_hex(8),
        "photo_url": media_url,
        "thumbnail_url": media_url,
        "caption": caption,
    }
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/savePreparedInlineMessage",
            json={
                "user_id": int(user["id"]),
                "result": json.dumps(result, ensure_ascii=False),
                "allow_group_chats": True,
            },
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            app.logger.error("savePreparedInlineMessage failed: %s", data)
            return jsonify({"ok": False, "error": "Telegram could not prepare the card for sharing."}), 502
        prepared = data.get("result") or {}
        prepared_id = prepared.get("id")
        if not prepared_id:
            return jsonify({"ok": False, "error": "Telegram returned no prepared message ID."}), 502
        return jsonify({"ok": True, "id": prepared_id})
    except Exception:
        app.logger.exception("Prepared Telegram share failed")
        return jsonify({"ok": False, "error": "Could not prepare the card for Telegram."}), 502

@app.get("/avatar/<int:user_id>")
def avatar(user_id):
    data, content_type = telegram_file_bytes_for_user(user_id)
    if not data:
        # Visible fallback instead of a transparent 1x1 image.
        placeholder = b'''<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#252b3a"/><circle cx="48" cy="38" r="17" fill="#8b93a7"/><path d="M19 80c4-17 15-26 29-26s25 9 29 26" fill="#8b93a7"/></svg>'''
        return Response(placeholder, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=60"})
    return Response(data, mimetype=content_type, headers={"Cache-Control": "public, max-age=21600"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
