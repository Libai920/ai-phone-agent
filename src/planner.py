"""DeepSeek planner — converts user task + UI tree into structured actions.

Uses DeepSeek's Anthropic-compatible Messages API.
"""

import json
import os
from anthropic import Anthropic


# DeepSeek endpoint via Anthropic SDK
API_KEY = os.environ["ANTHROPIC_AUTH_TOKEN"]
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
MODEL = os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=API_KEY, base_url=BASE_URL)
    return _client


SYSTEM_PROMPT = """You are an AI that controls an Android phone. You receive the current UI state (a list of interactive elements) and a user's task. You must produce a structured plan and the next action to take.

## CRITICAL: Output format

You MUST respond with ONLY this exact JSON structure — no other text, no markdown fences, no explanations:

{"plan":[{"step":1,"description":"...","expected_page":"..."}],"next_action":{"action":"click","target":{"text":"微信"},"assert":{"text_contains":"通讯录"}}}

The response must be a single JSON object with two keys: "plan" (array of step objects) and "next_action" (a single action object). NEVER output a bare action like {"action":"tap"} — always wrap it in the full structure.

## Action types

- click: Tap a UI element by text or content_desc. Example: {"action":"click","target":{"text":"微信"},"assert":{"page_changed":true}}
- input: Type text. Input does NOT change pages — always use text_contains (NOT page_changed). Example: {"action":"input","text":"牛鸡","assert":{"text_contains":"牛鸡"}}
- swipe: Scroll. Example: {"action":"swipe","direction":"up","assert":{"page_changed":true}}
- back: Press back. Example: {"action":"back","assert":{"page_changed":true}}
- launch: Start an app. ALWAYS use this to open apps instead of hunting for icons on the home screen. You can provide either "package" (if known) or "app" (the app name in Chinese/English, the system will resolve it). Examples: {"action":"launch","app":"QQ","assert":{"page_changed":true}} or {"action":"launch","package":"com.tencent.mobileqq","assert":{"page_changed":true}}

## Assert

Every next_action MUST include an assert field. Use:
- text_contains: text expected to appear after action (REQUIRED for input actions)
- page_changed: true if screen should change (do NOT use for input — typing does not change pages)

## Rules

1. Always output the full {"plan":[...],"next_action":{...}} structure — never a bare action
2. To OPEN an app, use launch with the package name (infer from resource_id). NEVER swipe around the home screen looking for icons
3. Match targets to EXACT text or content_desc from the UI element list provided
4. NEVER invent resource IDs — only use resource_id values that actually appear in the UI list
5. If no matching UI element exists, use a bounds target with approximate coordinates
6. Keep plans minimal — only the steps actually needed
"""


def _build_ui_context(nodes, max_nodes=100):
    """Turn node list into a compact text representation for the LLM.

    Always includes top 70% and bottom 30% of nodes — the bottom typically
    contains input fields, send buttons, and navigation that get truncated
    if we just take the first max_nodes.
    """
    total = len(nodes)
    if total <= max_nodes:
        selected = nodes
    else:
        top_n = int(max_nodes * 0.7)
        bottom_n = max_nodes - top_n
        selected = list(nodes[:top_n])
        if bottom_n > 0:
            selected.extend(nodes[-bottom_n:])

    lines = []
    for i, n in enumerate(selected):
        label = n["text"] or n["content_desc"] or n["resource_id"].split("/")[-1] or n["class"].split(".")[-1]
        rid = n["resource_id"] if n["resource_id"] else ""
        lines.append(
            f"{i}: {label} | class={n['class'].split('.')[-1]} "
            f"| rid={rid} "
            f"| bounds={n['bounds']} "
            f"| {'CLICK' if n['clickable'] else ''} {'FOCUS' if n['focusable'] else ''} {'SCROLL' if n['scrollable'] else ''}"
        )
    return "\n".join(lines)


def _extract_text(content):
    """Pull text blocks from response content, skipping thinking blocks."""
    texts = []
    for block in content:
        t = getattr(block, "text", None)
        if t:
            texts.append(t.strip())
    if texts:
        return "\n".join(texts)
    # If only thinking blocks, strip them and look for JSON
    thinking_texts = []
    for block in content:
        t = getattr(block, "thinking", None)
        if t:
            thinking_texts.append(t.strip())
    if thinking_texts:
        # DeepSeek sometimes wraps the real output inside thinking
        combined = "\n".join(thinking_texts)
        # Try to find JSON inside the thinking block
        return combined
    raise RuntimeError(f"No text or thinking in response: {str(content)[:200]}")


def _parse_json(text):
    """Robust JSON extraction from LLM response.

    Handles: markdown fences, leading/trailing junk, thinking blocks,
    bare actions without plan wrapper.
    """
    t = text.strip()

    # Strip markdown code fences of any flavor
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]

    # Try direct parse first
    try:
        result = json.loads(t)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        brace_start = t.find("{")
        result = None
        if brace_start >= 0:
            depth = 0
            in_string = False
            escape = False
            for i, ch in enumerate(t[brace_start:], brace_start):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = t[brace_start : i + 1]
                        try:
                            result = json.loads(candidate)
                        except json.JSONDecodeError:
                            pass
                        break

    if result is None:
        raise RuntimeError(f"Failed to parse JSON from response:\n{text[:500]}")

    # If DeepSeek returned a bare action, wrap it
    if "action" in result and "plan" not in result:
        result = {
            "plan": [{"step": 1, "description": f"Do: {result.get('action', '?')}", "expected_page": "?"}],
            "next_action": result,
        }

    return result


def plan(task, nodes):
    """First call: generate a full plan and the first action.

    Returns: {"plan": [...], "next_action": {...}}
    """
    ui_text = _build_ui_context(nodes)
    user_msg = f"Task: {task}\n\nCurrent UI elements:\n{ui_text}"

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp.content)
    return _parse_json(text)


def next_step(task, plan_text, last_assert_result, nodes):
    """Subsequent call: get the next action given the plan and current UI.

    Returns: {"next_action": {...}} or {"plan_revision": {...}}
    """
    ui_text = _build_ui_context(nodes)
    user_msg = (
        f"Task: {task}\n\n"
        f"Plan so far:\n{plan_text}\n\n"
        f"Last assert result: {last_assert_result}\n\n"
        f"Current UI elements:\n{ui_text}"
    )

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp.content)
    return _parse_json(text)


if __name__ == "__main__":
    from ui_reader import get_ui_state

    nodes = get_ui_state()
    print(f"UI: {len(nodes)} nodes\n")

    task = "打开微信"
    print(f"Task: {task}\n")
    print("Sending to DeepSeek...\n")

    result = plan(task, nodes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
