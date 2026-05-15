"""Fast path for simple tasks — no LLM needed."""

import re
import time
from ui_reader import get_ui_state
from action_executor import execute, press_back, press_home, resolve_package, adb
from action_executor import launch_app, launch_and_wait, enable_u2_ime, restore_ime
from action_executor import ensure_unlocked, check_assert

SLEEP = 0.4  # fast path uses shorter waits than slow path


# ── intent parsing ────────────────────────────────────────────

# Pattern: "在[App]里给[target]发[text]" / "在[target]里发[text]" / "给[target]发[text]"
_SEND_RE = re.compile(
    r"(?:在|给|往)(?P<target>.+?)(?:群|里|聊天|会话)?(?:中|里)?(?:发|发送|输入|写)(?P<text>.+)"
)
_SEND_RE2 = re.compile(
    r"(?:发|发送|输入|写)(?P<text>.+?)(?:给|到|在)(?P<target>.+)"
)
# Pattern: "在QQ里发你好" → app, text (no target)
_SEND_IN_APP_RE = re.compile(
    r"在(?P<app>.+?)(?:里|中|上)(?:发|发送|输入|写)(?P<text>.+)"
)
# Pattern: "在QQ里给牛鸡村群发牛鸡" → app, target, text
_SEND_IN_APP_WITH_TARGET_RE = re.compile(
    r"在(?P<app>.+?)里(?:给|往|向)(?P<target>.+?)(?:群|聊天|会话)?(?:里|中)?(?:发|发送|输入|写)(?P<text>.+)"
)

# Pattern: "搜索X" / "搜X" / "在X里搜索Y"
_SEARCH_RE = re.compile(
    r"(?:搜索|搜|查找|找)(?P<query>.+)"
)
_SEARCH_IN_APP_RE = re.compile(
    r"在(?P<app>.+?)(?:里|中)?(?:搜索|搜|查找|找)(?P<query>.+)"
)

# Pattern: "打开QQ在牛鸡群里发牛鸡" — compound open + send (must be before _OPEN_RE)
_OPEN_AND_SEND_RE = re.compile(
    r"打开(?P<app>.+?)(?:在|给)(?P<target>.+?)(?:群|聊天|会话)?(?:里|中)?(?:发|发送|输入|写)(?P<text>.+)"
)

# Pattern: "打开X"
_OPEN_RE = re.compile(r"打开(?P<app>.+)")

# Pattern: "返回" / "退出"
_BACK_RE = re.compile(r"^(返回|退出|back)$")

# ── research intent patterns ────────────────────────────────────

# "在B站搜大模型教程" / "在美团搜猪脚饭"
_RESEARCH_IN_APP_RE = re.compile(
    r"在(?P<app>.+?)(?:里|中|上)?(?:搜索|搜|找|查找)(?P<query>.+)"
)
# "帮我在B站搜X" / "帮我在美团找X" (explicit "在" before app)
_RESEARCH_HELP_IN_APP_RE = re.compile(
    r"(?:帮我|给我|帮忙)在(?P<app>.+?)(?:里|中|上)?(?:搜索|搜|找|查找)(?P<query>.+)"
)
# "帮我找猪脚饭" / "帮我搜好吃的" / "给我推荐火锅" (no app specified)
_RESEARCH_HELP_NO_APP_RE = re.compile(
    r"(?:帮我|给我|帮忙)(?:找|搜索|搜|推荐)(?P<query>.+)"
)
# "推荐X" / "有什么好的X"
_RESEARCH_RECOMMEND_RE = re.compile(
    r"(?:推荐|有什么好的|有什么好)(?P<query>.+)"
)
# "搜一下B站大模型教程" — app between verb and query, only if app is a known name
_RESEARCH_SIMPLE_RE = re.compile(
    r"(?:搜索|搜|找)(?:一下|一搜)?(?P<rest>.+)"
)

# ── pick result intent ──────────────────────────────────────────

# "点第1个" / "打开第2个" / "第3个"
_PICK_NTH_RE = re.compile(
    r"(?:点|打开|选|点击)(?:第)?(?P<n>\d+)(?:个|号|项)"
)
# Bare "1" / "第1个"
_PICK_NTH_BARE_RE = re.compile(
    r"^第?(?P<n>\d+)(?:个|号|项)?$"
)


def _get_foreground_package():
    """Return the package name of the currently foreground app, or None."""
    try:
        out = adb("shell", "dumpsys", "activity", "activities")
        for line in out.splitlines():
            # "mResumedActivity: u0 com.tencent.mobileqq/.activity.SplashActivity"
            if "mResumedActivity:" in line:
                parts = line.strip().split()
                for p in parts:
                    if "/" in p and p.startswith("u0"):
                        continue
                    if "/" in p:
                        return p.split("/")[0]
    except Exception:
        pass
    return None


def parse_intent(task):
    """Parse a Chinese task string into structured intent.

    Returns dict with 'type' and relevant fields, or None.
    """
    task = task.strip()

    # 0. Pick from last research results
    m = _PICK_NTH_RE.search(task)
    if not m:
        m = _PICK_NTH_BARE_RE.match(task)
    if m:
        n = int(m.group("n"))
        if 1 <= n <= 10:
            return {"type": "pick_nth", "n": n}

    # 1. Specific single-action intents
    m = _BACK_RE.match(task)
    if m:
        return {"type": "back"}

    m = _OPEN_AND_SEND_RE.match(task)
    if m:
        return {"type": "send", "app": m.group("app").strip(),
                "target": m.group("target").strip(),
                "text": m.group("text").strip()}

    m = _OPEN_RE.match(task)
    if m:
        return {"type": "open", "app": m.group("app").strip()}

    # 2. Research intents — explicit app in query
    m = _RESEARCH_IN_APP_RE.match(task)
    if m:
        return {"type": "research", "app": m.group("app").strip(),
                "query": m.group("query").strip()}

    m = _RESEARCH_HELP_IN_APP_RE.match(task)
    if m:
        return {"type": "research", "app": m.group("app").strip(),
                "query": m.group("query").strip()}

    # 3. Search with app in old format — short queries stay as search, long → research
    m = _SEARCH_IN_APP_RE.match(task)
    if m:
        query = m.group("query").strip()
        app = m.group("app").strip()
        if len(query) >= 3:
            return {"type": "research", "app": app, "query": query}
        return {"type": "search", "app": app, "query": query}

    m = _RESEARCH_HELP_NO_APP_RE.match(task)
    if m:
        return {"type": "research", "query": m.group("query").strip()}

    m = _RESEARCH_RECOMMEND_RE.match(task)
    if m:
        return {"type": "research", "query": m.group("query").strip()}

    m = _RESEARCH_SIMPLE_RE.match(task)
    if m:
        rest = m.group("rest").strip()
        for name in sorted(_KNOWN_APP_NAMES, key=len, reverse=True):
            if rest.startswith(name) and len(rest) > len(name):
                return {"type": "research", "app": name,
                        "query": rest[len(name):].strip()}
        return {"type": "research", "query": rest}

    # 4. Simple search (short queries only)
    m = _SEARCH_RE.match(task)
    if m:
        query = m.group("query").strip()
        if len(query) >= 4:
            return {"type": "research", "query": query}
        return {"type": "search", "query": query}

    # 5. Send/message intents
    m = _SEND_IN_APP_WITH_TARGET_RE.match(task)
    if m:
        return {"type": "send", "app": m.group("app").strip(),
                "target": m.group("target").strip(),
                "text": m.group("text").strip()}

    m = _SEND_RE.match(task)
    if m:
        return {"type": "send", "target": m.group("target").strip(),
                "text": m.group("text").strip()}

    m = _SEND_IN_APP_RE.match(task)
    if m:
        return {"type": "send", "app": m.group("app").strip(),
                "text": m.group("text").strip()}

    m = _SEND_RE2.match(task)
    if m:
        return {"type": "send", "target": m.group("target").strip(),
                "text": m.group("text").strip()}

    return None


# ── fast executors ─────────────────────────────────────────────

def _find_and_click(nodes, text, fuzzy=True):
    """Find a node by text and click it. Returns True on success."""
    node = None
    if text:
        for n in nodes:
            if n.get("text") == text:
                node = n
                break
    if not node and text:
        lower = text.lower()
        for n in nodes:
            nt = n.get("text", "").lower()
            nd = n.get("content_desc", "").lower()
            if (nt and (lower in nt or nt in lower)) or (nd and (lower in nd or nd in lower)):
                node = n
                break
    if not node:
        return False
    execute(nodes, {"action": "click", "target": {"text": node.get("text", ""),
             "resource_id": node.get("resource_id", "")}})
    return True


def _looks_like_search_entry(node):
    rid = node.get("resource_id", "").lower()
    cls = node.get("class", "").lower()
    desc = node.get("content_desc", "").lower()
    text = node.get("text", "").lower()
    return (
        "search" in rid or
        "search" in desc or
        "搜索" in text or
        "搜索" in desc or
        "input" in rid or
        "edit" in cls
    )


def _screen_contains_text(nodes, text):
    if not text:
        return True
    lower = text.lower()
    for n in nodes:
        haystack = (n.get("text", "") + n.get("content_desc", "")).lower()
        if lower in haystack:
            return True
    return False


def fast_open(intent):
    """Open an app by name."""
    app = intent["app"]
    pkg = resolve_package(app)
    if pkg:
        launch_app(package=pkg)
        return True
    # Try resolving with common suffixes
    for suffix in ["", "android", "mobile"]:
        pkg = resolve_package(app + suffix)
        if pkg:
            launch_app(package=pkg)
            return True
    return False


_KNOWN_APP_NAMES = ["微信", "QQ", "支付宝", "抖音", "淘宝", "微博", "知乎", "小红书", "拼多多", "京东", "饿了么", "美团", "B站", "哔哩哔哩", "bilibili", "快手", "高德地图", "高德", "百度地图", "百度", "酷狗音乐", "酷狗", "网易云音乐", "钉钉", "闲鱼", "得物"]


def fast_send(intent, nodes):
    """Send a message: open app if needed → find target → click → type → send."""
    target = intent.get("target", "")
    text = intent["text"]
    current_nodes = nodes

    # Step 0: if app specified, open it first
    app = intent.get("app", "")
    # Auto-detect app from target prefix (e.g. "微信文件传输助手" → app=微信, target=文件传输助手)
    if not app and target:
        for name in _KNOWN_APP_NAMES:
            if target.startswith(name) and len(target) > len(name):
                app = name
                target = target[len(name):]
                break
    if app:
        current_nodes = launch_and_wait(app=app)

    # Step 1: find and click the target (group/contact), if specified
    if target:
        if not _find_and_click(current_nodes, target):
            found_search = False
            for n in current_nodes:
                if _looks_like_search_entry(n):
                    if n.get("clickable") or n.get("focusable"):
                        execute(current_nodes, {"action": "click", "target": {
                            "text": n.get("text", ""),
                            "resource_id": n.get("resource_id", "")}})
                        time.sleep(0.5)
                        execute(current_nodes, {"action": "input", "text": target})
                        time.sleep(0.5)
                        time.sleep(SLEEP)
                        current_nodes = get_ui_state()
                        if _find_and_click(current_nodes, target):
                            found_search = True
                            break
                if found_search:
                    break
            if not found_search:
                return False

        time.sleep(SLEEP)
        current_nodes = get_ui_state()

    # Step 2: type the message — find input field and type
    input_node = None
    for n in current_nodes:
        cls = n.get("class", "").split(".")[-1].lower()
        if "edit" in cls or "input" in n.get("resource_id", "").lower():
            input_node = n
            break
    if input_node:
        execute(current_nodes, {"action": "click", "target": {
            "text": input_node.get("text", ""),
            "resource_id": input_node.get("resource_id", "")}})
        time.sleep(0.3)

    execute(current_nodes, {"action": "input", "text": text})
    time.sleep(SLEEP)
    current_nodes = get_ui_state()

    # Step 3: click send button
    send_texts = ["发送", "send", "Send"]
    for st in send_texts:
        for n in current_nodes:
            if st in n.get("text", "") or st in n.get("content_desc", ""):
                execute(current_nodes, {"action": "click", "target": {"text": n.get("text", "")}})
                time.sleep(SLEEP)
                after_send_nodes = get_ui_state()
                if _screen_contains_text(after_send_nodes, text):
                    print(f"  Verified sent text on screen: {text}")
                else:
                    print(f"  WARNING: sent text not visible after send: {text}")
                return True

    for n in current_nodes:
        rid = n.get("resource_id", "").lower()
        if "send" in rid or "confirm" in rid:
            execute(current_nodes, {"action": "click", "target": {
                "resource_id": n.get("resource_id", "")}})
            time.sleep(SLEEP)
            after_send_nodes = get_ui_state()
            if _screen_contains_text(after_send_nodes, text):
                print(f"  Verified sent text on screen: {text}")
            else:
                print(f"  WARNING: sent text not visible after send: {text}")
            return True

    return False


def fast_search(intent, nodes):
    """Perform a search: open app if needed → find search bar → type query."""
    app = intent.get("app", "")
    query = intent["query"]
    current_nodes = nodes

    if app:
        current_nodes = launch_and_wait(app=app)

    # Find search bar
    for n in current_nodes:
        if _looks_like_search_entry(n):
            if n.get("clickable") or n.get("focusable"):
                execute(current_nodes, {"action": "click", "target": {
                    "text": n.get("text", ""),
                    "resource_id": n.get("resource_id", "")}})
                time.sleep(0.3)
                execute(current_nodes, {"action": "input", "text": query})
                time.sleep(SLEEP)
                return True

    # Fallback: try clicking any EditText
    for n in current_nodes:
        cls = n.get("class", "").split(".")[-1].lower()
        if "edit" in cls:
            execute(current_nodes, {"action": "click", "target": {
                "text": n.get("text", ""),
                "resource_id": n.get("resource_id", "")}})
            time.sleep(0.3)
            execute(current_nodes, {"action": "input", "text": query})
            time.sleep(SLEEP)
            return True

    return False


def fast_back():
    """Press back."""
    press_back()
    return True


# ── dispatcher ─────────────────────────────────────────────────

def fast_run(task):
    """Try to execute a task via fast path.

    Returns True if handled, False if needs LLM.
    """
    intent = parse_intent(task)
    if not intent:
        return False

    print(f"\n  [FAST] {intent['type']}: {task}")
    itype = intent["type"]

    # Back: no IME, no UI dump needed — just press the button
    if itype == "back":
        fast_back()
        print(f"  OK")
        return True

    # Open: no IME needed, but may need unlock
    if itype == "open":
        if "app" in intent:
            ensure_unlocked()  # only wakes screen, no UI dump if not locked
            ok = fast_open(intent)
            print(f"  {'OK' if ok else 'FAIL'}")
            return ok
        return False

    # Send / Search: need IME for text input + UI dump
    try:
        enable_u2_ime()
        nodes = ensure_unlocked()

        if itype == "send":
            ok = fast_send(intent, nodes)
            print(f"  {'OK' if ok else 'FAIL'} — fast send")
            return ok

        if itype == "search":
            ok = fast_search(intent, nodes)
            print(f"  {'OK' if ok else 'FAIL'} — fast search")
            return ok
    finally:
        restore_ime()

    return False
