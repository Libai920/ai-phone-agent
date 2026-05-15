"""Research agent: search → screenshot → analyze → recommend.

Orchestrates the flow: open an app, search for something, take screenshots
of the results, send them to the LLM for analysis, and return structured
recommendations to the user.
"""

import time
import json
from pathlib import Path

from action_executor import (
    launch_and_wait, execute, screencap, enable_u2_ime, restore_ime,
    ensure_unlocked, resolve_package, launch_app, press_back,
)
from ui_reader import get_ui_state
from planner import analyze_screenshots

SLEEP = 0.5
RESEARCH_CACHE = Path(__file__).parent / "last_research.json"


def _safe_print(s):
    """Print safely on Windows GBK consoles."""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def research(task, app, query, num_screenshots=2):
    """Search an app for a query and return analyzed recommendations.

    Args:
        task: original user task string (e.g. "在B站搜大模型教程")
        app: app name in Chinese or English (e.g. "bilibili", "美团")
        query: search query string
        num_screenshots: how many screenshots to capture (scrolling between)

    Returns: dict with keys: type, app, results (list of recommendations)
    """
    print(f"\n{'='*50}")
    print(f"Research: {task}")
    print(f"  App: {app}  |  Query: {query}")
    print(f"{'='*50}")

    # Step 1: open app
    print(f"\n[1] Opening {app}...")
    package = resolve_package(app)
    current_nodes = ensure_unlocked()

    if package:
        launch_app(package=package)
        time.sleep(2.0)
        try:
            current_nodes = get_ui_state()
        except Exception:
            pass

    if not current_nodes or len(current_nodes) < 3:
        print(f"  [!] App opened but UI sparse, retrying...")
        time.sleep(1.5)
        try:
            current_nodes = get_ui_state()
        except Exception:
            pass

    if len(current_nodes) < 3:
        print(f"  [!] UI tree still sparse ({len(current_nodes)} nodes)")
        # Don't fail — we can still try screenshot mode for analysis

    # Step 2: find & click search bar
    print(f"[2] Finding search bar...")
    search_node = None
    for n in current_nodes:
        rid = n.get("resource_id", "").lower()
        cls = n.get("class", "").lower()
        desc = n.get("content_desc", "").lower()
        text = n.get("text", "").lower()
        if ("search" in rid or "search" in desc or "搜索" in text or "搜索" in desc or
                ("edit" in cls and n.get("clickable"))):
            if n.get("clickable") or n.get("focusable"):
                search_node = n
                break

    # Fallback: try any EditText near the top
    if not search_node:
        for n in current_nodes:
            cls = n.get("class", "").lower()
            if "edit" in cls or "input" in n.get("resource_id", "").lower():
                search_node = n
                break

    # Last resort: tap approximate top area for apps with no UI tree
    if not search_node:
        print(f"  [!] No search bar in UI tree, using coordinate fallback...")
        search_node = {
            "text": "",
            "resource_id": "",
            "bounds": "[300,150][960,300]",
            "clickable": True,
            "focusable": True,
        }

    enable_u2_ime()
    try:
        execute(current_nodes, {"action": "click", "target": {
            "text": search_node.get("text", ""),
            "resource_id": search_node.get("resource_id", ""),
        }})
    except RuntimeError:
        # If the UI tree click fails, try coordinate tap
        print(f"  [!] UI tree click failed, trying coordinate tap...")
        from action_executor import adb
        adb("shell", "input", "tap", "630", "200")
    time.sleep(0.8)

    # Step 3: type the query
    print(f"[3] Typing query: '{query}'...")
    execute([], {"action": "input", "text": query})
    time.sleep(1.2)

    # Try pressing search key on IME
    try:
        from action_executor import adb
        adb("shell", "input", "keyevent", "66")  # KEYCODE_ENTER
    except Exception:
        pass
    time.sleep(2.0)

    # Step 4: take screenshots, scrolling between
    print(f"[4] Capturing {num_screenshots} screenshot(s)...")
    screenshots = []

    for i in range(num_screenshots):
        if i > 0:
            # Scroll down for more results
            from action_executor import swipe
            swipe(630, 2000, 630, 800, duration=500)
            time.sleep(1.0)

        b64, w, h = screencap()
        if b64:
            screenshots.append(b64)
            print(f"  Screenshot {i+1}/{num_screenshots}: {w}x{h}")
        else:
            print(f"  Screenshot {i+1}/{num_screenshots}: FAILED")

    if not screenshots:
        print("  No screenshots captured, aborting.")
        restore_ime()
        return {"type": "error", "app": app, "results": [], "error": "Screenshot failed"}

    # Step 5: send to LLM for analysis
    print(f"[5] Analyzing with LLM...")
    try:
        result = analyze_screenshots(task, app, query, screenshots)
    except Exception as e:
        print(f"  Analysis FAILED: {e}")
        restore_ime()
        return {"type": "error", "app": app, "results": [], "error": str(e)}

    # Step 6: display results & cache
    print(f"\n{'─'*50}")
    result_type = result.get("type", "unknown")
    results = result.get("results", [])
    print(f"Analysis: {len(results)} results (type={result_type})")
    print(f"{'─'*50}")

    for i, r in enumerate(results):
        _safe_print(f"\n  [{i+1}] {r.get('title', '?')}")
        sub = r.get("subtitle", "")
        if sub:
            _safe_print(f"      {sub}")
        desc = r.get("description", "")
        if desc:
            _safe_print(f"      {desc}")
        rel = r.get("relevance", "?")
        action = r.get("action", "")
        bar = "=" * (rel // 2) if isinstance(rel, int) else ""
        _safe_print(f"      相关度: {rel}/10 {bar}")
        if action:
            _safe_print(f"      点击: {action}")

    # Cache results for "点第N个" follow-up
    try:
        RESEARCH_CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    print(f"\n{'─'*50}")
    print(f"Done. {len(results)} recommendations. Say '点第N个' to open one.")
    print(f"{'─'*50}")

    restore_ime()
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python researcher.py <app> <query>")
        print("Example: python researcher.py bilibili 大模型教程")
        sys.exit(1)

    app = sys.argv[1]
    query = " ".join(sys.argv[2:])
    task = f"在{app}搜{query}"
    result = research(task, app, query)
    print("\n--- Raw JSON ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
