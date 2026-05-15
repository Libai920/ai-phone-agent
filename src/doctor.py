import os
import subprocess
from pathlib import Path

from config import ADB_PATH, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL


def parse_adb_devices(output):
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def check_env(environ=os.environ):
    checks = []
    token = environ.get("ANTHROPIC_AUTH_TOKEN")
    checks.append({
        "name": "ANTHROPIC_AUTH_TOKEN",
        "ok": bool(token),
        "message": "set" if token else "missing",
    })

    base_url = environ.get("ANTHROPIC_BASE_URL", ANTHROPIC_BASE_URL)
    checks.append({
        "name": "ANTHROPIC_BASE_URL",
        "ok": bool(base_url),
        "message": base_url or "missing",
    })

    model = environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL)
    checks.append({
        "name": "ANTHROPIC_MODEL",
        "ok": bool(model),
        "message": model or "missing",
    })
    return checks


def _run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def check_adb(adb_path=ADB_PATH):
    path = Path(adb_path)
    if not path.exists():
        return [{"name": "ADB_PATH", "ok": False, "message": f"not found: {adb_path}"}]

    checks = [{"name": "ADB_PATH", "ok": True, "message": str(path)}]
    try:
        result = _run([str(path), "devices"])
    except Exception as e:
        checks.append({"name": "adb devices", "ok": False, "message": str(e)})
        return checks

    if result.returncode != 0:
        checks.append({"name": "adb devices", "ok": False, "message": result.stderr.strip()})
        return checks

    devices = parse_adb_devices(result.stdout)
    checks.append({
        "name": "adb devices",
        "ok": bool(devices),
        "message": ", ".join(devices) if devices else "no online devices",
    })
    return checks


def check_ui_dump(adb_path=ADB_PATH):
    try:
        result = _run([adb_path, "shell", "uiautomator", "dump", "/sdcard/doctor_ui.xml"], timeout=20)
    except Exception as e:
        return {"name": "uiautomator dump", "ok": False, "message": str(e)}
    if result.returncode != 0:
        return {"name": "uiautomator dump", "ok": False, "message": result.stderr.strip()}
    return {"name": "uiautomator dump", "ok": True, "message": "ok"}


def collect_checks():
    checks = []
    checks.extend(check_env())
    checks.extend(check_adb())
    if any(c["name"] == "adb devices" and c["ok"] for c in checks):
        checks.append(check_ui_dump())
    return checks


def main():
    checks = collect_checks()
    for check in checks:
        status = "OK" if check["ok"] else "FAIL"
        print(f"[{status}] {check['name']}: {check['message']}")
    return 0 if all(c["ok"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
