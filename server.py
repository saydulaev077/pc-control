import base64
import hmac
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import config
import pc_control


app = Flask(__name__, static_folder="web")
app.config["SECRET_KEY"] = config.SECRET_KEY
WEB_TOKEN = secrets.token_urlsafe(32)

net_prev = pc_control.get_network_speed()
net_prev_time = time.monotonic()


def agent_or_web_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        agent = request.headers.get("X-Agent-Secret", "")
        if config.PC_AGENT_SECRET and hmac.compare_digest(agent, config.PC_AGENT_SECRET):
            return fn(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], WEB_TOKEN):
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], WEB_TOKEN):
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


@app.get("/")
def index():
    return send_from_directory("web", "index.html")


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    if hmac.compare_digest(password, config.WEB_PASSWORD):
        return jsonify({"ok": True, "token": WEB_TOKEN})
    return jsonify({"ok": False, "error": "Неверный пароль"}), 401


@app.get("/api/state")
@auth_required
def state():
    global net_prev, net_prev_time
    now = time.monotonic()
    current = pc_control.get_network_speed()
    dt = max(0.1, now - net_prev_time)
    down = max(0, current["bytes_recv"] - net_prev["bytes_recv"]) * 8 / dt / 1_000_000
    up = max(0, current["bytes_sent"] - net_prev["bytes_sent"]) * 8 / dt / 1_000_000
    net_prev, net_prev_time = current, now

    return jsonify({
        "system": pc_control.get_system_info(),
        "network": {"download_mbps": round(down, 2), "upload_mbps": round(up, 2)},
        "processes": pc_control.get_processes(15),
        "windows": pc_control.get_windows(),
        "apps": [{"id": k, "name": v["name"]} for k, v in config.FAVORITE_APPS.items()],
    })


@app.post("/api/action")
@agent_or_web_auth
def action():
    data = request.get_json(silent=True) or {}
    name = data.get("action")

    actions = {
        "shutdown": lambda: pc_control.shutdown_pc(5),
        "restart": lambda: pc_control.restart_pc(5),
        "cancel": pc_control.cancel_shutdown,
        "lock": pc_control.lock_pc,
        "sleep": pc_control.sleep_pc,
        "minimize": pc_control.minimize_all_windows,
        "mute": pc_control.toggle_mute,
    }
    if name in actions:
        result = actions[name]()
        return jsonify({"ok": bool(result is not None and result is not False)})

    if name == "volume":
        return jsonify({"ok": pc_control.set_volume(data.get("value", 50))})

    if name == "kill":
        return jsonify({"ok": pc_control.kill_process(data.get("pid"))})

    if name == "window_minimize":
        return jsonify({"ok": pc_control.minimize_window(data.get("hwnd"))})

    if name == "window_restore":
        return jsonify({"ok": pc_control.restore_window(data.get("hwnd"))})

    if name == "launch":
        app_id = data.get("id")
        item = config.FAVORITE_APPS.get(app_id)
        if not item:
            return jsonify({"ok": False, "error": "Приложение не найдено"}), 404
        try:
            pc_control.launch_app(item["command"])
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": False, "error": "Неизвестное действие"}), 400


@app.get("/api/files")
@auth_required
def files():
    path = request.args.get("path") or str(Path.home())
    try:
        return jsonify(pc_control.list_dir(path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/files/mkdir")
@auth_required
def mkdir():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "path": pc_control.create_folder(data.get("path", ""), data.get("name", ""))})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/files/download")
@auth_required
def download():
    path = Path(request.args.get("path", "")).expanduser().resolve()
    if not path.is_file():
        return jsonify({"error": "Файл не найден"}), 404
    return send_file(path, as_attachment=True)


@app.get("/api/screenshot")
@auth_required
def screenshot_api():
    path = Path(os.getenv("TEMP", "/tmp")) / f"pc_control_{secrets.token_hex(6)}.png"
    pc_control.screenshot(str(path))
    return send_file(path, mimetype="image/png", as_attachment=False)


@app.get("/api/health")
@agent_or_web_auth
def health():
    return jsonify({"ok": True, "time": time.time()})


if __name__ == "__main__":
    print("=" * 55)
    print("PC CONTROL v5 ULTIMATE")
    print(f"Web: http://{config.WEB_HOST}:{config.WEB_PORT}")
    print("Пароль: значение PC_CONTROL_PASSWORD")
    print("=" * 55)
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, threaded=True)
