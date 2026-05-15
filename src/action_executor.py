import base64
import json
import subprocess
import time
from pathlib import Path
from config import ADB_PATH

ADB = ADB_PATH


def adb(*args, timeout=15):
    cmd = [ADB, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ADB failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


# App name → package keyword aliases for common Chinese apps
# Scanned from device 10AFBC22FT008G3 on 2026-05-14
_APP_ALIASES = {
    # Communication
    "微信": ["tencent.mm"],
    "QQ": ["tencent.mobileqq"],
    "钉钉": ["alibaba.android.rimet"],
    "飞书": ["ss.android.lark"],
    "QQ邮箱": ["tencent.androidqqmail"],
    # Social / Entertainment
    "抖音": ["aweme", "ugc.aweme"],
    "快手": ["kuaishou.nebula", "smile.gifmaker"],
    "哔哩哔哩": ["tv.danmaku", "bilibili"],
    "B站": ["tv.danmaku", "bilibili"],
    "bilibili": ["tv.danmaku"],
    "微博": ["weibo"],
    "百度贴吧": ["baidu.tieba"],
    "小红书": ["xingin"],
    "知乎": ["zhihu"],
    # Shopping
    "淘宝": ["taobao"],
    "京东": ["jingdong"],
    "拼多多": ["xunmeng", "pinduoduo"],
    "闲鱼": ["taobao.idlefish"],
    "得物": ["shizhuang.duapp"],
    # Food / Services
    "美团": ["sankuai", "meituan"],
    "饿了么": ["me.ele"],
    "菜鸟": ["cainiao.wireless"],
    # Maps / Travel
    "高德地图": ["autonavi"],
    "百度地图": ["baidu.BaiduMap", "baidumap"],
    "滴滴": ["sdu.didi"],
    "交管12123": ["tmri.app"],
    # Finance
    "支付宝": ["alipay", "eg.android"],
    "工商银行": ["icbc"],
    "招商银行": ["cmb.pb"],
    "中国银行": ["chinamworld.bocmbci", "chinamworld.main"],
    "云闪付": ["unionpay"],
    "同花顺": ["hexin.plat"],
    "个人所得税": ["gov.tax.its"],
    # Productivity
    "腾讯文档": ["tencent.docs"],
    "腾讯会议": ["tencent.wemeet.app"],
    "微信读书": ["tencent.weread"],
    "有道翻译官": ["youdao.translator"],
    "夸克浏览器": ["quark.browser"],
    "Via浏览器": ["mark.via"],
    "百度网盘": ["baidu.netdisk"],
    "语雀": ["yuque.mobile"],
    "XMind": ["xmind.doughnut"],
    "CSDN": ["csdnplus"],
    # Music / Media
    "酷狗音乐": ["kugou"],
    "网易云音乐": ["netease.cloudmusic"],
    "全民K歌": ["tencent.karaoke"],
    "央视新闻": ["cntvnews"],
    # Games
    "王者荣耀": ["tencent.tmgp.sgame"],
    # AI
    "混元": ["tencent.hunyuan.app.chat"],
    "豆包": ["larus.nova"],
    "即梦": ["bytedance.dreamina"],
    "Grok": ["ai.x.grok"],
    "ChatGPT": ["openai.chatgpt"],
    "Coze": ["coze.space"],
    # Tools
    "设置": ["com.android.settings"],
    "计算器": ["desmos.calculator"],
    "中国移动": ["greenpoint.android.mc10086"],
    "中国联通": ["sinovatech.unicom.ui"],
    "学习通": ["chaoxing.mobile"],
    "天眼查": ["tianyancha.skyeye"],
    "BOSS直聘": ["hpbr.bosszhipin"],
    "58同城": ["wuba"],
    "Keep": ["gotokeep.keep"],
    "国家反诈中心": ["hicorenational.antifraud"],
    "学信网": ["chsi.chsiapp"],
    "知网": ["cnki.client"],
    "LeetCode": ["lingkou.leetcode"],
    "Steam": ["valvesoftware.android.steam.community"],
    "Discord": ["discord"],
    "GitHub": ["github.android"],
    "Epic": ["epicgames.portal"],
    "Dead Cells": ["playdigious.deadcells"],
    "Buff": ["netease.buff"],
}

_package_cache = None

_CACHE_FILE = Path(__file__).parent / "app_packages.json"


def _load_cache():
    """Load user-specific package mappings from disk."""
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


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

    # 0. Check cache first (user-specific, across sessions)
    cache = _load_cache()
    if name_lower in cache:
        pkg = cache[name_lower]
        if pkg in packages:
            return pkg

    # 1. Direct substring match (works for English names like QQ, zhihu, baidu)
    matches = [p for p in packages if name_lower in p.lower()]
    if len(matches) == 1:
        return _learn(app_name, matches[0], cache)
    if len(matches) > 1:
        return _learn(app_name, min(matches, key=lambda p: len(p)), cache)

    # 2. Try built-in aliases for Chinese app names
    aliases = _APP_ALIASES.get(app_name, [])
    for alias in aliases:
        alias_lower = alias.lower()
        alias_matches = [p for p in packages if alias_lower in p.lower()]
        if alias_matches:
            return _learn(app_name, min(alias_matches, key=lambda p: len(p)), cache)

    return None


def _learn(app_name, package, cache):
    """Save a newly resolved mapping to cache for future sessions."""
    key = app_name.lower().strip()
    if key not in cache:
        cache[key] = package
        try:
            _save_cache(cache)
        except Exception:
            pass  # cache write failure is non-fatal
    return package


def _center(bounds):
    """'[x1,y1][x2,y2]' or [x1,y1,x2,y2] -> (cx, cy)"""
    if isinstance(bounds, list):
        if len(bounds) >= 4:
            x1, y1, x2, y2 = int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3])
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None
    if isinstance(bounds, str):
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


def _result(action, hit=None, message="ok"):
    return {
        "ok": True,
        "action": action,
        "hit": hit,
        "message": message,
    }


U2_IME = "com.github.uiautomator/.AdbKeyboard"
_ime_switched = False
_prev_ime = None
_screen_width = 1260
_screen_height = 2800


def enable_u2_ime():
    """Switch to uiautomator2 IME once. Call at start of session."""
    global _ime_switched, _prev_ime
    if not _ime_switched:
        _prev_ime = adb("shell", "settings", "get", "secure", "default_input_method")
        adb("shell", "ime", "enable", U2_IME)
        adb("shell", "ime", "set", U2_IME)
        _ime_switched = True


def restore_ime():
    """Restore the original IME. Call at end of session."""
    global _ime_switched
    if _ime_switched and _prev_ime:
        adb("shell", "ime", "set", _prev_ime)
        _ime_switched = False


def input_text(text):
    """Type text into the currently focused input field.

    Tries direct input first (fast, works for ASCII). Falls back to
    uiautomator2 IME broadcast (handles Unicode via base64).
    Caller should call enable_u2_ime() once before the first input.
    """
    # Try direct input first — works for ASCII on all devices
    safe = text.replace(" ", "%s").replace("&", "\\&")
    try:
        adb("shell", "input", "text", safe)
        time.sleep(0.3)
        return
    except RuntimeError:
        pass

    # Fallback: uiautomator2 IME broadcast with base64-encoded text
    adb("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT")
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    adb("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_INPUT_TEXT", "--es", "text", b64)
    time.sleep(0.2)
    adb("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_HIDE")


def swipe(x1, y1, x2, y2, duration=300):
    """Swipe from (x1,y1) to (x2,y2)."""
    adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))
    time.sleep(0.5)


def swipe_direction(direction, times=1):
    """Swipe up/down/left/right on center screen, proportional to screen size."""
    global _screen_width, _screen_height
    cx = _screen_width // 2
    cy = _screen_height // 2
    dist = max(int(_screen_height * 0.3), 200)
    for _ in range(times):
        if direction == "up":
            swipe(cx, cy + dist, cx, cy - dist)
        elif direction == "down":
            swipe(cx, cy - dist, cx, cy + dist)
        elif direction == "left":
            swipe(cx + dist, cy, cx - dist, cy)
        elif direction == "right":
            swipe(cx - dist, cy, cx + dist, cy)
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
    # Only press power if screen is off
    if not _is_screen_on():
        adb("shell", "input", "keyevent", "26")
        time.sleep(0.5)
    adb("shell", "wm", "dismiss-keyguard")
    time.sleep(0.3)
    adb("shell", "input", "keyevent", "82")  # menu key
    time.sleep(0.2)
    # Swipe up from bottom
    adb("shell", "input", "swipe", "630", "2600", "630", "200", "500")
    time.sleep(0.5)
    # Try a second swipe for stubborn Vivo lock
    adb("shell", "input", "swipe", "630", "2700", "630", "100", "800")
    time.sleep(1.0)


def screencap():
    """Take a screenshot and return as base64-encoded PNG bytes.

    Returns (base64_string, width, height) or (None, 0, 0) on failure.
    """
    import base64 as b64
    try:
        result = subprocess.run(
            [ADB, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None, 0, 0
        png_data = result.stdout
        # Read dimensions from PNG header (IHDR chunk at bytes 16-23)
        if len(png_data) > 24 and png_data[1:4] == b"PNG":
            import struct
            global _screen_width, _screen_height
            w, h = struct.unpack(">II", png_data[16:24])
            _screen_width, _screen_height = w, h
            return b64.b64encode(png_data).decode(), w, h
        return None, 0, 0
    except Exception:
        return None, 0, 0


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


def launch_and_wait(package=None, app=None):
    """Launch an app and wait for UI to settle.

    Returns the settled UI nodes.
    """
    from ui_reader import get_ui_state

    if not package and app:
        package = resolve_package(app)
    if not package:
        raise RuntimeError("launch_and_wait requires a package or app name")

    launch_app(package=package)

    # Wait for app to settle — uiautomator fails during launch animation
    for attempt in range(8):
        time.sleep(1.0)
        try:
            nodes = get_ui_state()
        except Exception:
            continue
        if len(nodes) > 0 and not _is_lockscreen(nodes):
            return nodes

    try:
        return get_ui_state()
    except Exception:
        return []


def execute(nodes, action):
    """Dispatch a single action.

    action: {
        "action": "click" | "input" | "swipe" | "back" | "launch",
        "target": {"text": "..."} | {"resource_id": "..."} | null,
        "text": "..." (for input),
        "direction": "up"|"down"|"left"|"right" (for swipe),
        "package": "..." (for launch)
    }
    Returns {"ok": bool, "action": str, "hit": node|None, "message": str}.
    """
    act = action["action"]

    if act == "click":
        hit = click(nodes, action.get("target", {}))
        label = hit.get("text") or hit.get("content_desc") or hit.get("resource_id", "")
        return _result(act, hit=hit, message=f"clicked {label}".strip())
    elif act == "input":
        input_text(action.get("text", ""))
        return _result(act, message="input text")
    elif act == "swipe":
        target = action.get("target")
        if target and "bounds" in target:
            # Swipe on a specific element (e.g., scroll a list)
            c = _center(target.get("bounds", ""))
            if action.get("direction") == "up":
                swipe(c[0], c[1] + 200, c[0], c[1] - 200)
        else:
            swipe_direction(action.get("direction", "up"))
        return _result(act, message=f"swiped {action.get('direction', 'up')}")
    elif act == "back":
        press_back()
        return _result(act, message="pressed back")
    elif act == "launch":
        launch_app(package=action.get("package", ""), app=action.get("app", ""))
        label = action.get("package") or action.get("app") or "app"
        return _result(act, message=f"launched {label}")
    else:
        raise RuntimeError(f"Unknown action: {act}")


# ── lock detection ─────────────────────────────────────────────

def _is_lockscreen(nodes):
    """Check if we're on the lock screen by looking for keyguard indicators."""
    if len(nodes) <= 0:
        return False  # 0 nodes = dump failed, not necessarily locked
    for n in nodes:
        rid = n.get("resource_id", "").lower()
        if "systemui" in rid or "keyguard" in rid:
            return True
        desc = n.get("content_desc", "").lower()
        if "解锁" in desc or "unlock" in desc:
            return True
    return False


def ensure_unlocked():
    """Check if phone is awake and unlocked. Fix it if not.
    Returns the current UI nodes.
    """
    from ui_reader import get_ui_state

    # Wake screen if off (use dumpsys power, not node count)
    if not _is_screen_on():
        print(f"  [!] Screen off, waking...")
        unlock()

    # Get UI nodes — may need retries during animations
    for attempt in range(6):
        try:
            nodes = get_ui_state()
        except Exception:
            nodes = []
        if len(nodes) > 0:
            break
        time.sleep(1.0)

    # If we have nodes and they show lock screen, try to unlock
    if _is_lockscreen(nodes):
        print(f"  [!] Lock screen detected ({len(nodes)} nodes), unlocking...")
        unlock()
        time.sleep(1.0)
        try:
            nodes = get_ui_state()
        except Exception:
            pass

    return nodes


def _is_screen_on():
    """Check if the device screen is on (fast, no UI dump)."""
    try:
        out = adb("shell", "dumpsys", "power")
        for line in out.splitlines():
            if "mWakefulness=" in line:
                return "Awake" in line
    except Exception:
        pass
    return True  # assume on if we can't check


def check_assert(nodes_before, nodes_after, action_spec):
    """Simple assert check. Returns (ok, message)."""
    assertion = action_spec.get("assert", {})

    expected = assertion.get("text_contains", "")
    if expected:
        for n in nodes_after:
            if expected.lower() in (n["text"] + n["content_desc"]).lower():
                return True, f"Found '{expected}' on screen"

    if assertion.get("page_changed"):
        before_ids = {n.get("text") + n.get("content_desc") + n.get("resource_id") for n in nodes_before}
        after_ids = {n.get("text") + n.get("content_desc") + n.get("resource_id") for n in nodes_after}
        if before_ids != after_ids:
            return True, "Page changed"
        else:
            return False, "Page did not change"

    return True, "No assertion to check"


if __name__ == "__main__":
    from ui_reader import get_ui_state

    nodes = get_ui_state()
    print(f"Loaded {len(nodes)} nodes")

    # Demo: try clicking a common target
    target = {"text": "微信"}
    try:
        result = execute(nodes, {"action": "click", "target": target})
        hit = result["hit"]
        print(f"Clicked: {hit['text'] or hit['content_desc']} at {_center(hit['bounds'])}")
    except RuntimeError as e:
        print(f"Failed: {e}")
