"""DeepSeek planner — converts user task + UI tree into structured actions.

Uses DeepSeek's Anthropic-compatible Messages API.
"""

import json
import os
from anthropic import Anthropic


# DeepSeek endpoint via Anthropic SDK
API_KEY = os.environ.get(
    "ANTHROPIC_AUTH_TOKEN",
    "sk-93dd731b07ba47cd9db1ff280e07c737",
)
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
MODEL = os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=API_KEY, base_url=BASE_URL)
    return _client


SYSTEM_PROMPT = """You are an AI that controls an Android phone. You receive the current UI state (a list of interactive elements) and a user's task. You must produce a structured plan and the next action to take.

## Output format

Always respond with valid JSON only, no other text:

```json
{
  "plan": [
    {"step": 1, "description": "...", "expected_page": "..."},
    {"step": 2, "description": "...", "expected_page": "..."}
  ],
  "next_action": {
    "action": "click",
    "target": {"text": "微信"},
    "assert": {"text_contains": "通讯录"}
  }
}
```

## Action types

- **click**: Tap a UI element. Target by text (exact or substring), resource_id, or content_desc.
- **input**: Type text into the currently focused field. Use `{"action": "input", "text": "hello"}`.
- **swipe**: Scroll the screen. Use `{"action": "swipe", "direction": "up"}` (up/down/left/right).
- **back**: Press the Android back button. Use `{"action": "back"}`.

## Assert

Every next_action must include an assert field. Assert describes what should be visible on screen after the action succeeds. This is how the system verifies the action worked. Use:
- `text_contains`: text that should appear after the action
- `page_changed`: true if the screen should be different after the action

If assert fails, the system will send you the new UI state and you must revise the plan.

## Rules

1. Generate a plan first, then the first action. The plan describes every step needed to complete the task.
2. Use the user's prior knowledge of the app — you know how common apps work.
3. Match targets to actual elements in the UI tree. Use exact text from the UI tree.
4. If no matching element exists for your target, return a plan-revision with alternative targets.
5. Keep plans concise but complete. Do not skip verification steps.
"""


def _build_ui_context(nodes, max_nodes=60):
    """Turn node list into a compact text representation for the LLM."""
    lines = []
    for i, n in enumerate(nodes[:max_nodes]):
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
    """Pull the first text block from response content, skipping thinking blocks."""
    for block in content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise RuntimeError("No text block in response")


def plan(task, nodes):
    """First call: generate a full plan and the first action.

    Returns: {"plan": [...], "next_action": {...}}
    """
    ui_text = _build_ui_context(nodes)
    user_msg = f"Task: {task}\n\nCurrent UI elements:\n{ui_text}"

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp.content)
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


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
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp.content)
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


if __name__ == "__main__":
    from ui_reader import get_ui_state

    nodes = get_ui_state()
    print(f"UI: {len(nodes)} nodes\n")

    task = "打开微信"
    print(f"Task: {task}\n")
    print("Sending to DeepSeek...\n")

    result = plan(task, nodes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
