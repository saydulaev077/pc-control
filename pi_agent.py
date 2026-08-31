import os
import time
import socket
import struct
import requests

RAILWAY_URL = os.getenv("RAILWAY_URL", "").rstrip("/")
AGENT_SECRET = os.getenv("AGENT_SECRET", "")
PC_CONTROL_URL = os.getenv("PC_CONTROL_URL", "http://192.168.1.100:5000").rstrip("/")
PC_AGENT_SECRET = os.getenv("PC_AGENT_SECRET", AGENT_SECRET)
PC_MAC = os.getenv("PC_MAC", "").replace(":", "").replace("-", "").replace(".", "")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))

def wol(mac):
    if len(mac) != 12:
        raise ValueError("PC_MAC должен содержать 12 hex-символов")
    mac_bytes = bytes.fromhex(mac)
    packet = b"\xff" * 6 + mac_bytes * 16
    for port in (9, 7):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, ("255.255.255.255", port))
        s.close()

def pc_online():
    try:
        r = requests.get(
            PC_CONTROL_URL + "/api/health",
            headers={"X-Agent-Secret": PC_AGENT_SECRET},
            timeout=2,
        )
        return r.ok
    except requests.RequestException:
        return False

def send_pc_action(action):
    r = requests.post(
        PC_CONTROL_URL + "/api/action",
        json={"action": action},
        headers={"X-Agent-Secret": PC_AGENT_SECRET},
        timeout=8,
    )
    r.raise_for_status()
    return r.json()

def heartbeat():
    requests.post(
        RAILWAY_URL + "/agent/heartbeat",
        json={"pc_online": pc_online()},
        headers={"X-Agent-Secret": AGENT_SECRET},
        timeout=8,
    ).raise_for_status()

def report(item, ok, message=""):
    try:
        requests.post(
            RAILWAY_URL + "/agent/result",
            json={"command_id": item.get("id"), "action": item.get("action"), "ok": ok, "message": message},
            headers={"X-Agent-Secret": AGENT_SECRET},
            timeout=8,
        )
    except requests.RequestException:
        pass

def main():
    if not RAILWAY_URL or not AGENT_SECRET or not PC_MAC:
        raise SystemExit("Нужны RAILWAY_URL, AGENT_SECRET и PC_MAC")
    print("PC Control Raspberry Pi agent started")
    while True:
        try:
            heartbeat()
            r = requests.get(RAILWAY_URL + "/agent/poll",
                             headers={"X-Agent-Secret": AGENT_SECRET}, timeout=8)
            r.raise_for_status()
            for item in r.json().get("commands", []):
                action = item.get("action")
                try:
                    if action == "wake":
                        wol(PC_MAC)
                        report(item, True, "Wake-on-LAN отправлен")
                    else:
                        result = send_pc_action(action)
                        report(item, bool(result.get("ok")), "Команда передана ПК")
                except Exception as exc:
                    report(item, False, str(exc))
        except Exception as exc:
            print("Agent:", exc)
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
