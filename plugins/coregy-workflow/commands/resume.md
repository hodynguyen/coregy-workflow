---
description: Resume an interrupted workflow. Respects persisted execution mode (auto/guided/manual). Override with 'auto', 'manual', or 'guided'.
argument-hint: "[optional: 'auto', 'manual', 'guided', 'skip <agent>', 'restart <agent>']"
---

# /coregy-workflow:resume

Resume an interrupted feature workflow from where it left off.

## User Instructions

$ARGUMENTS

If the section above contains text, apply it as guidance for this resume:
- "auto" → override execution mode to `auto` (update state.json, auto-run all remaining agents)
- "manual" → override execution mode to `manual` (update state.json, pause between agents)
- "guided" → override execution mode to `guided` (update state.json, auto-run after spec confirmed)
- "skip <agent>" → mark that agent as skipped in state.json before computing next
- "restart <agent>" → clear that agent's checkpoint and start fresh
- "continue from <agent>" → jump directly to that agent instead of the default next
- "focus on <area>" → pass this as additional context to the next agent

If empty, resume normally using the execution mode persisted in state.json (default: `guided`).

## Steps

Before resuming, check tracker for additional context about this workflow and related items:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py context --cwd .
```

1. **Check for active workflow**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py show --json --cwd .
```

Exit 1 means there is no workflow. Also treat a `status` other than `"in_progress"` as
nothing to resume. Either way, inform the user:

```
No active workflow found. Start one with /coregy-workflow:start-feature
```

Otherwise branch on `spec_confirmed` from this JSON in step 5.

2. **Display workflow state**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py show --cwd .
```

Present it in the richer form below (the script output is ASCII; the icons are yours):

```
Resuming Workflow
━━━━━━━━━━━━━━━━
Feature: [feature description]
Type: [feature type]
Mode: [auto | guided | manual]
Spec: [✅ Confirmed | ⚠️ Pending — discovery incomplete]
Started: [created_at]

Progress: ██████░░░░ 3/8 agents (37%)

  THINK:  ✅ researcher → ✅ architect
  BUILD:  🔄 backend → ⬜ frontend
  VERIFY: ⬜ unit-tester → ⬜ code-reviewer
  SHIP:   ⬜ devops
```

Use these icons:
- ✅ completed
- 🔄 active (in progress)
- ⏭️ skipped
- ⬜ pending

3. **Show completed agent summaries**: For each completed agent in `agent_log`, show:

```
Completed work:
  ✅ researcher — "Researched OAuth2 vs JWT" (updated: decisions.md)
  ✅ architect — "Designed API contracts" (updated: architecture.md, api-contracts.md)
```

4. **Check for agent checkpoints**: Check if there are saved checkpoints from interrupted agents:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py checkpoint-list --workflow-id <workflow_id> --cwd .
```

If a checkpoint exists for the next agent, display it:

```
📌 Checkpoint found for [agent name]:
   Progress: [completed_items]/[total_items] items done
   Last updated: [updated_at]
   Resume from: [resume_hint]
```

5. **Branch based on spec status**:

### If `spec_confirmed` is `false` or missing → Continue Discovery

The spec was not finalized before the session was interrupted. Continue the discovery process:

- Read any partial spec or notes from KB
- Re-read the feature description and type from state.json
- Resume asking clarifying questions from where discovery left off
- Once the user confirms the spec, record it and proceed to auto-execution (same as
  start-feature Phase C):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py confirm-spec \
  --spec-file "spec-<slug>.md" --cwd .
```

### If `spec_confirmed` is `true` → Execute Remaining Agents

The spec is confirmed — run remaining agents based on execution mode.

a. **Apply mode override**: If the user passed a mode argument, persist it. Otherwise use
   the mode already in state.json (default: `guided`).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py set-mode <auto|guided|manual> --cwd .
```

If `$ARGUMENTS` is `skip <agent>`, mark it skipped before computing the next agent:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py skip-agent <agent> --cwd .
```

b. **Read the spec and log**: Read `.coregy/knowledge/<spec_file>` for the confirmed spec and `.coregy/knowledge/<log_file>` for work already done by previous agents.

c. **Identify remaining agents**: Loop on

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py next-agent --json --cwd .
```

until `agent` is `null`. This subcommand always exits 0, so branch on the content.
A non-null `escalation` means a fix loop stopped and is waiting on the user: show its
`gate`, `escalation_reason` and `issues` and offer accept / one more round / abort exactly as
in start-feature's **Fix loop** step — in every mode — before starting any agent.

d. **Run agents based on execution mode**: For the agent `next-agent` returned (re-ask after
   each one — a gate's `request-fixes` sends the workflow back to BUILD):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py start-agent <agent> --cwd .
   ```
   - A non-null `checkpoint` in that JSON means the agent was interrupted: pass its
     `partial_output`, `resume_hint` and completed/pending items so it continues rather
     than restarting. A null checkpoint means start fresh.
   - A non-null `fix_round` means this run is part of the fix loop: pass its `gate` and
     `issues` to the agent (a BUILD agent fixes exactly those; the gate re-checks them first).
   - Activate the agent (it reads profile.yaml + KB + spec file)
   - When the agent completes:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py complete-agent <agent> \
       --summary "<one line>" --kb-files "<comma,separated>" --cwd .
     ```
   - Show one-line status:
     ```
     ✅ backend completed — "Implemented 5 API endpoints" → Starting unit-tester...
     ```

   **Mode-specific behavior after each agent:**
   - **`auto` or `guided`**: **Immediately** proceed to next agent — do NOT pause.
   - **`manual`**: Pause and show a review prompt. Wait for user to respond with `continue`, `skip`, or `abort`.

e. **Complete workflow**: After all agents finish:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py complete --cwd .
```

Then show the final summary.

### If all agents already completed

Inform the user and offer to complete the workflow:

```
All agents have completed their work.
Would you like to:
  1. Complete this workflow
  2. Re-run a specific agent
  3. Start a new feature with /coregy-workflow:start-feature
```

For "restart `<agent>`", clear its checkpoint first, then run it as in step 5d:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py checkpoint-clear \
  --workflow-id <workflow_id> --agent <agent> --cwd .
```

To abandon the workflow instead:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/state.py abort --cwd .
```

## Output

### Final Summary (after all agents complete)
```
Workflow Complete
━━━━━━━━━━━━━━━━

Feature: [description]
Spec: .coregy/knowledge/[spec_file]
Log:  .coregy/knowledge/[log_file]

Agent Results:
  ✅ researcher  — [summary]
  ✅ architect   — [summary]
  ✅ backend     — [summary]
  ✅ unit-tester — [summary]
  ✅ code-reviewer — [summary]

KB Files Updated:
  → architecture.md
  → api-contracts.md
  → decisions.md
```

## Notes

- This command is the counterpart to `/coregy-workflow:start-feature` — start begins, resume continues
- **Key behavior**: Respects the `execution_mode` persisted in state.json. Override with `auto`, `guided`, or `manual` argument.
- If spec is confirmed → execute remaining agents per mode. If spec is pending → continue discovery.
- Workflow state (including execution mode) persists in `.coregy/state.json` across sessions
- The knowledge base files modified by previous agents are available to the next agent automatically
- **Checkpoints**: When an agent is interrupted (context limit, disconnect, etc.), its checkpoint in `tracker.db` preserves exactly what work was done. On resume, the agent receives the checkpoint data so it can skip already-completed items and continue from `resume_hint`.
- Mode override updates state.json, so subsequent resumes will use the new mode
