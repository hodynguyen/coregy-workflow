---
description: Start a spec-driven feature development workflow. Supports --auto (skip discovery, full auto), --manual (pause between agents), or default guided mode.
argument-hint: "[--auto|--manual] [feature description, e.g. 'add OAuth2 login, focus on security']"
---

# /coregy-workflow:start-feature

Start a spec-driven, multi-phase feature development workflow.

## User Instructions

$ARGUMENTS

If the section above contains text, first parse the **execution mode**, then treat the remainder as the feature description:

### Execution Mode

Parse the arguments for mode flags (case-insensitive):
- `--auto` or starts with `auto:` → set execution mode to **auto**
- `--manual` or starts with `manual:` → set execution mode to **manual**
- Neither → default to **guided**

Strip the mode flag from the remaining text before treating it as the feature description.

| Mode | Discovery | Spec | Agent Execution |
|------|-----------|------|-----------------|
| **auto** | Skip — auto-generate spec from description + KB | Auto-confirm (no user input) | Run all agents without stopping |
| **guided** (default) | Interactive — ask user questions | User confirms | Run all agents without stopping |
| **manual** | Interactive — ask user questions | User confirms | Pause between each agent for review |

### Feature Description

Use the remaining text (after stripping mode flag) to:
- Pre-fill step 2 (feature description) so you can skip asking if the description is clear enough
- Apply focus areas (e.g. "focus on security" → emphasize code-reviewer + spec-verifier)
- Narrow scope (e.g. "only backend" → skip frontend agent in BUILD)
- Override the default agent sequence if the user explicitly requests it

If empty and mode is `auto`, inform the user that `--auto` requires a feature description and fall back to `guided` mode.
If empty and mode is `guided` or `manual`, ask the user for the feature description normally.

## Workflow Overview

This command follows a **spec-driven development** approach:

```
DISCOVERY → SPEC CONFIRMATION → AUTO-EXECUTION
     ↑              │
     └──────────────┘  (iterate until user confirms)
```

1. **Discovery**: Ask all clarifying questions upfront, discuss trade-offs with user (**skipped in `auto` mode**)
2. **Spec Confirmation**: Summarize everything into a clear spec, user confirms (**auto-confirmed in `auto` mode**)
3. **Execution**: Run all agents in sequence (**pauses between agents in `manual` mode**). A
   reviewer, verifier or tester that finds blocking issues sends the work back to the BUILD
   agents and re-checks it — the **fix loop**, capped at `--max-fix-rounds` (default 3)

## Steps

### Phase A: Discovery

1. **Check initialization**: Verify `.coregy/profile.yaml` exists. If not, run `/coregy-workflow:init` first.

2. **Read project context**: Read `.coregy/profile.yaml` and all `.coregy/knowledge/` files to understand the current project state.

3. **Gather feature description**: If not provided in arguments, ask the user to describe the feature. (In `auto` mode, a description MUST be provided in arguments.)

4. **Classify feature type**: Based on the description, classify into one of these types:

| Type | Description |
|------|-------------|
| `new-feature` | Entirely new functionality |
| `bug-fix` | Fix a reported bug |
| `refactor` | Restructure existing code without changing behavior |
| `api-endpoint` | New or modified API endpoint |
| `ui-change` | Frontend-only change |
| `tech-spike` | Research and prototyping |
| `deployment` | Infrastructure or deployment change |
| `hotfix` | Urgent production fix |

5. **Generate discovery questions**: Based on the feature type, tech stack (from profile.yaml), and existing knowledge base, compile a **single batch** of all questions that need clarification. Group them by category:

**For `new-feature` / `api-endpoint`:**
- **Architecture**: Where does this fit in the current system? New service or extend existing?
- **API Design**: What endpoints are needed? Request/response shapes? Auth requirements?
- **Data Model**: New tables/collections? Schema changes? Migrations needed?
- **Business Logic**: What are the core rules? Edge cases? Error scenarios?
- **Frontend** (if applicable): What UI components? User flow? State management approach?
- **Testing**: Coverage requirements? Integration test scenarios? E2E needed?
- **Deployment**: Feature flags? Rollback plan? Environment-specific config?

**For `bug-fix` / `hotfix`:**
- **Reproduction**: Steps to reproduce? Which environments?
- **Root Cause**: Known cause or needs investigation? Related recent changes?
- **Scope**: Which components are affected? Is it isolated or systemic?
- **Testing**: How to verify the fix? Regression tests needed?

**For `refactor`:**
- **Scope**: Which modules/files? What patterns to introduce/remove?
- **Behavior**: Must behavior stay identical? Any acceptable changes?
- **Testing**: Existing test coverage? Additional tests needed?
- **Migration**: Breaking API changes? Backward compatibility needed?

**For `tech-spike`:**
- **Goal**: What question are we trying to answer?
- **Constraints**: Time box? Must integrate with existing stack?
- **Output**: Prototype? Comparison doc? ADR?

Present ALL questions at once. Let the user answer in any order, partially, or all at once.

6. **Iterate until clear**: If answers are vague or raise new questions, ask follow-ups. But always batch questions — never ask one at a time. Continue until you have enough information to write a spec.

**If mode is `auto`**: Skip steps 5-6 entirely. Instead, use the feature description from arguments combined with existing knowledge base context (architecture.md, api-contracts.md, decisions.md) to generate the spec directly. Make reasonable assumptions based on the codebase. Do NOT ask any questions — proceed straight to Phase B.

### Phase B: Spec Confirmation

7. **Write the spec**: Synthesize all discovery answers into a structured spec document. Present it to the user:

```
Feature Spec: [title]
━━━━━━━━━━━━━━━━━━━━

Type: [classified type]
Priority: [high/medium/low]

## Summary
[1-2 sentence description of what will be built]

## Requirements
- [Req 1]
- [Req 2]
- ...

## Technical Design
- Architecture: [approach]
- API Endpoints: [list with methods, paths, request/response]
- Data Model: [schema changes]
- Key Decisions: [trade-offs made during discovery]

## Out of Scope
- [What we explicitly won't do in this feature]

## Agent Workflow
  THINK:  [agents]
  BUILD:  [agents]
  VERIFY: [agents]
  SHIP:   [agents] (optional)

Estimated agents: [N] agents across [M] phases
```

8. **Get user confirmation**:

**If mode is `auto`**: Auto-confirm the spec. Show a brief 3-5 line summary of the spec so the user can see what was generated, but do NOT wait for input. Immediately proceed to execution.

**If mode is `guided` or `manual`**: Ask the user to confirm or request changes. The user may:
- Approve as-is → proceed to execution
- Request changes → update spec and re-present
- Add/remove agents → adjust the workflow
- Change scope → update requirements

Do NOT proceed to execution until the user explicitly confirms.

### Phase C: Execution

9. **Save spec to knowledge base**: Write the confirmed spec to `.coregy/knowledge/spec-<slugified-feature>.md` with YAML frontmatter:

```markdown
---
tags: [spec, <feature-type>, <relevant-tags>]
created: <YYYY-MM-DD>
author_agent: start-feature
status: confirmed
---

# Spec: [feature title]

[Full spec content from step 7]
```

10. **Create workflow state and feature log**: One call does both:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py init-workflow \
  --feature "<user's feature description>" \
  --type "<classified type>" \
  --phases '{"THINK":["architect"],"BUILD":["backend"],"VERIFY":["unit-tester","code-reviewer"]}' \
  --spec-file "spec-<slugified-feature>.md" \
  --mode <auto|guided|manual> \
  --spec-confirmed \
  --cwd .
```

This writes `.coregy/state.json` in the current schema and creates
`.coregy/knowledge/log-<slugified-feature>.md` with the correct frontmatter.
Do **not** hand-write either file.

- `--phases` takes a single-quoted JSON object mapping phase name to its agent list; use
  the sequence from "Agent Sequence by Feature Type" below.
- `--max-fix-rounds <n>` (default 3) caps how often each gate may send work back to BUILD.
  Pass it only when the user asks for a different limit.
- Exit 1 with "Active workflow ... in progress" means a workflow is already running —
  offer `/coregy-workflow:resume` rather than passing `--force`, which destroys it.

The log file is where each agent will append its detailed work record. It tracks:
- What each agent did (summary)
- Files created and modified in the codebase
- KB files updated
- Key decisions made

Also create a tracker item linked to the workflow — pass the `workflow_id` from the
`init-workflow` JSON output. The link is what lets `state.py` move the item to
`in_progress` when the first agent starts and to `completed`/`abandoned` when the
workflow ends; an unlinked item stays "created" forever:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py create \
  --type task \
  --title "<feature description>" \
  --tags "<relevant tags>" \
  --priority medium \
  --workflow-id "<workflow_id from init-workflow>" \
  --cwd .
```

11. **Run agents based on execution mode**: Do not walk the sequence from memory — the fix
   loop can send the workflow back to BUILD. Ask the state machine for the next agent each time:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py next-agent --json --cwd .
   ```
   Stop when `agent` is `null`. If `escalation` is non-null, handle it first (see **Fix loop**
   below) — do not start the agent it names. Otherwise, for that agent:
   - Mark it active:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py start-agent <agent> --cwd .
     ```
     If the JSON contains a non-null `checkpoint`, pass its `partial_output`, `resume_hint`
     and items to the agent so it continues instead of restarting. Surface any `warnings`.
     If `fix_round` is non-null, pass its `round`, `gate` and `issues` to the agent: a BUILD
     agent fixes exactly those issues; the gate re-checks them before anything else.
   - Activate the agent (it reads profile.yaml + KB + spec file + log file)
   - When the agent completes:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py complete-agent <agent> \
       --summary "<one line>" \
       --kb-files "architecture.md,decisions.md" \
       --cwd .
     ```
     The agent appends its own work record to the feature log via `state.py log-append`
     (files created/modified, KB updated, decisions) — do not write that entry by hand.
   - Show a one-line status update:
     ```
     ✅ researcher completed — "Researched OAuth2 providers" → Starting architect...
     ```

   **Mode-specific behavior after each agent:**

   - **`auto` or `guided`**: **Immediately** proceed to the next agent — do NOT pause to ask the user.
   - **`manual`**: Pause and show a review prompt:
     ```
     ✅ researcher completed — "Researched OAuth2 providers"

     Next: architect (THINK phase)
     → continue | skip | abort
     ```
     Wait for the user to respond before proceeding. `skip` →
     `state.py skip-agent <next agent> --cwd .`; `abort` → `state.py abort --cwd .`.

   **Parallel agents**: During BUILD phase, if both `frontend` and `backend` are present, run them in parallel (all modes).

   **Fix loop**: A gate agent (`code-reviewer`, `spec-verifier`, `unit-tester`,
   `integration-tester`) that finds **blocking** issues records them with
   `state.py request-fixes` instead of completing. Your follow-up `complete-agent` call for it is
   then a harmless no-op, and `next-agent` returns the BUILD agent(s) to fix, then the gate again.
   Show one line per round:
   ```
   🔁 code-reviewer → backend — fix round 1/3: 2 blocking issues
   ```
   This runs without pausing in `auto` and `guided` (in `manual`, the usual pause applies).

   **Escalation** — the loop stops itself when a gate has used all its rounds (`max_rounds`)
   or a round found no fewer issues than the previous one (`no_progress`). In **every** mode,
   including `auto`, show the remaining issues and ask the user:
   ```
   ⚠️ Fix loop stopped — code-reviewer (no_progress): 2 blocking issues remain
     - src/auth.py:42 token compared with ==
     - src/auth.py:88 missing expiry check
   → accept | one more round | abort
   ```
   - `accept` — continue with the issues logged:
     `state.py complete-agent <gate> --summary "accepted with open issues" --cwd .`, and add
     the issues to `tech-debt.md`
   - `one more round` — `state.py request-fixes <gate> --force-round --cwd .` (reuses the
     escalated issues), then continue the loop
   - `abort` — `state.py abort --cwd .`

12. **Complete workflow**: After all agents finish:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py complete --cwd .
```

This finalizes the feature log (appends the Summary section and flips the frontmatter to
`status: completed`), sets the workflow status and completes the linked tracker item in
one call. Then:
   - Show a final summary of all agent outputs
   - Update the spec file status to `implemented`

## Agent Sequence by Feature Type

| Type | Agent Sequence |
|------|---------------|
| `new-feature` | researcher → architect → frontend + backend → unit-tester → integration-tester → code-reviewer → spec-verifier |
| `bug-fix` | architect → frontend or backend → unit-tester → code-reviewer |
| `refactor` | code-reviewer (assess) → frontend or backend → unit-tester → code-reviewer (verify) |
| `api-endpoint` | architect → backend → integration-tester → code-reviewer |
| `ui-change` | frontend → unit-tester → code-reviewer |
| `tech-spike` | researcher → architect |
| `deployment` | devops |
| `hotfix` | frontend or backend → unit-tester → devops |

## Output

### During Discovery
- Present all questions grouped by category
- Show the iterative spec as it develops

### During Execution
- One-line per agent completion
- Final summary with all outputs

### Final Summary
```
Workflow Complete
━━━━━━━━━━━━━━━━

Feature: [description]
Type: [type]
Duration: [time from start to finish]

Agent Results:
  ✅ researcher  — [summary]
  ✅ architect   — [summary]
  ✅ backend     — [summary]
  ✅ frontend    — [summary]
  ✅ unit-tester — [summary]
  ✅ code-reviewer — [summary]

Fix rounds: [n] — [gate → fixer: resolved | accepted with open issues]   (omit if none)

KB Files Updated:
  → architecture.md
  → api-contracts.md
  → decisions.md

Spec: .coregy/knowledge/spec-<feature>.md
Log:  .coregy/knowledge/log-<feature>.md
```

## Notes

- **Three execution modes**: `auto` (no interaction), `guided` (interactive discovery, auto execution), `manual` (interactive discovery, pause between agents)
- **`auto` mode** skips discovery and spec confirmation — best for well-described features or simple tasks
- **`guided` mode** (default) iterates with the user until spec is clear, then runs agents without interruption
- **`manual` mode** gives full control — user reviews each agent's output before proceeding
- Frontend and backend agents can run in parallel during BUILD phase (all modes)
- SHIP phase (devops) is included only for deployment/hotfix types
- Each agent reads the spec file + KB, so context flows naturally between agents
- If interrupted, use `/coregy-workflow:resume` — it respects the persisted execution mode
- Workflow state (including `execution_mode`) is persisted in `.coregy/state.json`
- The feature log provides a complete audit trail of all work done — review it after workflow completes
