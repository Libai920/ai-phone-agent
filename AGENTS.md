# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project: AI Phone Agent

- **Repo:** https://github.com/Libai920/ai-phone-agent
- **Local:** E:\ai-phone-agent
- **Goal:** AI controls Android phone via ADB + DeepSeek

### Architecture

```
src/ui_reader.py       → adb uiautomator dump → filtered JSON
src/action_executor.py → JSON → adb input tap/swipe/text
src/planner.py         → DeepSeek API (Anthropic-compat) → plan + actions
src/agent.py           → orchestrator: read→plan→execute→verify→replan
```

### Key decisions (from grilled session)
- Android only (ADB, no iOS)
- Structured UI tree (no screenshots)
- DeepSeek v4 via Anthropic-compatible API
- Plan-first architecture with re-planning on assert failure
- Python + ADB proxy (no Android APK needed)
- ADB path: `E:/AA/platform-tools/adb.exe`
- Must use `//sdcard/` prefix for MSYS compatibility

### Running
```bash
python src/agent.py "打开知乎"
```

### Device
- vivo phone, serial 10AFBC22FT008G3
- ADB at E:/AA/platform-tools/adb.exe
- Common issue: phone locks after idle → agent auto-unlocks

### GitHub
- Token stored in environment/session
- gh CLI at: E:/tools/bin/gh.exe
