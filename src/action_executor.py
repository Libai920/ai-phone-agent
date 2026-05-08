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

    # 2. Resource ID match
    if rid:
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
    """Tap the center of a matched node."""
    node = _find_node(nodes, target)
    if node is None:
        raise RuntimeError(f"No node matched target: {target}")
    cx, cy = _center(node["bounds"])
    adb("shell", "input", "tap", str(cx), str(cy))
    time.sleep(0.5)
    return node


def input_text(text):
    """Type text into the currently focused input field."""
    # Escape special characters for ADB
    safe = text.replace(" ", "%s").replace("&", "\\&")
    adb("shell", "input", "text", safe)
    time.sleep(0.3)


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


def execute(nodes, action):
    """Dispatch a single action.

    action: {
        "action": "click" | "input" | "swipe" | "back",
        "target": {"text": "..."} | {"resource_id": "..."} | null,
        "text": "..." (for input),
        "direction": "up"|"down"|"left"|"right" (for swipe)
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
