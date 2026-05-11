"""Multi-step agent: plans, executes, verifies, and re-plans on failure."""

import json
import time
import sys

from ui_reader import get_ui_state
from action_executor import execute, unlock, press_home
from planner import plan, next_step

MAX_ITERATIONS = 12
SAME_TARGET_RETRIES = 2
SLEEP_AFTER_ACTION = 1.2
LOCK_THRESHOLD = 5  # nodes <= this means probably locked


def _ensure_unlocked():
    """Check if phone is awake and unlocked. Fix it if not."""
    nodes = get_ui_state()
    if len(nodes) <= LOCK_THRESHOLD:
        print(f"  [!] Phone appears locked ({len(nodes)} nodes), waking...")
        unlock()
        time.sleep(1.0)
        nodes = get_ui_state()
        print(f"  [!] After unlock: {len(nodes)} nodes")
    return nodes


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
    nodes = _ensure_unlocked()

    # Phase 1: initial plan
    print(f"\n[1] Reading screen: {len(nodes)} nodes")

    print("[2] Planning with DeepSeek...")
    try:
        result = plan(task, nodes)
        plan_steps = result.get("plan", [])
        action = result.get("next_action", {})
        if not plan_steps and not action:
            print(f"  PLAN FAIL: empty response — {json.dumps(result, ensure_ascii=False)[:200]}")
            return False
        if not action:
            # Maybe the task is already done? Just pick first plan step
            print(f"  WARNING: no next_action, using plan only")
            action = {}
    except Exception as e:
        print(f"  PLAN FAIL: {e}")
        return False

    print(f"  Plan ({len(plan_steps)} steps):")
    _print_plan(plan_steps)
    print(f"  First action: {action.get('action')} target={action.get('target')}")
    print(f"  Assert: {action.get('assert')}")

    plan_idx = 0
    history = []
    iteration = 0
    last_failed_target = None
    same_target_fails = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        current_step = plan_steps[plan_idx] if plan_idx < len(plan_steps) else None
        step_desc = current_step.get("description", "?") if current_step else "?"

        print(f"\n--- Step {plan_idx+1}/{len(plan_steps)} (iter {iteration}) ---")
        print(f"  Goal: {step_desc}")

        # Ensure still unlocked before acting
        nodes_before = _ensure_unlocked()

        # Execute
        if not action or "action" not in action:
            print(f"  No valid action, skipping — action={action}")
            break
        act_label = action.get('action')
        if act_label == 'input':
            print(f"  Action: input '{action.get('text', '')}'")
        elif act_label == 'launch':
            pkg = action.get('package', '') or action.get('app', '?')
            print(f"  Action: launch {pkg}")
        else:
            print(f"  Action: {act_label} {action.get('target', '')}")
        try:
            hit = execute(nodes_before, action)
            if hit:
                label = hit.get("text") or hit.get("content_desc") or hit.get("resource_id", "")
                print(f"  Executed on: {label} at {hit.get('bounds', '?')}")
        except RuntimeError as e:
            print(f"  EXEC FAIL: {e}")
            # Track repeated failures on same target
            target_key = str(action.get("target", ""))
            if target_key == last_failed_target and target_key:
                same_target_fails += 1
            else:
                same_target_fails = 1
                last_failed_target = target_key

            history.append({"step": plan_idx, "action": action, "result": f"exec_fail: {e}"})
            # Re-plan
            nodes = _ensure_unlocked()
            hint = ""
            if same_target_fails > SAME_TARGET_RETRIES:
                hint = " (Previous attempts with the same target failed — try a completely different approach, use text/desc from the ACTUAL UI tree, NOT made-up resource IDs)"
                print(f"  ! Repeated target failure ({same_target_fails}x), asking for new approach")
            print(f"  Re-planning after exec failure{hint}...")
            try:
                result = next_step(task, json.dumps(plan_steps, ensure_ascii=False), f"FAIL: {e}{hint}", nodes)
                plan_steps = result.get("plan_revision", result.get("plan", plan_steps))
                action = result.get("next_action", {})
                if action.get("target"):
                    last_failed_target = str(action.get("target", ""))
            except Exception as re:
                print(f"  RE-PLAN FAIL: {re}")
                return False
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
            try:
                result = next_step(
                    task,
                    json.dumps(plan_steps, ensure_ascii=False),
                    f"Previous step OK: {msg}",
                    nodes,
                )
                action = result.get("next_action", {})
            except Exception as e:
                print(f"  NEXT_STEP FAIL: {e}")
                return False
            if not action:
                print("  No next_action, assuming plan complete.")
                return True
        else:
            # Re-plan
            print(f"\n  ! Assert failed, re-planning...")
            try:
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
            except Exception as e:
                print(f"  RE-PLAN FAIL: {e}")
                return False
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
