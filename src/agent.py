"""Multi-step agent: plans, executes, verifies, and re-plans on failure."""

import json
import time
import sys

from ui_reader import get_ui_state
from action_executor import execute, unlock
from planner import plan, next_step

MAX_ITERATIONS = 8
SLEEP_AFTER_ACTION = 1.2


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


def _print_plan(plan_list):
    for s in plan_list:
        print(f"    {s['step']}. {s['description']} → {s.get('expected_page', '?')}")


def run(task):
    """Execute a multi-step task with re-planning on failure.

    Returns True on success.
    """
    print(f"\n{'='*50}")
    print(f"Task: {task}")
    print(f"{'='*50}")

    # Phase 0: ensure unlocked
    nodes = get_ui_state()
    if len(nodes) <= 2:
        print("[0] Phone appears locked, waking...")
        unlock()
        nodes = get_ui_state()

    # Phase 1: initial plan
    print(f"\n[1] Reading screen: {len(nodes)} nodes")

    print("[2] Planning with DeepSeek...")
    result = plan(task, nodes)
    plan_steps = result.get("plan", [])
    action = result.get("next_action", {})

    print(f"  Plan ({len(plan_steps)} steps):")
    _print_plan(plan_steps)
    print(f"  First action: {action.get('action')} target={action.get('target')}")
    print(f"  Assert: {action.get('assert')}")

    plan_idx = 0
    history = []
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        current_step = plan_steps[plan_idx] if plan_idx < len(plan_steps) else None
        step_desc = current_step.get("description", "?") if current_step else "?"

        print(f"\n--- Step {plan_idx+1}/{len(plan_steps)} (iter {iteration}) ---")
        print(f"  Goal: {step_desc}")

        # Execute
        nodes_before = nodes
        print(f"  Action: {action.get('action')} {action.get('target', '')}")
        try:
            hit = execute(nodes_before, action)
            if hit:
                label = hit.get("text") or hit.get("content_desc") or hit.get("resource_id", "")
                print(f"  Executed on: {label} at {hit.get('bounds', '?')}")
        except RuntimeError as e:
            print(f"  EXEC FAIL: {e}")
            history.append({"step": plan_idx, "action": action, "result": f"exec_fail: {e}"})
            # Re-plan
            nodes = get_ui_state()
            print("  Re-planning after exec failure...")
            result = next_step(task, json.dumps(plan_steps, ensure_ascii=False), f"FAIL: {e}", nodes)
            plan_steps = result.get("plan_revision", result.get("plan", plan_steps))
            action = result.get("next_action", {})
            plan_idx = 0
            if not action:
                print("  No more actions, giving up.")
                return False
            continue

        time.sleep(SLEEP_AFTER_ACTION)

        # Verify
        nodes_after = get_ui_state()
        ok, msg = check_assert(nodes_before, nodes_after, action)
        print(f"  Verify: {'OK' if ok else 'FAIL'} — {msg}")
        print(f"  Screen: {len(nodes_before)} → {len(nodes_after)} nodes")

        history.append({"step": plan_idx, "action": action, "result": msg, "ok": ok})

        if ok:
            plan_idx += 1
            nodes = nodes_after

            if plan_idx >= len(plan_steps):
                print(f"\n{'='*50}")
                print(f"ALL STEPS COMPLETE ({len(plan_steps)} steps, {iteration} iterations)")
                print(f"{'='*50}")
                return True

            # Get next action from plan
            print(f"\n  → Advancing to step {plan_idx+1}: {plan_steps[plan_idx].get('description', '?')}")
            result = next_step(
                task,
                json.dumps(plan_steps, ensure_ascii=False),
                f"Previous step OK: {msg}",
                nodes,
            )
            action = result.get("next_action", {})
            if not action:
                print("  No next_action, assuming plan complete.")
                return True
        else:
            # Re-plan
            print(f"\n  ! Assert failed, re-planning...")
            result = next_step(
                task,
                json.dumps(plan_steps, ensure_ascii=False),
                f"FAIL: {msg}. The current screen does not match expectations.",
                nodes_after,
            )
            if "plan_revision" in result:
                plan_steps = result["plan_revision"]
                plan_idx = 0
                print(f"  Revised plan ({len(plan_steps)} steps):")
                _print_plan(plan_steps)
            action = result.get("next_action", {})
            if not action:
                print("  No revised action, giving up.")
                return False
            nodes = nodes_after

    print(f"\n  Max iterations ({MAX_ITERATIONS}) reached.")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py <task>")
        print("Example: python agent.py 打开微信")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    success = run(task)
    sys.exit(0 if success else 1)
