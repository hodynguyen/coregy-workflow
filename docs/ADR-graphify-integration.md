# ADR: Graphify Knowledge Graph Integration

> Architecture Decision Record for integrating Graphify into the Coregy Workflow plugin.

| Field       | Value                                |
|-------------|--------------------------------------|
| **Status**  | Proposed                             |
| **Date**    | 2026-04-13                           |
| **Version** | v0.8.3                               |
| **Author**  | architect agent                      |
| **Scope**   | Plugin-wide (hooks, commands, agents)|

---

## Table of Contents

- [1. Context](#1-context)
- [2. Decision](#2-decision)
- [3. Phased Rollout](#3-phased-rollout)
- [4. Architecture](#4-architecture)
- [5. MCP Server Configuration](#5-mcp-server-configuration)
- [6. Agent Integration Pattern](#6-agent-integration-pattern)
- [7. Dependencies and Requirements](#7-dependencies-and-requirements)
- [8. Risks and Mitigations](#8-risks-and-mitigations)
- [9. Performance Considerations](#9-performance-considerations)
- [10. Alternatives Considered](#10-alternatives-considered)

---

## 1. Context

### The Problem

Coregy Workflow agents currently operate with two sources of structural knowledge: the project profile (`.coregy/profile.yaml`) and the accumulated knowledge base (`.coregy/knowledge/`). Both are text-based and manually curated. When an agent needs to answer questions like "what calls this function?", "what is the blast radius of changing this module?", or "which components depend on this service?", it must either:

1. **Read source files directly** -- which consumes enormous context window budget (a 61-file Python project is ~50K tokens of raw source), or
2. **Rely on KB entries** -- which are only as good as what previous agents wrote, and go stale as code changes.

Neither approach gives agents reliable, queryable structural knowledge about the codebase.

### Why Graphify

Graphify is a knowledge graph tool that uses tree-sitter AST extraction to turn codebases into queryable graphs. Running on this repository (61 Python files) produced:

- **1,392 nodes** and **1,582 edges** capturing file, class, function, method, and rationale entities
- **graph.json of ~304 KB** versus ~21 MB of raw source -- a **71x token reduction**
- God node detection correctly identified `main()`, `_now()`, `load_state()`, `TestDevOps`
- 100% EXTRACTED confidence (no LLM needed for the structural pass)
- 20 language support via tree-sitter, 30+ file extensions

The key insight: agents do not need to read source code to understand structure. A graph query like "get neighbors of function X" returns callers, callees, and containing module in a few hundred tokens, versus reading the entire file (hundreds to thousands of tokens).

### Why Now

The plugin is at v0.7.1 with all 6 original phases complete. The next capability gap is structural code intelligence. Graphify is a natural fit because:

- It already exposes an MCP server (7 tools), which aligns with the plugin's existing MCP integration pattern (`/coregy-workflow:connect`)
- It is optional and does not require changes to the core detection pipeline
- The graph is filesystem-based (JSON), matching the plugin's "no persistent state except filesystem" constraint
- It addresses the most common agent limitation reported: lack of call-graph and dependency awareness

---

## 2. Decision

**Integrate Graphify as an optional MCP-based capability, following the same pattern as GitHub/Linear/Jira integrations.** Graphify will be registered via `/coregy-workflow:connect graphify`, its MCP tools will be available to agents that declare them, and the SessionStart hook will inject a graph summary when a graph is available.

### Design Principles

1. **Optional, not required.** The plugin must work identically without Graphify installed. No agent prompt should break if graph tools are unavailable.
2. **MCP-first.** Agents access the graph exclusively through MCP tool calls, not through direct Python imports or file reads of graph.json.
3. **Lazy and cached.** Graph builds happen on explicit user action (`/init --graph`, `/refresh --graph`), not automatically. Graphify's SHA256 file-content cache ensures rebuilds are incremental.
4. **Graceful degradation.** The hook checks for graph availability and injects a summary only when present. Agents check for tool availability before attempting graph queries.

---

## 3. Phased Rollout

### Phase 1: Minimum Viable Integration (v0.8.0)

**Goal:** Prove value with smallest change set. Three files modified.

| File | Change | Effort |
|------|--------|--------|
| `commands/connect.md` | Add Graphify as a fourth integration option alongside GitHub/Linear/Jira. Guide user through `pip install graphifyy`, graph build, and MCP server config. | Low |
| `hooks/inject_project_context.py` | Check for `graphify-out/graph.json`. If present, inject a compact summary: node/edge counts, top god nodes, community count. ~200 tokens max. | Low |
| `agents/code-reviewer.md` | Add a "Graphify MCP Tools" section with usage patterns for blast radius analysis, god node detection, and coupling checks. | Low |

**Deliverable:** Code reviewer can query the graph to assess change impact. Users configure Graphify through the existing `/connect` workflow.

**Validation criteria:**
- Code reviewer agent successfully calls `get_neighbors` and `god_nodes` MCP tools
- Hook injects graph summary without exceeding 30s timeout
- Plugin works normally when Graphify is not installed

### Phase 2: Agent Expansion (v0.8.1)

**Goal:** Extend graph access to the agents that benefit most.

| File | Change | Effort |
|------|--------|--------|
| `agents/architect.md` | Add graph tools for module boundary analysis, coupling detection, community structure. | Low |
| `agents/backend.md` | Add graph tools for caller/callee lookup, dependency tracing. | Low |
| `agents/frontend.md` | Add graph tools for component dependency trees, shared state detection. | Low |
| `commands/init.md` | Add optional `--graph` flag to run `graphify extract` after profile detection. | Low-Medium |
| `commands/refresh.md` | Add optional `--graph` flag to rebuild graph alongside profile refresh. | Low |

**Deliverable:** Four agents have graph-aware capabilities. Graph build integrated into init/refresh workflow.

### Phase 3: KB Auto-Population and Change Tracking (v0.8.2)

**Goal:** Use Graphify's wiki and diff capabilities to keep the KB current.

| Component | Change | Effort |
|-----------|--------|--------|
| KB templates | Auto-populate `architecture.md` from Graphify community articles. Map communities to architectural modules. | Medium |
| `kb_index.py` | Index graph metadata (god nodes, community names) alongside KB sections. | Medium |
| Change tracking | Use `graph_diff()` between builds to detect structural changes. Surface in `/status` and auto-update relevant KB sections. | Medium |
| Remaining agents | Add graph tool sections to `unit-tester.md`, `integration-tester.md`, `spec-verifier.md`, `researcher.md`, `devops.md`. | Low |

**Deliverable:** Knowledge base stays structurally current via graph diffs. All 9 agents have graph access.

---

## 4. Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        COREGY WORKFLOW PLUGIN                          │
│                                                                      │
│  ┌────────────────────┐    ┌──────────────────────────────────────┐  │
│  │  LAYER 1: PROFILE  │    │  GRAPHIFY (optional, external)      │  │
│  │  .coregy/profile.yaml│    │                                      │  │
│  │  integrations:     │    │  graphify-out/                       │  │
│  │    graphify: true  │───>│  ├── graph.json  (nodes + edges)    │  │
│  └────────────────────┘    │  ├── cache/      (per-file SHA256)  │  │
│           │                │  └── wiki/       (community articles)│  │
│           v                └──────────┬───────────────────────────┘  │
│  ┌────────────────────┐               │                              │
│  │  LAYER 2: KB       │               │ MCP stdio                   │
│  │  .coregy/knowledge/  │<──────────────┤                              │
│  │  (enriched by      │    ┌──────────┴───────────────────────────┐  │
│  │   graph data)      │    │  GRAPHIFY MCP SERVER                 │  │
│  └────────────────────┘    │  7 tools: query_graph, get_node,     │  │
│           │                │  get_neighbors, get_community,       │  │
│           v                │  god_nodes, graph_stats, shortest_path│  │
│  ┌────────────────────┐    └──────────┬───────────────────────────┘  │
│  │  LAYER 3: AGENTS   │               │                              │
│  │  9 agents ─────────│───────────────┘                              │
│  │  (MCP tool calls)  │  Agents call graph tools via MCP protocol   │
│  └────────────────────┘                                              │
└──────────────────────────────────────────────────────────────────────┘
```

### Data Flow: Session Start with Graphify

```
User starts Claude Code session
        │
        v
[Hook: inject_project_context.py]
        │
        ├── Read .coregy/profile.yaml          (always)
        ├── Read .coregy/state.json            (always, if exists)
        ├── Check graphify-out/graph.json    (new: if exists)
        │       │
        │       ├── YES: parse graph stats
        │       │        inject summary block:
        │       │        "Graph: 1392 nodes, 1582 edges
        │       │         God nodes: main(), load_state()
        │       │         Communities: 12"
        │       │
        │       └── NO: skip (no graph available)
        │
        v
System message includes profile + graph summary
        │
        v
Agent receives request
        │
        ├── Reads profile.yaml (stack context)
        ├── Reads knowledge base (accumulated context)
        ├── Sees graph summary in system message (structural context)
        │
        ├── Needs structural detail?
        │       │
        │       ├── YES: calls MCP tools
        │       │        e.g. get_neighbors("detect_stack.main")
        │       │        e.g. god_nodes(top_n=5)
        │       │
        │       └── NO: proceeds with text-based context only
        │
        v
Agent completes work, writes to KB
```

### Data Flow: Graph Build

```
User runs /coregy-workflow:init --graph
  (or /coregy-workflow:refresh --graph)
        │
        v
[detect_stack.py]  ───>  .coregy/profile.yaml
        │
        v
[/graphify skill]  ───>  graphify-out/
  Invokes the Graphify       ├── graph.json  (nodes + edges + communities)
  Claude Code skill          ├── cache/      (SHA256 per-file)
  which orchestrates:        ├── wiki/       (optional, Phase 3)
  1. detect (file scan)      └── GRAPH_REPORT.md
  2. extract (AST, local)
  3. semantic (LLM, optional)
  4. cluster + analyze
  5. export
        │
        v
Update profile.yaml:
  integrations:
    graphify: true

Note: Graphify does NOT expose `extract` or `cluster` as standalone CLI
commands. Graph building is orchestrated by the /graphify skill (Claude
reads SKILL.md and runs Python modules via Bash). Alternatively, Python
modules can be imported directly:
  from graphify.extract import extract
  from graphify.build import build
```

### MCP Connection Architecture

```
┌─────────────┐     stdio      ┌──────────────────┐     file read     ┌────────────────┐
│ Claude Code  │ <──────────> │ graphify serve    │ <───────────────> │ graph.json     │
│ (host)       │   JSON-RPC   │ (MCP server)      │                   │ (304 KB)       │
│              │              │                    │                   │                │
│ Agent calls: │              │ Loads graph into   │                   │ 1392 nodes     │
│ get_neighbors│              │ memory at startup. │                   │ 1582 edges     │
│ god_nodes    │              │ Answers queries    │                   │ SHA256 cached  │
│ query_graph  │              │ from in-memory     │                   │                │
│ ...          │              │ NetworkX graph.    │                   │                │
└─────────────┘              └──────────────────┘                   └────────────────┘
```

---

## 5. MCP Server Configuration

### Claude Code settings.json

The Graphify MCP server is registered in the user's Claude Code settings, not in the plugin itself. The `/coregy-workflow:connect graphify` command guides the user to add this configuration.

```json
{
  "mcpServers": {
    "graphify": {
      "command": "python3",
      "args": ["-m", "graphify.serve", "graphify-out/graph.json"],
      "cwd": "/absolute/path/to/project"
    }
  }
}
```

**Critical note on `cwd`:** Graphify's cache is cwd-relative. The `cwd` field must point to the project root. The graph path argument is relative to `cwd`. If `cwd` is omitted, the MCP server may fail to locate `graphify-out/graph.json`.

**Note:** The graph path is passed as a CLI argument to `graphify.serve`, not via environment variable. The `serve()` function reads `sys.argv[1]` with a default of `"graphify-out/graph.json"`.

### Alternative: Project-scoped config

For per-project configuration, the entry goes in `.claude/settings.json` at the project root:

```json
{
  "mcpServers": {
    "graphify": {
      "command": "python3",
      "args": ["-m", "graphify.serve", "graphify-out/graph.json"]
    }
  }
}
```

When using project-scoped config, `cwd` defaults to the project root, so it can be omitted.

### Alternative: Graphify's built-in installer

Graphify provides its own `graphify claude install` command, which:
- Copies `SKILL.md` to `~/.claude/skills/graphify/`
- Adds a PreToolUse hook to CLAUDE.md
- Registers the skill in Claude Code's configuration

This approach installs Graphify as a standalone Claude Code skill (invoked via `/graphify`), separate from coregy-workflow. It is an alternative to the MCP-based integration described here. The two approaches are compatible — a project could use both the `/graphify` skill for graph building and the coregy-workflow MCP integration for agent-level graph queries.

### Verifying the MCP Server

After configuration, the user restarts Claude Code. The connect command instructs them to verify with:

```
Ask Claude: "What MCP tools do you have from graphify?"
Expected: query_graph, get_node, get_neighbors, get_community, god_nodes, graph_stats, shortest_path
```

---

## 6. Agent Integration Pattern

### General Pattern

Every agent that uses Graphify follows this structure in its `.md` prompt file:

```markdown
## Graphify MCP Tools (optional)

If the Graphify MCP server is available, use these tools to get structural
code intelligence. Check tool availability before calling — the graph may
not be configured for this project.

Available tools:
- `query_graph(query)` — natural language graph query
- `get_node(label)` — get a specific node's metadata by label or ID
- `get_neighbors(label, relation_filter)` — get connected nodes, optionally filtered by relation type
- `get_community(community_id)` — get all nodes in a detected community/module
- `god_nodes(top_n)` — find high-coupling nodes (most connections)
- `graph_stats()` — graph-wide statistics
- `shortest_path(source, target)` — find dependency path between nodes

Node ID format: path segments joined by underscores, lowercased
Example: `plugins_coregy_workflow_skills_project_profile_scripts_state_py` (file),
         `init_workflow` (function), `testfeaturelog` (class)
```

### Agent-Specific Integration: Code Reviewer

The code reviewer benefits most from Graphify. It uses the graph to assess change impact beyond what a diff reveals.

**Blast radius analysis:**
```
When reviewing a PR that modifies function X:
1. Call get_neighbors(label="function_X") to find all connected nodes
   (callers, callees, containing module)
2. Call get_neighbors(label="function_X", relation_filter="calls")
   to see only call relationships
3. Report the blast radius: "This function is connected to N other entities
   across M files. Changes here affect: [list connected nodes]."
```

**God node warning:**
```
At the start of any review:
1. Call god_nodes(top_n=10)
2. Cross-reference with the files in the PR diff
3. If any changed file contains a god node, flag it:
   "WARNING: This PR modifies god node `main()` (47 connections).
   Changes to high-coupling nodes have elevated risk. Verify all
   callers are compatible with the change."
```

**Coupling check:**
```
When the PR adds a new import or function call:
1. Call shortest_path(source="new_module", target="existing_module")
2. If the path length is 1 (direct dependency), note it
3. If it creates a cycle, flag it as a coupling concern
```

### Agent-Specific Integration: Architect

The architect uses Graphify to validate and discover module boundaries.

**Module boundary validation:**
```
When designing a new feature that spans modules:
1. Call graph_stats() to understand current architecture shape
2. Call get_community(community_id=N) for relevant communities
3. Verify the proposed design respects existing module boundaries
4. If the design requires cross-community calls, document the
   coupling trade-off in the ADR
```

**Dependency direction enforcement:**
```
When reviewing architecture compliance:
1. Call get_neighbors(label="public_api", relation_filter="imports")
2. Check which files import the module
3. Verify callers are from expected layers (e.g., commands call
   detectors, not the reverse)
4. Flag any dependency direction violations
```

### Agent-Specific Integration: Backend

The backend agent uses Graphify to understand existing code before making changes.

**Pre-implementation reconnaissance:**
```
Before implementing a new feature:
1. Call query_graph("functions related to [feature area]")
2. Call get_neighbors for each relevant function to understand the
   existing call graph
3. Identify the correct insertion point that minimizes new coupling
4. Call god_nodes(top_n=5) to know which modules to avoid
   touching if possible
```

**Impact preview:**
```
Before modifying an existing function:
1. Call get_neighbors(label="target_function", relation_filter="calls")
2. List all callers and callees that will be affected
3. Verify parameter changes are backward-compatible, or plan
   migration for each caller
```

---

## 7. Dependencies and Requirements

### Required (for Graphify itself)

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python | >= 3.10 | Graphify hard requirement (uses match/case, type unions) |
| tree-sitter | >= 0.23.0 | Language API v2 for AST extraction |
| networkx | any | Graph data structure and algorithms |

**Note on Python version:** The coregy-workflow plugin itself requires Python 3.8+. Graphify requires 3.10+. Since Graphify is optional, this does not raise the plugin's minimum version. The `/connect graphify` command must check `python3 --version` and warn if < 3.10.

### Optional (for Graphify features)

| Dependency | Purpose | Install size |
|-----------|---------|-------------|
| graspologic | Leiden community detection (better than Louvain fallback) | ~20 MB |
| watchdog | File watching for auto-rebuild | ~5 MB |
| mcp | MCP server protocol (required for agent integration) | ~50 MB |

### Total footprint

- Graphify venv without MCP: ~76 MB
- Graphify venv with MCP: ~150 MB
- graph.json for this repo (61 files): ~304 KB

### What the plugin does NOT depend on

The coregy-workflow plugin itself gains zero new dependencies. All Graphify interaction is via:
1. MCP protocol (handled by Claude Code runtime)
2. File existence checks in the hook (`os.path.exists`, `json.load`)
3. Shell commands in the connect/init/refresh commands (`graphify query`, `graphify benchmark`), or the `/graphify` skill for graph building

---

## 8. Risks and Mitigations

| # | Risk | Severity | Likelihood | Mitigation |
|---|------|----------|------------|------------|
| 1 | **Hook timeout.** Parsing graph.json in the SessionStart hook exceeds the 30s timeout for very large graphs. | Medium | Low | Read only the `metadata` key from graph.json (first few KB). Do not load the full node/edge arrays. For graphs > 10 MB, skip injection and log a warning. The hook currently completes in < 1s for 304 KB. |
| 2 | **Graph staleness.** Code changes but graph is not rebuilt, causing agents to act on outdated structural data. | Medium | Medium | Document that `/refresh --graph` should be run after significant refactors. In Phase 3, use `graph_diff()` to detect staleness and surface warnings in `/status`. The hook could compare graph.json mtime against source file mtimes (same pattern as profile staleness check). |
| 3 | **MCP server not running.** User configured Graphify but the MCP server process is not active when agents try to call tools. | Medium | Medium | Agents must check tool availability before calling. The prompt pattern includes "Check tool availability before calling." Claude Code surfaces tool availability in the system message, so agents see whether graphify tools exist. |
| 4 | **Python version mismatch.** User has Python 3.8/3.9, Graphify requires 3.10+. | Low | Medium | `/connect graphify` checks Python version first and provides clear error: "Graphify requires Python 3.10+. Your current version is 3.X." Suggest pyenv or system upgrade. |
| 5 | **Large graph.json in repo.** Users accidentally commit graphify-out/ to git. | Low | Medium | `/connect graphify` appends `graphify-out/` to `.gitignore` if not already present. The init command does the same. |
| 6 | **Node ID instability.** File or function renames change node IDs, breaking cached references in KB entries. | Low | Low | Node IDs are derived from file path + AST position, so they change on rename by design. KB entries should reference logical names, not node IDs. Graph queries by name pattern (`query_graph`) are more resilient than exact ID lookups. |
| 7 | **Cross-file resolution limited to Python.** Other languages get per-file AST but no `uses` edges across files. | Medium | High (for non-Python) | Document this limitation clearly. Per-file `contains`, `calls` (intra-file), `imports`, and `inherits` edges are still valuable. Cross-file resolution for other languages is on Graphify's roadmap. |
| 8 | **Agent over-reliance on graph.** Agents call graph tools for every task, wasting tool-call budget on simple changes. | Low | Low | Agent prompts include guidance: "Use graph tools when the change spans multiple modules or when you need to understand callers/dependencies. For single-file, single-function changes, direct code reading is sufficient." |

---

## 9. Performance Considerations

### Token Reduction

| Metric | Without Graphify | With Graphify | Reduction |
|--------|-----------------|---------------|-----------|
| Full codebase context (61 files) | ~50,000 tokens | ~700 tokens (graph summary) | 71x |
| Single function context | ~500-2000 tokens (read file) | ~100-300 tokens (get_neighbors) | 3-7x |
| Module overview | ~5,000-10,000 tokens (read multiple files) | ~500 tokens (get_community) | 10-20x |

The primary token savings come from the hook-injected summary replacing the need for agents to read source files to understand project structure. Agents still read source files when they need to see implementation details, but structural queries (who calls what, what depends on what) go through the graph.

### Caching Strategy

Graphify uses a two-level cache:

1. **File-level cache** (`graphify-out/cache/{sha256}.json`): SHA256 of file content + path. Only changed files are re-extracted on rebuild. This means incremental rebuilds after small changes are fast (< 5s for a few changed files).

2. **Graph-level cache** (`graphify-out/graph.json`): The full assembled graph. Rebuilt from cached file extractions. For this repo, full build from warm cache takes < 3s.

### Hook Timeout Budget

The SessionStart hook has a 30s timeout. Current hook execution is < 2s. The Graphify addition must:

- Open `graphify-out/graph.json` and read only metadata (not full graph)
- Parse the metadata JSON object (node count, edge count, communities)
- Format a summary string (~200 tokens)
- **Budget: < 500ms additional** for a 304 KB graph.json
- **Safety cutoff: skip if graph.json > 10 MB** to avoid timeout risk on massive monorepos

Implementation approach for the hook:

```
Read first 4 KB of graph.json
  -> Parse metadata block (node_count, edge_count, communities)
  -> If metadata not in first 4 KB, fall back to os.path.getsize() for rough estimate
  -> Format summary
  -> Total: < 100ms for typical graphs
```

---

## 10. Alternatives Considered

### Alternative 1: Direct Python Import

**Approach:** Import Graphify's Python API directly in hook scripts and detector modules.

**Rejected because:**
- Adds a hard dependency (tree-sitter, networkx) to the plugin's requirements
- Breaks the "stdlib + PyYAML only" dependency policy
- Forces Python 3.10+ on all users, not just those who want graph features
- Violates the plugin's architecture: agents are Markdown prompts that use tools, not Python libraries

### Alternative 2: Graphify as Required Dependency

**Approach:** Make graph extraction part of the standard `/init` flow, always build a graph.

**Rejected because:**
- 150 MB venv footprint for a feature not all projects need
- Python 3.10+ requirement would exclude users on older systems
- Build time (even a few seconds) adds friction to first-run experience
- Many small projects (< 10 files) get negligible benefit from a knowledge graph
- Violates the principle that the plugin should work immediately after install

### Alternative 3: File-Based Integration (No MCP)

**Approach:** Agents read `graphify-out/graph.json` directly using the Read tool, parse JSON in-prompt.

**Rejected because:**
- graph.json is 304 KB for 61 files -- far too large for context window
- Agents would need to understand the graph schema and write JSON queries in-prompt
- No query optimization -- every question loads the full graph
- MCP tools provide natural-language-friendly interfaces (`get_neighbors`, `god_nodes`)
- The MCP server holds the graph in memory and answers queries efficiently

### Alternative 4: Custom Graph Implementation

**Approach:** Build a lightweight graph extractor within the plugin using only stdlib.

**Rejected because:**
- tree-sitter provides production-grade AST parsing for 20 languages; reimplementing even a subset is months of work
- networkx graph algorithms (shortest path, community detection) are well-tested
- Graphify already exists, is tested, and handles edge cases (caching, incremental builds, language configs)
- Maintaining a custom graph engine is outside the plugin's core competency

---

## Appendix A: File Change Summary by Phase

### Phase 1 (v0.8.0) -- 3 files

```
plugins/coregy-workflow/
  commands/connect.md                    [MODIFY] Add Graphify integration option
  hooks/inject_project_context.py        [MODIFY] Add graph summary injection
  agents/code-reviewer.md               [MODIFY] Add Graphify MCP Tools section
```

### Phase 2 (v0.8.1) -- 5 files

```
plugins/coregy-workflow/
  agents/architect.md                    [MODIFY] Add Graphify MCP Tools section
  agents/backend.md                      [MODIFY] Add Graphify MCP Tools section
  agents/frontend.md                     [MODIFY] Add Graphify MCP Tools section
  commands/init.md                       [MODIFY] Add --graph flag
  commands/refresh.md                    [MODIFY] Add --graph flag
```

### Phase 3 (v0.8.2) -- 7+ files

```
plugins/coregy-workflow/
  agents/unit-tester.md                  [MODIFY] Add Graphify MCP Tools section
  agents/integration-tester.md           [MODIFY] Add Graphify MCP Tools section
  agents/spec-verifier.md               [MODIFY] Add Graphify MCP Tools section
  agents/researcher.md                   [MODIFY] Add Graphify MCP Tools section
  agents/devops.md                       [MODIFY] Add Graphify MCP Tools section
  skills/project-profile/scripts/kb_index.py  [MODIFY] Index graph metadata
  skills/knowledge-base/templates/       [MODIFY] Graph-aware KB population
```

---

## Appendix B: Graphify MCP Tool Reference

| Tool | Parameters | Returns | Primary Agent Use |
|------|-----------|---------|-------------------|
| `query_graph` | `question: str, mode: bfs\|dfs, depth: int, token_budget: int` | BFS/DFS traversal results as text with nodes and edges | All agents: general-purpose exploration |
| `get_node` | `label: str` | Single node with ID, source file, location, type, community, degree | Backend: understanding a specific function |
| `get_neighbors` | `label: str, relation_filter?: str` | List of connected nodes with edge relation and confidence | Code reviewer: blast radius; Backend: callers |
| `get_community` | `community_id: int` | All nodes belonging to a detected community/module | Architect: module boundary analysis |
| `god_nodes` | `top_n?: int (default 10)` | Nodes ranked by edge count (highest coupling) | Code reviewer: risk assessment |
| `graph_stats` | (none) | Node count, edge count, community count, confidence breakdown (% EXTRACTED/INFERRED/AMBIGUOUS) | Hook injection; Architect: overview |
| `shortest_path` | `source: str, target: str, max_hops?: int (default 8)` | Ordered path of nodes with edge relations between them | Architect: dependency chain analysis |

---

## Appendix C: Example Hook Output

When `graphify-out/graph.json` is present, the SessionStart hook appends this block to the system message:

```
## Code Graph (Graphify)
- Nodes: 1392 (files: 61, classes: 45, functions: 312, methods: 974)
- Edges: 1582 (contains: 890, calls: 412, imports: 180, inherits: 24, other: 76)
- Communities: 12
- God nodes: main() [47 connections], _now() [38], load_state() [35], TestDevOps [31]
- Graph built: 2026-04-13T10:30:00Z
- Use Graphify MCP tools (query_graph, get_neighbors, god_nodes, ...) for structural queries.
```

Estimated token count: ~120 tokens. This replaces thousands of tokens that agents would otherwise spend reading source files to build a mental model of the codebase structure.
