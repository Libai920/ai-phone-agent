"""Single-step agent: wires UI reader, planner, and action executor together."""

import json
import time
import sys
from pathlib import Path

from ui_reader import get_ui_state
from action_executor import execute, press_back
from planner import plan


def check_assert(nodes_before, nodes_after, action_spec):
    """Simple assert check. Returns (ok, message)."""
    assertion = action_spec.get("assert", {})

    # Check text_contains
    expected = assertion.get("text_contains", "")
    if expected:
        for n in nodes_after:
            if expected.lower() in (n["text"] + n["content_desc"]).lower():
                return True, f"Found '{expected}' on screen"

    # Check page_changed
    if assertion.get("page_changed"):
        before_ids = {n.get("text") + n.get("content_desc") + n.get("resource_id") for n in nodes_before}
        after_ids = {n.get("text") + n.get("content_desc") + n.get("resource_id") for n in nodes_after}
        if before_ids != after_ids:
            return True, "Page changed"
        else:
            return False, "Page did not change"

    # No assertion → assume success
    return True, "No assertion to check"


def run(task):
    """Execute a single-step task. Returns True on success."""
    print(f"\n{'='*50}")
    print(f"Task: {task}")
    print(f"{'='*50}")

    # 1. Get current UI state
    print("\n[1/4] Reading screen...")
    nodes_before = get_ui_state()
    print(f"  {len(nodes_before)} interactive elements found")

    # 2. Plan
    print("\n[2/4] Planning with DeepSeek...")
    result = plan(task, nodes_before)

    action_plan = result.get("plan", [])
    next_action = result.get("next_action", {})

    print(f"  Plan: {len(action_plan)} steps")
    for s in action_plan:
        print(f"    {s['step']}. {s['description']} → {s['expected_page']}")
    print(f"  Action: {next_action.get('action')} target={next_action.get('target')}")
    print(f"  Assert: {next_action.get('assert')}")

    # 3. Execute
    print("\n[3/4] Executing...")
    try:
        hit = execute(nodes_before, next_action)
        if hit:
            label = hit.get("text") or hit.get("content_desc") or hit.get("resource_id", "")
            print(f"  Clicked: {label}")
    except RuntimeError as e:
        print(f"  FAILED: {e}")
        return False

    # Wait for UI to settle
    time.sleep(1.0)

    # 4. Verify
    print("\n[4/4] Verifying...")
    nodes_after = get_ui_state()
    ok, msg = check_assert(nodes_before, nodes_after, next_action)
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")
    print(f"  Screen: {len(nodes_before)} → {len(nodes_after)} nodes")

    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py <task>")
        print("Example: python agent.py 打开微信")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    success = run(task)
    sys.exit(0 if success else 1)
