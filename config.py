import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or 0)

WEB_HOST = os.getenv("PC_CONTROL_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("PC_CONTROL_PORT", "5000"))
WEB_PASSWORD = os.getenv("PC_CONTROL_PASSWORD", "change-me")
SECRET_KEY = os.getenv("PC_CONTROL_SECRET", "change-this-secret")
PC_AGENT_SECRET = os.getenv("PC_AGENT_SECRET", "")

# Безопасный список приложений. Добавляй свои exe/пути сюда.
FAVORITE_APPS = {
    "notepad": {"name": "Блокнот", "command": ["notepad.exe"]},
    "calculator": {"name": "Калькулятор", "command": ["calc.exe"]},
    "explorer": {"name": "Проводник", "command": ["explorer.exe"]},
    "browser": {"name": "Браузер", "command": ["explorer.exe", "https://www.google.com"]},
    # Пример:
    # "discord": {"name": "Discord", "command": [r"C:\Users\YOU\AppData\Local\Discord\Update.exe", "--processStart", "Discord.exe"]},
}
