import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config
import pc_control


def authorized(update):
    return bool(update.effective_user and update.effective_user.id == config.ALLOWED_USER_ID)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("🌡 Температуры", callback_data="temps"),
         InlineKeyboardButton("🌐 Сеть", callback_data="network")],
        [InlineKeyboardButton("⚙️ Процессы", callback_data="processes"),
         InlineKeyboardButton("🪟 Окна", callback_data="windows")],
        [InlineKeyboardButton("🚀 Приложения", callback_data="apps")],
        [InlineKeyboardButton("📁 Файлы", callback_data="files")],
        [InlineKeyboardButton("🔇 Звук", callback_data="mute"),
         InlineKeyboardButton("🗕 Свернуть", callback_data="minimize")],
        [InlineKeyboardButton("📸 Скриншот", callback_data="screenshot")],
        [InlineKeyboardButton("🔒 Блокировка", callback_data="lock"),
         InlineKeyboardButton("💤 Сон", callback_data="sleep")],
        [InlineKeyboardButton("🔄 Перезагрузка", callback_data="restart"),
         InlineKeyboardButton("🔴 Выключить", callback_data="shutdown")],
        [InlineKeyboardButton("❌ Отмена выключения", callback_data="cancel")],
    ])


def apps_menu():
    rows = []
    for app_id, item in config.FAVORITE_APPS.items():
        rows.append([InlineKeyboardButton("▶️ " + item["name"], callback_data="launch:" + app_id)])
    rows.append([InlineKeyboardButton("↩️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if authorized(update):
        await update.message.reply_text("🖥 <b>PC CONTROL v5</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=menu())


async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    if not authorized(update):
        return
    a = q.data

    if a == "back":
        await q.edit_message_text("🖥 <b>PC CONTROL v5</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=menu())
        return

    if a == "status":
        i = pc_control.get_system_info()
        text = (f"📊 <b>СТАТУС</b>\n\n🖥 <code>{i['hostname']}</code>\n"
                f"⚙️ CPU: <b>{i['cpu_percent']}%</b>\n"
                f"🧠 RAM: <b>{i['ram_percent']}%</b> — {i['ram_used_gb']}/{i['ram_total_gb']} GB\n"
                f"⏱ {i['uptime']}")
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=menu())
        return

    if a == "temps":
        t = pc_control.get_temperatures()
        await q.edit_message_text(
            f"🌡 <b>ТЕМПЕРАТУРЫ</b>\n\nCPU: <b>{t['cpu'] if t['cpu'] is not None else '—'}°C</b>\nGPU: <b>{t['gpu'] if t['gpu'] is not None else '—'}°C</b>",
            parse_mode="HTML", reply_markup=menu())
        return

    if a == "network":
        n = pc_control.get_network_speed()
        await q.edit_message_text(
            "🌐 <b>СЕТЬ</b>\n\nОткрой веб-панель для графика скорости в реальном времени.",
            parse_mode="HTML", reply_markup=menu())
        return

    if a == "processes":
        ps = pc_control.get_processes(10)
        text = "⚙️ <b>ТОП ПРОЦЕССОВ</b>\n\n" + "\n".join(
            f"<code>{p['pid']}</code> {p['name']} — CPU {p['cpu']}% / RAM {p['memory']}%"
            for p in ps
        )
        await q.edit_message_text(text[:4000], parse_mode="HTML", reply_markup=menu())
        return

    if a == "windows":
        ws = pc_control.get_windows()
        text = "🪟 <b>ОКНА</b>\n\n" + "\n".join(f"• {w['title'][:70]} (PID {w['pid']})" for w in ws[:15])
        await q.edit_message_text(text[:4000], parse_mode="HTML", reply_markup=menu())
        return

    if a == "apps":
        await q.edit_message_text("🚀 <b>ПРИЛОЖЕНИЯ</b>\n\nВыбери приложение:", parse_mode="HTML", reply_markup=apps_menu())
        return

    if a.startswith("launch:"):
        app_id = a.split(":", 1)[1]
        item = config.FAVORITE_APPS.get(app_id)
        if item:
            try:
                pc_control.launch_app(item["command"])
                await q.edit_message_text(f"▶️ {item['name']} запущено.", reply_markup=menu())
            except Exception as exc:
                await q.edit_message_text(f"❌ Ошибка: {exc}", reply_markup=menu())
        return

    if a == "files":
        home = str(Path.home())
        listing = pc_control.list_dir(home)
        names = "\n".join(("📁 " if x["is_dir"] else "📄 ") + x["name"] for x in listing["items"][:20])
        await q.edit_message_text(f"📁 <b>{home}</b>\n\n{names}", parse_mode="HTML", reply_markup=menu())
        return

    if a == "mute":
        ok = pc_control.toggle_mute()
        await q.edit_message_text("🔇 Звук переключён." if ok else "❌ Не удалось изменить звук.", reply_markup=menu())
        return

    if a == "minimize":
        pc_control.minimize_all_windows()
        await q.edit_message_text("🗕 Окна свернуты.", reply_markup=menu())
        return

    if a == "screenshot":
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                path = f.name
            pc_control.screenshot(path)
            with open(path, "rb") as photo:
                await q.message.reply_photo(photo=photo, caption="📸 Скриншот ПК")
            Path(path).unlink(missing_ok=True)
        except Exception as exc:
            await q.edit_message_text(f"❌ Скриншот не удался: {exc}", reply_markup=menu())
        return

    actions = {"lock": pc_control.lock_pc, "sleep": pc_control.sleep_pc, "cancel": pc_control.cancel_shutdown}
    if a in actions:
        actions[a]()
        await q.edit_message_text("✅ Выполнено.", reply_markup=menu())
        return

    if a == "restart":
        await q.edit_message_text("🔄 Перезагрузка через 5 секунд.", reply_markup=menu())
        pc_control.restart_pc(5)
        return

    if a == "shutdown":
        await q.edit_message_text("🔴 Выключение через 5 секунд.", reply_markup=menu())
        pc_control.shutdown_pc(5)
        return


def main():
    if not config.BOT_TOKEN or not config.ALLOWED_USER_ID:
        raise SystemExit("Задай BOT_TOKEN и ALLOWED_USER_ID.")
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handler))
    print("PC Control v5 Telegram bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
