"""Multi-step agent: plans, executes, verifies, and re-plans on failure."""

import json
import time
import sys

from ui_reader import get_ui_state
from action_executor import execute, enable_u2_ime, restore_ime, ensure_unlocked, check_assert, screencap
from fast_agent import fast_run, parse_intent

MAX_ITERATIONS = 12
SAME_TARGET_RETRIES = 2
SLEEP_AFTER_ACTION = 0.5
SCREENSHOT_TASK_KEYWORDS = [
    "看看",
    "看一下",
    "分析",
    "识别",
    "判断",
    "推荐",
    "哪个",
    "更好",
    "第几个",
    "页面",
    "截图",
    "结果",
    "总结",
    "比较",
]


def _prefers_screenshot(task):
    """Return True when the task needs visual page understanding."""
    return any(keyword in task for keyword in SCREENSHOT_TASK_KEYWORDS)


def _print_plan(plan_list):
    for s in plan_list:
        print(f"    {s['step']}. {s['description']} → {s.get('expected_page', '?')}")


# Maps query keywords → (app_name, app_label) for auto-selection
_RESEARCH_APP_GUESS = [
    (["吃", "饭", "美食", "外卖", "猪脚", "鸡腿", "面", "奶茶", "火锅", "烧烤", "咖啡",
      "早餐", "午餐", "晚餐", "小吃", "甜品", "蛋糕", "炸鸡", "汉堡", "寿司", "披萨",
      "餐厅", "饭店", "馆子", "好吃"], ("美团", "美团")),
    (["教程", "学习", "课程", "教学", "入门", "实战", "视频", "讲解", "怎么", "如何"], ("bilibili", "B站")),
    (["穿搭", "攻略", "测评", "探店", "好物", "种草", "打卡", "拍照"], ("小红书", "小红书")),
    (["买", "价格", "便宜", "优惠", "正品", "包邮"], ("淘宝", "淘宝")),
    (["新闻", "热点", "最新", "今天"], ("知乎", "知乎")),
]


def _guess_app(query):
    """Guess the best app for a research query based on keywords."""
    for keywords, (app_name, _) in _RESEARCH_APP_GUESS:
        for kw in keywords:
            if kw in query:
                return app_name
    return "小红书"  # default fallback


def _do_research(task, intent):
    """Execute a research intent: search → screenshot → analyze → return results."""
    from researcher import research

    app = intent.get("app")
    query = intent["query"]

    if not app:
        app = _guess_app(query)
        print(f"\n  → 自动选择 {app} 搜索")

    try:
        return research(task, app, query)
    except Exception as e:
        print(f"  Research FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def _do_pick_nth(n):
    """Tap the Nth result from the last research session.

    Reads cached research results, gets the tap_bounds for result N,
    and taps its center.
    """
    from pathlib import Path
    cache_file = Path(__file__).parent / "last_research.json"

    if not cache_file.exists():
        print(f"  No previous search results. Try searching first.")
        return False

    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        results = cached.get("results", [])
    except Exception:
        print(f"  Failed to read cached results.")
        return False

    if n < 1 or n > len(results):
        print(f"  Result #{n} not found (have {len(results)} results).")
        return False

    result = results[n - 1]
    title = result.get("title", "?")
    bounds = result.get("tap_bounds")

    if not bounds or len(bounds) < 4:
        print(f"  Result #{n} ({title}) has no tap coordinates. Taking fresh screenshot...")
        # Fallback: take fresh screenshot, ask LLM to find the result
        b64, w, h = screencap()
        if not b64:
            print(f"  Screenshot failed.")
            return False
        prompt = (
            f"Previous search results:\n{json.dumps(results, ensure_ascii=False)}\n\n"
            f"The user wants to tap result #{n}: \"{title}\".\n"
            f"Look at this screenshot (the search results page) and return a JSON object "
            f"with only the tap coordinates: {{\"tap_bounds\": [x1, y1, x2, y2]}}.\n"
            f"The screenshot is {w}x{h} pixels. Estimate where \"{title}\" is on screen."
        )
        try:
            from planner import analyze_screenshots
            # Use a lightweight call — just get coordinates
            coord_result = analyze_screenshots(
                f"Find result {n}: {title}", "unknown", title, [b64]
            )
            # Result format might not match — extract bounds from results
            coord_results = coord_result.get("results", [])
            if coord_results and "tap_bounds" in coord_results[0]:
                bounds = coord_results[0]["tap_bounds"]
            else:
                # Try getting from tap_bounds at top level
                bounds = coord_result.get("tap_bounds")
                if not bounds:
                    print(f"  Could not determine tap coordinates.")
                    return False
        except Exception as e:
            print(f"  Coordinate fallback failed: {e}")
            return False

    # Tap center of bounds
    cx = (bounds[0] + bounds[2]) // 2
    cy = (bounds[1] + bounds[3]) // 2
    print(f"\n  Tapping result #{n}: {title}")
    print(f"  Coordinates: ({cx}, {cy}) — bounds={bounds}")

    from action_executor import adb, ensure_unlocked
    ensure_unlocked()
    adb("shell", "input", "tap", str(cx), str(cy))

    # Take a quick screenshot to confirm
    import time
    time.sleep(1.0)
    confirm_b64, _, _ = screencap()
    if confirm_b64:
        print(f"  Done! Check the phone screen.")

    return True


def run(task):
    """Execute a task. Fast path for simple ops, LLM for complex ones.

    Returns True on success.
    """
    # Pick-Nth path: tap the Nth result from last research
    intent = parse_intent(task)
    if intent and intent["type"] == "pick_nth":
        return _do_pick_nth(intent["n"])

    # Research path: search → screenshot → analyze → recommend
    if intent and intent["type"] == "research":
        try:
            result = _do_research(task, intent)
            return result is not None and result.get("results")
        finally:
            restore_ime()

    # Fast path: no LLM, rule-based execution
    if fast_run(task):
        return True

    # Slow path: LLM planning + execution
    try:
        return _run(task)
    finally:
        restore_ime()


def _run(task):
    """Inner run — IME is managed by outer run()."""
    from planner import plan, next_step

    print(f"\n{'='*50}")
    print(f"Task: {task}")
    print(f"{'='*50}")

    # Phase 0: ensure unlocked, enable fast IME
    nodes = ensure_unlocked()
    enable_u2_ime()

    # Phase 1: initial plan — use screenshots if UI tree is too sparse
    print(f"\n[1] Reading screen: {len(nodes)} nodes")
    prefer_screenshot = _prefers_screenshot(task)
    use_screenshots = prefer_screenshot or len(nodes) < 5

    if prefer_screenshot:
        print("[2] Visual task, switching to screenshot mode...")
        return _run_with_screenshots(task)
    if len(nodes) < 5:
        print("[2] UI tree sparse, switching to screenshot mode...")
        return _run_with_screenshots(task)

    print("[2] Planning with DeepSeek...")
    try:
        result = plan(task, nodes)
        plan_steps = result.get("plan", [])
        action = result.get("next_action", {})
        if not plan_steps and not action:
            print(f"  PLAN FAIL: empty response — {json.dumps(result, ensure_ascii=False)[:200]}")
            return False
        if not action:
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
        nodes_before = ensure_unlocked()

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
            result = execute(nodes_before, action)
            hit = result.get("hit")
            if hit:
                label = hit.get("text") or hit.get("content_desc") or hit.get("resource_id", "")
                print(f"  Executed on: {label} at {hit.get('bounds', '?')}")
            else:
                print(f"  Executed: {result.get('message', action.get('action', 'ok'))}")
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
            nodes = ensure_unlocked()
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


def _run_with_screenshots(task):
    """Slow path using screenshots instead of UI tree (for apps that hide accessibility)."""
    from planner import plan_with_screenshot, next_step_with_screenshot, verify_screenshot_action

    print(f"\n{'='*50}")
    print(f"Task: {task}  [SCREENSHOT MODE]")
    print(f"{'='*50}")

    # Take initial screenshot
    b64, w, h = screencap()
    if not b64:
        print("  SCREENSHOT FAILED")
        return False
    print(f"  Screenshot: {w}x{h}")

    print("[1] Planning with screenshot...")
    try:
        result = plan_with_screenshot(task, b64)
        plan_steps = result.get("plan", [])
        action = result.get("next_action", {})
        if not action:
            print(f"  PLAN FAIL: no next_action")
            return False
    except Exception as e:
        print(f"  PLAN FAIL: {e}")
        return False

    print(f"  Plan ({len(plan_steps)} steps):")
    _print_plan(plan_steps)
    print(f"  First action: {action.get('action')} target={action.get('target')}")

    plan_idx = 0
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        current_step = plan_steps[plan_idx] if plan_idx < len(plan_steps) else None
        step_desc = current_step.get("description", "?") if current_step else "?"

        print(f"\n--- Step {plan_idx+1}/{len(plan_steps)} (iter {iteration}) ---")
        print(f"  Goal: {step_desc}")

        nodes_before = ensure_unlocked()

        if not action or "action" not in action:
            print(f"  No valid action, skipping")
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
            execute(nodes_before, action)
        except RuntimeError as e:
            print(f"  EXEC FAIL: {e}")
            history_text = json.dumps(plan_steps, ensure_ascii=False)
            b64, _, _ = screencap()
            if not b64:
                return False
            try:
                result = next_step_with_screenshot(task, history_text, f"FAIL: {e}", b64)
                plan_steps = result.get("plan_revision", result.get("plan", plan_steps))
                action = result.get("next_action", {})
            except Exception as re:
                print(f"  RE-PLAN FAIL: {re}")
                return False
            plan_idx = 0
            if not action:
                return False
            continue

        time.sleep(SLEEP_AFTER_ACTION)

        # Take new screenshot for verification
        b64, _, _ = screencap()
        if not b64:
            return False

        history_text = json.dumps(plan_steps, ensure_ascii=False)
        try:
            verification = verify_screenshot_action(
                task,
                action,
                action.get("assert", {}),
                b64,
            )
        except Exception as e:
            print(f"  VERIFY FAIL: {e}")
            verification = {"ok": False, "message": f"verification failed: {e}"}

        ok = verification.get("ok", False)
        msg = verification.get("message", "")
        print(f"  Verify: {'OK' if ok else 'FAIL'} — {msg}")

        if ok:
            plan_idx += 1
            nodes = ensure_unlocked()

            if plan_idx >= len(plan_steps):
                print(f"\n{'='*50}")
                print(f"ALL STEPS COMPLETE ({len(plan_steps)} steps, {iteration} iterations)")
                print(f"{'='*50}")
                return True

            # Get next action
            print(f"\n  → Advancing to step {plan_idx+1}: {plan_steps[plan_idx].get('description', '?')}")
            try:
                result = next_step_with_screenshot(task, history_text, f"OK: {msg}", b64)
                action = result.get("next_action", {})
            except Exception as e:
                print(f"  NEXT_STEP FAIL: {e}")
                return False
            if not action:
                print("  No next_action, assuming plan complete.")
                return True
        else:
            print(f"\n  ! Screenshot assert failed, re-planning...")
            try:
                result = next_step_with_screenshot(task, history_text, f"FAIL: {msg}", b64)
                plan_steps = result.get("plan_revision", result.get("plan", plan_steps))
                action = result.get("next_action", {})
                plan_idx = 0
            except Exception as e:
                print(f"  RE-PLAN FAIL: {e}")
                return False
            if not action:
                print("  No revised action, giving up.")
                return False

    print(f"\n  Max iterations ({MAX_ITERATIONS}) reached.")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py [--dry-run] <task>")
        print("Example: python agent.py 打开微信")
        sys.exit(1)

    dry_run = sys.argv[1] == "--dry-run"
    args = sys.argv[2:] if dry_run else sys.argv[1:]
    if not args:
        print("Usage: python agent.py [--dry-run] <task>")
        sys.exit(1)

    task = " ".join(args)
    if dry_run:
        print(json.dumps({
            "task": task,
            "intent": parse_intent(task),
            "prefers_screenshot": _prefers_screenshot(task),
        }, ensure_ascii=False, indent=2))
        sys.exit(0)

    success = run(task)
    sys.exit(0 if success else 1)
