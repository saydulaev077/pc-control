import os
import platform
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_command(command, timeout=10):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            shell=False,
        )
    except Exception as exc:
        return None


def shutdown_pc(delay=5):
    return run_command(["shutdown", "/s", "/t", str(max(0, int(delay)))])


def restart_pc(delay=5):
    return run_command(["shutdown", "/r", "/t", str(max(0, int(delay)))])


def cancel_shutdown():
    return run_command(["shutdown", "/a"])


def lock_pc():
    return run_command(["rundll32.exe", "user32.dll,LockWorkStation"])


def sleep_pc():
    return run_command([
        "powershell", "-NoProfile", "-Command",
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)"
    ])


def minimize_all_windows():
    # Win+D — показать рабочий стол.
    return run_command([
        "powershell", "-NoProfile", "-Command",
        "$ws=New-Object -ComObject WScript.Shell; $ws.SendKeys('^{ESC}')"
    ])


def toggle_mute():
    try:
        from pycaw.pycaw import AudioUtilities
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(not bool(volume.GetMute()), None)
        return True
    except Exception:
        # Fallback через клавишу мультимедиа.
        try:
            import ctypes
            ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
            return True
        except Exception:
            return False


def get_volume():
    try:
        from pycaw.pycaw import AudioUtilities
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        device = AudioUtilities.GetSpeakers()
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return {"volume": round(volume.GetMasterVolumeLevelScalar() * 100), "muted": bool(volume.GetMute())}
    except Exception:
        return {"volume": None, "muted": None}


def set_volume(percent):
    percent = max(0, min(100, int(percent)))
    try:
        from pycaw.pycaw import AudioUtilities
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        device = AudioUtilities.GetSpeakers()
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(percent / 100, None)
        volume.SetMute(False, None)
        return True
    except Exception:
        return False


def get_temperatures():
    result = {"cpu": None, "gpu": None}
    # GPU
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            result["gpu"] = round(gpus[0].temperature, 1)
    except Exception:
        pass
    # CPU: psutil зависит от поддержки датчиков системой.
    try:
        sensors = psutil.sensors_temperatures()
        candidates = []
        for values in sensors.values():
            for item in values:
                if item.current is not None:
                    candidates.append(float(item.current))
        if candidates:
            result["cpu"] = round(max(candidates), 1)
    except Exception:
        pass
    return result


def get_network_speed():
    # Скорость рассчитывается сервером из двух снимков счетчиков.
    counters = psutil.net_io_counters()
    return {"bytes_sent": counters.bytes_sent, "bytes_recv": counters.bytes_recv}


def get_processes(limit=20):
    rows = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
        try:
            info = p.info
            rows.append({
                "pid": info["pid"],
                "name": info.get("name") or "Unknown",
                "cpu": round(info.get("cpu_percent") or 0, 1),
                "memory": round(info.get("memory_percent") or 0, 1),
                "user": info.get("username") or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda x: x["cpu"], reverse=True)
    return rows[:limit]


def kill_process(pid):
    try:
        p = psutil.Process(int(pid))
        p.terminate()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


def get_windows():
    if platform.system() != "Windows":
        return []
    try:
        import win32gui
        import win32process
        result = []
        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).strip():
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                result.append({"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "pid": pid})
            return True
        win32gui.EnumWindows(callback, None)
        return result
    except Exception:
        return []


def minimize_window(hwnd):
    try:
        import win32gui
        win32gui.ShowWindow(int(hwnd), 6)
        return True
    except Exception:
        return False


def restore_window(hwnd):
    try:
        import win32gui
        win32gui.ShowWindow(int(hwnd), 9)
        win32gui.SetForegroundWindow(int(hwnd))
        return True
    except Exception:
        return False


def get_system_info():
    boot = psutil.boot_time()
    uptime = max(0, int(time.time() - boot))
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    mem = psutil.virtual_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "name": part.mountpoint,
                "total_gb": round(usage.total / 1024**3, 1),
                "used_gb": round(usage.used / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
                "percent": usage.percent,
            })
        except Exception:
            pass

    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_percent": psutil.cpu_percent(interval=0.05),
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_cores": psutil.cpu_count(logical=True) or 0,
        "ram_total_gb": round(mem.total / 1024**3, 1),
        "ram_used_gb": round(mem.used / 1024**3, 1),
        "ram_free_gb": round(mem.available / 1024**3, 1),
        "ram_percent": mem.percent,
        "boot_time": datetime.fromtimestamp(boot).strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": f"{days}д {hours:02d}ч {minutes:02d}м {seconds:02d}с",
        "disks": disks,
        "temperatures": get_temperatures(),
        "battery": get_battery(),
        "volume": get_volume(),
    }


def get_battery():
    try:
        b = psutil.sensors_battery()
        if b:
            return {"percent": round(b.percent), "plugged": bool(b.power_plugged)}
    except Exception:
        pass
    return None


def screenshot(path):
    from PIL import ImageGrab
    image = ImageGrab.grab()
    image.save(path, "PNG")
    return path


def list_dir(path):
    base = Path(path).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise ValueError("Папка не найдена")
    items = []
    for item in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            st = item.stat()
            items.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": st.st_size if item.is_file() else None,
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        except OSError:
            continue
    return {"path": str(base), "parent": str(base.parent), "items": items}


def create_folder(path, name):
    base = Path(path).expanduser().resolve()
    if not name or any(x in name for x in ('\\', '/', ':', '*', '?', '"', '<', '>', '|')):
        raise ValueError("Недопустимое имя папки")
    target = base / name
    target.mkdir()
    return str(target)


def launch_app(command):
    # command приходит только из config.FAVORITE_APPS.
    subprocess.Popen(command, creationflags=CREATE_NO_WINDOW)
    return True
