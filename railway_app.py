import os
import time
import threading
import secrets
import hmac
from collections import deque
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or 0)
except ValueError:
    ALLOWED_USER_ID = 0

WEB_PASSWORD = (
    os.getenv("WEB_PASSWORD", "")
    or os.getenv("PC_CONTROL_PASSWORD", "")
).strip()

AGENT_SECRET = (
    os.getenv("AGENT_SECRET", "")
    or os.getenv("PC_AGENT_SECRET", "")
).strip()


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__, static_folder="web")

# Временный токен авторизации сайта.
# При перезапуске Railway он изменится.
WEB_TOKEN = secrets.token_urlsafe(32)


# =========================================================
# STORAGE
# =========================================================

commands = deque(maxlen=100)
lock = threading.Lock()

state = {
    "pi_online": False,
    "pc_online": False,
    "last_seen": 0,
    "pc_last_seen": 0,
    "last_result": None,
}


# =========================================================
# AUTH
# =========================================================

def web_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            return jsonify({
                "error": "Unauthorized"
            }), 401

        token = authorization[7:]

        if not hmac.compare_digest(token, WEB_TOKEN):
            return jsonify({
                "error": "Unauthorized"
            }), 401

        return fn(*args, **kwargs)

    return wrapper


def agent_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not AGENT_SECRET:
            return jsonify({
                "error": "AGENT_SECRET is not configured"
            }), 503

        secret = request.headers.get("X-Agent-Secret", "")

        if not hmac.compare_digest(secret, AGENT_SECRET):
            return jsonify({
                "error": "Unauthorized"
            }), 401

        return fn(*args, **kwargs)

    return wrapper


# =========================================================
# COMMAND QUEUE
# =========================================================

def enqueue(action):
    item = {
        "id": secrets.token_hex(8),
        "action": action,
        "created": time.time(),
    }

    with lock:
        commands.append(item)

    print(f"[COMMAND] {action} -> {item['id']}")

    return item


# =========================================================
# TELEGRAM AUTH
# =========================================================

def authorized(update: Update):
    user = update.effective_user

    if not user:
        return False

    return user.id == ALLOWED_USER_ID


# =========================================================
# TELEGRAM MENU
# =========================================================

def bot_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 Включить ПК",
                callback_data="wake"
            ),
            InlineKeyboardButton(
                "🔴 Выключить ПК",
                callback_data="shutdown"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Перезагрузить",
                callback_data="restart"
            ),
            InlineKeyboardButton(
                "💤 Сон",
                callback_data="sleep"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Статус",
                callback_data="status"
            )
        ],
    ])


# =========================================================
# TELEGRAM /start
# =========================================================

async def bot_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not authorized(update):
        print(
            f"[TELEGRAM] Unauthorized user: "
            f"{update.effective_user.id if update.effective_user else 'unknown'}"
        )
        return

    if not update.message:
        return

    await update.message.reply_text(
        "🖥 PC CONTROL v5\n\n"
        "Удалённое управление компьютером:",
        reply_markup=bot_menu(),
    )


# =========================================================
# TELEGRAM CALLBACKS
# =========================================================

async def bot_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    if not authorized(update):
        await query.answer(
            "⛔ Нет доступа",
            show_alert=True
        )
        return

    await query.answer()

    action = query.data

    # -------------------------
    # STATUS
    # -------------------------

    if action == "status":
        with lock:
            current_state = dict(state)

        now = time.time()

        pi_age = (
            int(now - current_state["last_seen"])
            if current_state["last_seen"]
            else 999999
        )

        pi_online = pi_age < 15

        pc_online = current_state["pc_online"]

        pi_status = (
            "🟢 онлайн"
            if pi_online
            else "🔴 офлайн"
        )

        pc_status = (
            "🟢 включён"
            if pc_online
            else "🔴 выключен"
        )

        await query.edit_message_text(
            "📊 СТАТУС\n\n"
            f"Raspberry Pi: {pi_status}\n"
            f"ПК: {pc_status}",
            reply_markup=bot_menu(),
        )

        return

    # -------------------------
    # POWER COMMANDS
    # -------------------------

    labels = {
        "wake": "🟢 Команда включения отправлена.",
        "shutdown": "🔴 Команда выключения отправлена.",
        "restart": "🔄 Команда перезагрузки отправлена.",
        "sleep": "💤 Команда сна отправлена.",
    }

    allowed_actions = {
        "wake",
        "shutdown",
        "restart",
        "sleep",
    }

    if action not in allowed_actions:
        await query.edit_message_text(
            "❌ Неизвестная команда.",
            reply_markup=bot_menu(),
        )
        return

    item = enqueue(action)

    await query.edit_message_text(
        f"{labels[action]}\n\n"
        f"ID команды: `{item['id']}`",
        parse_mode="Markdown",
        reply_markup=bot_menu(),
    )


# =========================================================
# WEBSITE
# =========================================================

@app.get("/")
def index():
    return send_from_directory(
        app.static_folder,
        "index.html"
    )


# =========================================================
# WEBSITE LOGIN
# =========================================================

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}

    password = str(
        data.get("password", "")
    )

    if not WEB_PASSWORD:
        return jsonify({
            "ok": False,
            "error": "WEB_PASSWORD не настроен в Railway"
        }), 503

    if hmac.compare_digest(password, WEB_PASSWORD):
        return jsonify({
            "ok": True,
            "token": WEB_TOKEN,
        })

    return jsonify({
        "ok": False,
        "error": "Неверный пароль",
    }), 401


# =========================================================
# WEBSITE STATE
# =========================================================

@app.get("/api/state")
@web_auth
def web_state():
    with lock:
        current_state = dict(state)

    now = time.time()

    current_state["pi_online"] = (
        now - current_state["last_seen"] < 15
        if current_state["last_seen"]
        else False
    )

    return jsonify(current_state)


# =========================================================
# WEBSITE POWER
# =========================================================

@app.post("/api/power")
@web_auth
def web_power():
    data = request.get_json(silent=True) or {}

    action = str(
        data.get("action", "")
    ).strip()

    allowed_actions = {
        "wake",
        "shutdown",
        "restart",
        "sleep",
    }

    if action not in allowed_actions:
        return jsonify({
            "ok": False,
            "error": "Неизвестная команда",
        }), 400

    item = enqueue(action)

    return jsonify({
        "ok": True,
        "command_id": item["id"],
    })


# =========================================================
# RASPBERRY PI - POLL
# =========================================================

@app.get("/agent/poll")
@agent_auth
def agent_poll():
    with lock:
        items = list(commands)
        commands.clear()

    if items:
        print(
            f"[AGENT] Sending {len(items)} command(s) to Raspberry Pi"
        )

    return jsonify({
        "commands": items
    })


# =========================================================
# RASPBERRY PI - HEARTBEAT
# =========================================================

@app.post("/agent/heartbeat")
@agent_auth
def agent_heartbeat():
    data = request.get_json(silent=True) or {}

    pc_online = bool(
        data.get("pc_online", False)
    )

    now = time.time()

    with lock:
        state["last_seen"] = now
        state["pi_online"] = True
        state["pc_online"] = pc_online

        if pc_online:
            state["pc_last_seen"] = now

    return jsonify({
        "ok": True
    })


# =========================================================
# RASPBERRY PI - RESULT
# =========================================================

@app.post("/agent/result")
@agent_auth
def agent_result():
    data = request.get_json(silent=True) or {}

    with lock:
        state["last_result"] = data

    print(f"[AGENT RESULT] {data}")

    return jsonify({
        "ok": True
    })


# =========================================================
# TELEGRAM BOT
# =========================================================

def run_bot():
    if not BOT_TOKEN:
        print(
            "[TELEGRAM] ERROR: BOT_TOKEN is not configured"
        )
        return False

    if not ALLOWED_USER_ID:
        print(
            "[TELEGRAM] ERROR: ALLOWED_USER_ID is not configured"
        )
        return False

    print(
        "[TELEGRAM] Starting Telegram bot..."
    )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            bot_start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            bot_handler
        )
    )

    print(
        "[TELEGRAM] Bot started successfully."
    )

    # ВАЖНО:
    # run_polling() выполняется в ГЛАВНОМ ПОТОКЕ.
    application.run_polling(
        drop_pending_updates=True
    )

    return True


# =========================================================
# FLASK
# =========================================================

def run_web():
    port = int(
        os.getenv("PORT", "8080")
    )

    print(
        f"[WEB] Starting Flask on port {port}..."
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("=" * 50)
    print("PC CONTROL v5")
    print("Railway + Raspberry Pi")
    print("=" * 50)

    print(
        f"[CONFIG] BOT_TOKEN: "
        f"{'OK' if BOT_TOKEN else 'MISSING'}"
    )

    print(
        f"[CONFIG] ALLOWED_USER_ID: "
        f"{ALLOWED_USER_ID if ALLOWED_USER_ID else 'MISSING'}"
    )

    print(
        f"[CONFIG] WEB_PASSWORD: "
        f"{'OK' if WEB_PASSWORD else 'MISSING'}"
    )

    print(
        f"[CONFIG] AGENT_SECRET: "
        f"{'OK' if AGENT_SECRET else 'MISSING'}"
    )

    # Flask работает в отдельном потоке.
    # Telegram polling работает в ГЛАВНОМ потоке.
    web_thread = threading.Thread(
        target=run_web,
        name="Flask-Web",
        daemon=True,
    )

    web_thread.start()

    # Telegram запускается только в main thread.
    run_bot()
