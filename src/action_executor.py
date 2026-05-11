import base64
import subprocess
import time
from pathlib import Path

ADB = "E:/AA/platform-tools/adb.exe"


def adb(*args, timeout=15):
    cmd = [ADB, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ADB failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


# App name → package keyword aliases for common Chinese apps
# where the package name doesn't contain an obvious English keyword
_APP_ALIASES = {
    "微信": ["tencent.mm"],
    "支付宝": ["alipay", "eg.android"],
    "抖音": ["aweme", "ugc.aweme"],
    "淘宝": ["taobao"],
    "微博": ["weibo"],
    "网易云音乐": ["netease.cloudmusic"],
    "饿了么": ["me.ele"],
    "美团": ["sankuai", "meituan"],
    "滴滴": ["sdu.didi"],
    "高德地图": ["autonavi"],
    "百度地图": ["baidumaps"],
    "酷狗音乐": ["kugou"],
    "哔哩哔哩": ["tv.danmaku", "bilibili"],
    "小红书": ["xingin"],
    "拼多多": ["xunmeng", "pinduoduo"],
    "京东": ["jingdong"],
    "知乎": ["zhihu"],
    "QQ": ["tencent.mobileqq"],
    "设置": ["com.android.settings"],
}

_package_cache = None


def _load_packages():
    global _package_cache
    if _package_cache is not None:
        return _package_cache
    raw = adb("shell", "pm", "list", "packages")
    _package_cache = set()
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            _package_cache.add(line[8:])
    return _package_cache


def resolve_package(app_name):
    """Resolve an app name (Chinese or English) to a package name.

    Returns the best-matching package, or None if unresolvable.
    """
    packages = _load_packages()
    name_lower = app_name.lower().strip()

    # 1. Direct substring match (works for English names like QQ, zhihu, baidu)
    matches = [p for p in packages if name_lower in p.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return min(matches, key=lambda p: len(p))

    # 2. Try aliases for Chinese app names
    aliases = _APP_ALIASES.get(app_name, [])
    for alias in aliases:
        alias_lower = alias.lower()
        alias_matches = [p for p in packages if alias_lower in p.lower()]
        if alias_matches:
            return min(alias_matches, key=lambda p: len(p))

    return None


def _center(bounds):
    """'[x1,y1][x2,y2]' -> (cx, cy)"""
    parts = bounds.replace("[", " ").replace("]", " ").replace(",", " ").split()
    if len(parts) >= 4:
        x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def _find_node(nodes, target):
    """Match a node by text (exact), resource_id, or text (fuzzy)."""
    text = target.get("text", "")
    rid = target.get("resource_id", "")

    # 1. Exact text match
    if text:
        for n in nodes:
            if n["text"] == text:
                return n

    # 2. Resource ID match — only if the rid actually exists in the tree
    if rid:
        rid_exists = any(n["resource_id"] == rid for n in nodes)
        if rid_exists:
            for n in nodes:
                if n["resource_id"] == rid:
                    return n

    # 3. Fuzzy text match (case-insensitive substring)
    if text:
        lower = text.lower()
        for n in nodes:
            if lower in n["text"].lower() or lower in n["content_desc"].lower():
                return n

    return None


def click(nodes, target):
    """Tap the center of a matched node, or use explicit coordinates."""
    # If target provides bounds directly, tap center of those bounds
    if "bounds" in target and not target.get("text") and not target.get("resource_id"):
        c = _center(target["bounds"])
        if c:
            adb("shell", "input", "tap", str(c[0]), str(c[1]))
            time.sleep(0.5)
            return {"bounds": target["bounds"], "text": "", "content_desc": ""}

    node = _find_node(nodes, target)
    if node is None:
        raise RuntimeError(f"No node matched target: {target}")
    cx, cy = _center(node["bounds"])
    adb("shell", "input", "tap", str(cx), str(cy))
    time.sleep(0.5)
    return node


def input_text(text):
    """Type text into the currently focused input field.

    Tries direct input first (fast, works for ASCII). Falls back to
    uiautomator2 IME broadcast (handles Unicode via base64).
    """
    # Try direct input first — works for ASCII on all devices
    safe = text.replace(" ", "%s").replace("&", "\\&")
    try:
        adb("shell", "input", "text", safe)
        time.sleep(0.3)
        return
    except RuntimeError:
        pass

    # Fallback: uiautomator2 AdbKeyboard IME with base64-encoded text
    U2_IME = "com.github.uiautomator/.AdbKeyboard"
    prev_ime = adb("shell", "settings", "get", "secure", "default_input_method")
    try:
        adb("shell", "ime", "enable", U2_IME)
        adb("shell", "ime", "set", U2_IME)
        b64 = base64.b64encode(text.encode("utf-8")).decode()
        adb("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_INPUT_TEXT", "--es", "text", b64)
        time.sleep(0.2)
        adb("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_HIDE")
        time.sleep(0.1)
    finally:
        adb("shell", "ime", "set", prev_ime)
        time.sleep(0.1)


def swipe(x1, y1, x2, y2, duration=300):
    """Swipe from (x1,y1) to (x2,y2)."""
    adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))
    time.sleep(0.5)


def swipe_direction(direction):
    """Swipe up/down/left/right on center screen (fixed 1260x2800 for now)."""
    cx, cy = 630, 1400
    if direction == "up":
        swipe(cx, cy + 400, cx, cy - 400)
    elif direction == "down":
        swipe(cx, cy - 400, cx, cy + 400)
    elif direction == "left":
        swipe(cx + 400, cy, cx - 400, cy)
    elif direction == "right":
        swipe(cx - 400, cy, cx + 400, cy)
    else:
        raise ValueError(f"Unknown direction: {direction}")


def press_back():
    """Press the Android back button."""
    adb("shell", "input", "keyevent", "4")
    time.sleep(0.5)


def press_home():
    """Press the Android home button."""
    adb("shell", "input", "keyevent", "3")
    time.sleep(0.5)


def unlock():
    """Wake screen and dismiss keyguard."""
    adb("shell", "input", "keyevent", "26")  # Power
    time.sleep(0.3)
    adb("shell", "wm", "dismiss-keyguard")
    time.sleep(0.3)
    # Swipe up to unlock
    adb("shell", "input", "swipe", "630", "2300", "630", "300", "300")
    time.sleep(1.0)


def launch_app(package=None, app=None):
    """Launch an app by package name, or resolve app name to package."""
    if not package and app:
        package = resolve_package(app)
        if not package:
            raise RuntimeError(f"Cannot resolve app '{app}' to a package. Try clicking the icon instead.")
    if not package:
        raise RuntimeError("launch requires a package or app name")
    adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(1.5)


def execute(nodes, action):
    """Dispatch a single action.

    action: {
        "action": "click" | "input" | "swipe" | "back" | "launch",
        "target": {"text": "..."} | {"resource_id": "..."} | null,
        "text": "..." (for input),
        "direction": "up"|"down"|"left"|"right" (for swipe),
        "package": "..." (for launch)
    }
    Returns the matched node (for click) or None.
    """
    act = action["action"]

    if act == "click":
        return click(nodes, action.get("target", {}))
    elif act == "input":
        input_text(action.get("text", ""))
        return None
    elif act == "swipe":
        target = action.get("target")
        if target and "bounds" in target:
            # Swipe on a specific element (e.g., scroll a list)
            c = _center(target.get("bounds", ""))
            if action.get("direction") == "up":
                swipe(c[0], c[1] + 200, c[0], c[1] - 200)
        else:
            swipe_direction(action.get("direction", "up"))
        return None
    elif act == "back":
        press_back()
        return None
    elif act == "launch":
        launch_app(package=action.get("package", ""), app=action.get("app", ""))
        return None
    else:
        raise ValueError(f"Unknown action: {act}")


if __name__ == "__main__":
    from ui_reader import get_ui_state

    nodes = get_ui_state()
    print(f"Loaded {len(nodes)} nodes")

    # Demo: try clicking a common target
    target = {"text": "微信"}
    try:
        hit = execute(nodes, {"action": "click", "target": target})
        print(f"Clicked: {hit['text'] or hit['content_desc']} at {_center(hit['bounds'])}")
    except RuntimeError as e:
        print(f"Failed: {e}")
