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

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or 0)
WEB_PASSWORD = os.getenv("WEB_PASSWORD", os.getenv("PC_CONTROL_PASSWORD", ""))
AGENT_SECRET = os.getenv("AGENT_SECRET", os.getenv("PC_AGENT_SECRET", ""))

app = Flask(__name__, static_folder="web")
WEB_TOKEN = secrets.token_urlsafe(32)
commands = deque(maxlen=100)
lock = threading.Lock()
state = {
    "pi_online": False,
    "pc_online": False,
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
        a = request.headers.get("X-Agent-Secret", "")
        if AGENT_SECRET and hmac.compare_digest(a, AGENT_SECRET):
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper

def enqueue(action):
    item = {"id": secrets.token_hex(8), "action": action, "created": time.time()}
    with lock:
        commands.append(item)
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
    if authorized(update):
        await update.message.reply_text("🖥 PC CONTROL v5\n\nУдалённое управление:", reply_markup=bot_menu())

async def bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not authorized(update):
        return
    await q.answer()
    a = q.data
    if a == "status":
        with lock:
            s = dict(state)
        age = int(time.time() - s["last_seen"]) if s["last_seen"] else 999999
        pi = "🟢 онлайн" if age < 15 else "🔴 офлайн"
        pc = "🟢 включён" if s["pc_online"] else "🔴 выключен"
        await q.edit_message_text(
            f"📊 СТАТУС\n\nRaspberry Pi: {pi}\nПК: {pc}",
            reply_markup=bot_menu())
        return
    labels = {"wake":"🟢 Команда включения отправлена.", "shutdown":"🔴 Команда выключения отправлена.",
              "restart":"🔄 Команда перезагрузки отправлена.", "sleep":"💤 Команда сна отправлена."}
    enqueue(a)
    await q.edit_message_text(labels.get(a, "✅ Команда отправлена."), reply_markup=bot_menu())

@app.get("/")
def index():
    return send_from_directory("web", "index.html")

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    if WEB_PASSWORD and hmac.compare_digest(str(data.get("password","")), WEB_PASSWORD):
        return jsonify({"ok": True, "token": WEB_TOKEN})
    return jsonify({"ok": False, "error": "Неверный пароль"}), 401

@app.get("/api/state")
@web_auth
def web_state():
    with lock:
        s = dict(state)
    s["pi_online"] = (time.time() - s["last_seen"]) < 15 if s["last_seen"] else False
    return jsonify(s)

@app.post("/api/power")
@web_auth
def web_power():
    data = request.get_json(silent=True) or {}
    action = str(data.get("action",""))
    if action not in {"wake","shutdown","restart","sleep"}:
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
    with lock:
        state["last_seen"] = time.time()
        state["pi_online"] = True
        state["pc_online"] = bool(data.get("pc_online", False))
        state["pc_last_seen"] = time.time() if state["pc_online"] else state["pc_last_seen"]
    return jsonify({"ok": True})

@app.post("/agent/result")
@agent_auth
def agent_result():
    data = request.get_json(silent=True) or {}
    with lock:
        state["last_result"] = data
    return jsonify({"ok": True})

def run_bot():
    if not BOT_TOKEN or not ALLOWED_USER_ID:
        print("Telegram bot disabled: set BOT_TOKEN and ALLOWED_USER_ID")
        return
    tg = Application.builder().token(BOT_TOKEN).build()
    tg.add_handler(CommandHandler("start", bot_start))
    tg.add_handler(CallbackQueryHandler(bot_handler))
    tg.run_polling(drop_pending_updates=True)

def run_web():
    # Flask runs in a background thread. The Telegram polling loop must
    # stay in the main interpreter thread because python-telegram-bot
    # installs signal handlers when run_polling() starts.
    port = int(os.getenv("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    # IMPORTANT: do not start Telegram polling from a worker thread.
    # Railway launches this file as the main process.
    threading.Thread(target=run_web, daemon=True).start()
    run_bot()
