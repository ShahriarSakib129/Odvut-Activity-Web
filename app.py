import os
import re
import hmac
import hashlib
import json
from datetime import datetime
import time
from zoneinfo import ZoneInfo
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from flask import Flask, jsonify, render_template, request, Response
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
PHOTO_CACHE_TTL = 600

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


def telegram_file_id(user_id):
    """Get the user's current Telegram profile photo file_id with short caching."""
    if not BOT_TOKEN:
        return None

    user_id = int(user_id)
    now = time.time()
    cached = PHOTO_CACHE.get(user_id)
    if cached and now - cached[0] < PHOTO_CACHE_TTL:
        return cached[1]

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos"
    try:
        resp = requests.get(
            url,
            params={"user_id": user_id, "limit": 1},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        photos = data.get("result", {}).get("photos", [])
        file_id = photos[0][-1].get("file_id") if photos else None
        PHOTO_CACHE[user_id] = (now, file_id)
        return file_id
    except Exception:
        # Cache failures briefly to avoid hammering Telegram during repeated loads.
        PHOTO_CACHE[user_id] = (now, None)
        return None


def telegram_file_bytes(file_id):
    if not BOT_TOKEN or not file_id:
        return None, None
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file_id}, timeout=8)
        r.raise_for_status()
        path = r.json().get("result", {}).get("file_path")
        if not path:
            return None, None
        image = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=10)
        image.raise_for_status()
        return image.content, image.headers.get("Content-Type", "image/jpeg")
    except Exception:
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
        return jsonify({"ok": True, "month": month, "count": len(data), "members": data})
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid month. Use YYYY-MM."}), 400
    except Exception:
        app.logger.exception("Leaderboard query failed")
        return jsonify({"ok": False, "error": "Leaderboard unavailable."}), 500


@app.get("/api/search")
def search_member():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Enter username or Telegram ID."}), 400
    try:
        month = valid_month(request.args.get("month"))
        with db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if query.isdigit():
                    cur.execute("""
                        SELECT user_id, username, first_name, message_count, active_days, activity_time_seconds
                        FROM public.activity_logs
                        WHERE chat_id=%s AND month=%s AND user_id=%s
                        LIMIT 1
                    """, (int(GROUP_ID), month, int(query)))
                else:
                    username = query.lstrip("@").lower()
                    if not USERNAME_RE.fullmatch(query):
                        return jsonify({"ok": False, "error": "Invalid username or Telegram ID."}), 400
                    cur.execute("""
                        SELECT user_id, username, first_name, message_count, active_days, activity_time_seconds
                        FROM public.activity_logs
                        WHERE chat_id=%s AND month=%s AND lower(username)=lower(%s)
                        LIMIT 1
                    """, (int(GROUP_ID), month, username))
                row = cur.fetchone()

        if not row:
            return jsonify({"ok": False, "error": "Member not found for this month."}), 404

        row["score"] = score(row)
        row["eligible"] = int(row.get("active_days") or 0) >= MIN_ACTIVE_DAYS
        eligible_rows = [r for r in fetch_rows(month) if r["eligible"]]
        rank = next((i + 1 for i, r in enumerate(eligible_rows) if int(r["user_id"]) == int(row["user_id"])), None)
        return jsonify({"ok": True, "month": month, "member": {
            "user_id": int(row["user_id"]),
            "username": row.get("username") or "",
            "first_name": row.get("first_name") or "Member",
            "score": row["score"],
            "rank": rank,
            "eligible": row["eligible"],
            "is_admin": bool(ADMIN_ID and int(ADMIN_ID) == int(row["user_id"])),
            "active_days": int(row.get("active_days") or 0),
            "message_count": int(row.get("message_count") or 0),
            "estimated_time": duration(row.get("activity_time_seconds")),
        }})
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid month. Use YYYY-MM."}), 400
    except Exception:
        app.logger.exception("Member search failed")
        return jsonify({"ok": False, "error": "Search unavailable."}), 500


@app.get("/api/me")
def my_activity():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_telegram_init_data(init_data)
    if not user:
        return jsonify({"ok": False, "error": "Open this Activity Mini App from Telegram."}), 401
    try:
        month = valid_month(request.args.get("month"))
        with db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT user_id, username, first_name, message_count, active_days, activity_time_seconds
                    FROM public.activity_logs
                    WHERE chat_id=%s AND month=%s AND user_id=%s
                    LIMIT 1
                """, (int(GROUP_ID), month, int(user["id"])))
                row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "এই মাসে আপনার কোনো activity record পাওয়া যায়নি।"}), 404
        row["score"] = score(row)
        row["eligible"] = int(row.get("active_days") or 0) >= MIN_ACTIVE_DAYS
        is_admin = bool(ADMIN_ID and int(ADMIN_ID) == int(user["id"]))
        return jsonify({"ok": True, "month": month, "member": member_payload(row, month, rank_for_user(month, user["id"]), is_admin)})
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid month. Use YYYY-MM."}), 400
    except Exception:
        app.logger.exception("Mini App activity lookup failed")
        return jsonify({"ok": False, "error": "Activity unavailable."}), 500


@app.get("/avatar/<int:user_id>")
def avatar(user_id):
    file_id = telegram_file_id(user_id)
    data, content_type = telegram_file_bytes(file_id)
    if not data:
        # Tiny transparent PNG fallback.
        import base64
        placeholder = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        return Response(placeholder, mimetype="image/png", headers={"Cache-Control": "public, max-age=300"})
    return Response(data, mimetype=content_type, headers={"Cache-Control": "public, max-age=600"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
