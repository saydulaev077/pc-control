import os
import time
import threading
import secrets
import hmac
from collections import deque
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or 0)
except ValueError:
    ALLOWED_USER_ID = 0
WEB_PASSWORD = (os.getenv("WEB_PASSWORD", "") or os.getenv("PC_CONTROL_PASSWORD", "")).strip()
AGENT_SECRET = (os.getenv("AGENT_SECRET", "") or os.getenv("PC_AGENT_SECRET", "")).strip()

app = Flask(__name__, static_folder="web")
WEB_TOKEN = secrets.token_urlsafe(32)
commands = deque(maxlen=100)
lock = threading.Lock()
state = {
    "pc_online": False,
    "agent_online": False,
    "last_seen": 0,
    "pc_last_seen": 0,
    "last_result": None,
}


def web_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        a = request.headers.get("Authorization", "")
        if a.startswith("Bearer ") and hmac.compare_digest(a[7:], WEB_TOKEN):
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


def agent_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not AGENT_SECRET:
            return jsonify({"error": "AGENT_SECRET is not configured"}), 503
        a = request.headers.get("X-Agent-Secret", "")
        if hmac.compare_digest(a, AGENT_SECRET):
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


def enqueue(action):
    item = {"id": secrets.token_hex(8), "action": action, "created": time.time()}
    with lock:
        commands.append(item)
    print(f"[COMMAND] {action} -> {item['id']}")
    return item


def authorized(update):
    return bool(update.effective_user and update.effective_user.id == ALLOWED_USER_ID)


def bot_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включить ПК", callback_data="wake"),
         InlineKeyboardButton("🔴 Выключить ПК", callback_data="shutdown")],
        [InlineKeyboardButton("🔄 Перезагрузить", callback_data="restart"),
         InlineKeyboardButton("💤 Сон", callback_data="sleep")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
    ])


async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update) or not update.message:
        return
    await update.message.reply_text(
        "🖥 PC CONTROL v5\n\nУправление Windows через Railway:",
        reply_markup=bot_menu(),
    )


async def bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    if not authorized(update):
        await q.answer("⛔ Нет доступа", show_alert=True)
        return
    await q.answer()
    action = q.data

    if action == "status":
        with lock:
            s = dict(state)
        now = time.time()
        agent = "🟢 онлайн" if s["last_seen"] and now - s["last_seen"] < 20 else "🔴 офлайн"
        pc = "🟢 включён" if s["pc_online"] else "🔴 выключен"
        await q.edit_message_text(
            f"📊 СТАТУС\n\nWindows-агент: {agent}\nПК: {pc}",
            reply_markup=bot_menu(),
        )
        return

    if action == "wake":
        await q.edit_message_text(
            "⚠️ ПК полностью выключен.\n\n"
            "Без Raspberry Pi/роутера/другого постоянно работающего устройства включить его из Railway невозможно.\n\n"
            "Остальные команды работают, пока Windows-агент запущен.",
            reply_markup=bot_menu(),
        )
        return

    if action not in {"shutdown", "restart", "sleep"}:
        return

    item = enqueue(action)
    labels = {
        "shutdown": "🔴 Команда выключения отправлена.",
        "restart": "🔄 Команда перезагрузки отправлена.",
        "sleep": "💤 Команда сна отправлена.",
    }
    await q.edit_message_text(
        f"{labels[action]}\nID: `{item['id']}",
        parse_mode="Markdown",
        reply_markup=bot_menu(),
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    if not WEB_PASSWORD:
        return jsonify({"ok": False, "error": "WEB_PASSWORD не настроен"}), 503
    if hmac.compare_digest(password, WEB_PASSWORD):
        return jsonify({"ok": True, "token": WEB_TOKEN})
    return jsonify({"ok": False, "error": "Неверный пароль"}), 401


@app.get("/api/state")
@web_auth
def api_state():
    with lock:
        s = dict(state)
    s["agent_online"] = bool(s["last_seen"] and time.time() - s["last_seen"] < 20)
    return jsonify(s)


@app.post("/api/power")
@web_auth
def api_power():
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).strip()
    if action == "wake":
        return jsonify({"ok": False, "error": "Нельзя включить полностью выключенный ПК без постоянно работающего устройства в сети."}), 409
    if action not in {"shutdown", "restart", "sleep"}:
        return jsonify({"ok": False, "error": "Неизвестная команда"}), 400
    item = enqueue(action)
    return jsonify({"ok": True, "command_id": item["id"]})


@app.get("/agent/poll")
@agent_auth
def agent_poll():
    with lock:
        items = list(commands)
        commands.clear()
    return jsonify({"commands": items})


@app.post("/agent/heartbeat")
@agent_auth
def agent_heartbeat():
    data = request.get_json(silent=True) or {}
    now = time.time()
    pc_online = bool(data.get("pc_online", False))
    with lock:
        state["last_seen"] = now
        state["agent_online"] = True
        state["pc_online"] = pc_online
        if pc_online:
            state["pc_last_seen"] = now
    return jsonify({"ok": True})


@app.post("/agent/result")
@agent_auth
def agent_result():
    data = request.get_json(silent=True) or {}
    with lock:
        state["last_result"] = data
    print(f"[AGENT RESULT] {data}")
    return jsonify({"ok": True})


def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)


def run_bot():
    if not BOT_TOKEN or not ALLOWED_USER_ID:
        print("[TELEGRAM] BOT_TOKEN or ALLOWED_USER_ID is missing")
        return
    tg = Application.builder().token(BOT_TOKEN).build()
    tg.add_handler(CommandHandler("start", bot_start))
    tg.add_handler(CallbackQueryHandler(bot_handler))
    print("[TELEGRAM] Bot started successfully")
    tg.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_web, name="Flask", daemon=True).start()
    run_bot()
