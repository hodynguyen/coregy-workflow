---
tags: [interaction-tracking, state-persistence, sqlite, phase-7, architecture]
created: 2026-03-21
author_agent: architect
status: active
---

# Interaction Tracking & State Persistence — Spec chi tiet

> Thiet ke toan dien cho he thong theo doi tuong tac va luu tru trang thai,
> thay the va mo rong `.coregy/state.json` hien tai.

---

## Muc luc

1. [Phan loai yeu cau (Request Classification Taxonomy)](#1-phan-loai-yeu-cau)
2. [Data Model / Schema SQLite](#2-data-model--schema-sqlite)
3. [State Machine theo tung loai](#3-state-machine-theo-tung-loai)
4. [Quan ly vong doi (Lifecycle Management)](#4-quan-ly-vong-doi)
5. [Awareness Layer — hien thi ngu canh](#5-awareness-layer)
6. [Diem tich hop (Integration Points)](#6-diem-tich-hop)
7. [Chien luoc di chuyen (Migration Strategy)](#7-chien-luoc-di-chuyen)
8. [API Surface](#8-api-surface)
9. [Cac truong hop dac biet (Edge Cases)](#9-cac-truong-hop-dac-biet)

---

## 1. Phan loai yeu cau

### 1.1. Cac loai chinh (Primary Types)

| Type | Mo ta | Vi du | Co state machine? |
|------|-------|-------|-------------------|
| `task` | Cong viec can build/fix/deploy. Map truc tiep voi workflow hien tai | "Them xac thuc OAuth2", "Fix loi payment timeout" | Co — day du |
| `investigation` | Tim hieu, phan tich, doc code. Khong thay doi code | "Giai thich cach auth module hoat dong", "Phan tich performance cua query nay" | Co — don gian |
| `question` | Cau hoi chung, co the lien quan hoac khong | "SQLite co support concurrent writes khong?", "Convention dat ten file la gi?" | Co — rat don gian |
| `discussion` | Thao luan kien truc, trade-off, khong co ket luan ngay | "Nen dung REST hay gRPC cho service nay?", "Monolith hay microservice?" | Co — trung binh |
| `maintenance` | Bao tri, cap nhat dependency, clean up, khong phai feature moi | "Cap nhat React len v19", "Xoa code deprecated" | Co — trung binh |

### 1.2. Metadata chung cho moi item

```python
{
    "id": "itm_<uuid4_short>",        # 12 ky tu, vi du: itm_a1b2c3d4e5f6
    "type": "task|investigation|question|discussion|maintenance",
    "title": "...",                     # Tieu de ngan gon (agent tu dong tao)
    "description": "...",              # Mo ta chi tiet hon (optional)
    "status": "...",                   # Trang thai hien tai (tuy loai)
    "priority": "high|medium|low",    # Mac dinh: medium
    "tags": ["auth", "payment", ...],  # Tags tu do, dung cho search
    "created_at": "ISO 8601 UTC",
    "updated_at": "ISO 8601 UTC",
    "completed_at": "ISO 8601 UTC | null",
    "session_id": "ses_<date>_<seq>",  # Session nao tao ra item nay
    "related_items": ["itm_xxx", ...], # Lien ket voi item khac
    "related_files": ["src/auth.py"],  # File lien quan
    "workflow_id": "feat-xxx | null",  # Chi co voi type=task, link den state.json workflow
    "kb_refs": ["decisions.md#ADR-005"], # Tham chieu den knowledge base
    "notes": "...",                    # Ghi chu bo sung (agent hoac user them)
}
```

### 1.3. Metadata rieng theo loai

**Task** (bo sung):
```python
{
    "feature_type": "new-feature|bug-fix|refactor|...",  # Tu start-feature taxonomy
    "agents_involved": ["architect", "backend"],
    "branch": "feat/oauth2-login",      # Git branch neu co
    "blocked_by": ["itm_xxx"],           # Dependency/blocker
    "estimated_complexity": "small|medium|large",
}
```

**Investigation** (bo sung):
```python
{
    "scope": ["src/auth/", "src/middleware/"],  # Pham vi tim hieu
    "findings": "...",                          # Ket qua chinh
    "led_to_task": "itm_xxx | null",            # Investigation dan den task nao
}
```

**Discussion** (bo sung):
```python
{
    "options_considered": ["REST", "gRPC", "GraphQL"],
    "conclusion": "...",            # Ket luan neu co
    "adr_ref": "ADR-005 | null",   # Neu ket luan tro thanh ADR
}
```

---

## 2. Data Model / Schema SQLite

Database file: `.coregy/tracker.db`

### 2.1. Schema

```sql
-- Chuyen doi schema bang pragma
PRAGMA journal_mode = WAL;        -- Write-Ahead Logging: an toan khi crash
PRAGMA foreign_keys = ON;

-- =====================================================
-- BANG CHINH: items
-- Moi yeu cau cua user la mot item
-- =====================================================
CREATE TABLE items (
    id          TEXT PRIMARY KEY,      -- itm_<12 chars>
    type        TEXT NOT NULL CHECK (type IN ('task','investigation','question','discussion','maintenance')),
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    status      TEXT NOT NULL,         -- Gia tri phu thuoc vao type (validate trong Python)
    priority    TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    created_at  TEXT NOT NULL,         -- ISO 8601
    updated_at  TEXT NOT NULL,
    completed_at TEXT,
    session_id  TEXT NOT NULL,
    workflow_id TEXT,                   -- Link den state.json workflow (chi cho task)
    notes       TEXT DEFAULT '',

    -- Metadata rieng theo type (luu dang JSON)
    extra       TEXT DEFAULT '{}'      -- JSON blob cho metadata dac thu cua tung type
);

-- =====================================================
-- BANG TAGS
-- Nhieu-nhieu: moi item co nhieu tags
-- =====================================================
CREATE TABLE item_tags (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (item_id, tag)
);

-- =====================================================
-- BANG LIEN KET FILE
-- Moi item co the lien quan den nhieu file
-- =====================================================
CREATE TABLE item_files (
    item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    filepath TEXT NOT NULL,
    PRIMARY KEY (item_id, filepath)
);

-- =====================================================
-- BANG LIEN KET GIUA CAC ITEM
-- Quan he: related, blocked_by, led_to, supersedes
-- =====================================================
CREATE TABLE item_relations (
    from_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    to_item_id   TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL CHECK (relation IN ('related','blocked_by','led_to','supersedes','parent','child')),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (from_item_id, to_item_id, relation)
);

-- =====================================================
-- BANG KB REFERENCES
-- Tham chieu den knowledge base entries
-- =====================================================
CREATE TABLE item_kb_refs (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kb_ref  TEXT NOT NULL,             -- Vi du: "decisions.md#ADR-005"
    PRIMARY KEY (item_id, kb_ref)
);

-- =====================================================
-- BANG STATUS TRANSITIONS (audit log)
-- Luu lai moi thay doi trang thai
-- =====================================================
CREATE TABLE status_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    from_status TEXT,                  -- null cho trang thai dau tien
    to_status  TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    reason     TEXT DEFAULT ''         -- Ly do chuyen trang thai
);

-- =====================================================
-- BANG SESSIONS
-- Theo doi cac phien lam viec
-- =====================================================
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,       -- ses_<YYYYMMDD>_<seq>
    started_at TEXT NOT NULL,
    ended_at   TEXT,                   -- null neu chua ket thuc
    summary    TEXT DEFAULT ''         -- Tu dong tao khi session ket thuc
);

-- =====================================================
-- INDEXES cho cac query thuong dung
-- =====================================================
CREATE INDEX idx_items_type ON items(type);
CREATE INDEX idx_items_status ON items(status);
CREATE INDEX idx_items_priority ON items(priority);
CREATE INDEX idx_items_created ON items(created_at);
CREATE INDEX idx_items_session ON items(session_id);
CREATE INDEX idx_items_workflow ON items(workflow_id);
CREATE INDEX idx_item_tags_tag ON item_tags(tag);
CREATE INDEX idx_status_log_item ON status_log(item_id);
CREATE INDEX idx_status_log_time ON status_log(changed_at);
CREATE INDEX idx_item_relations_to ON item_relations(to_item_id);
```

### 2.2. Ly do chon SQLite thay vi JSON

| Tieu chi | JSON (hien tai) | SQLite |
|----------|-----------------|--------|
| Query phuc tap | Phai load toan bo file, loc trong Python | SQL native, chi doc nhung gi can |
| Du lieu lon | Cham khi file lon | Hieu qua voi hang ngan ban ghi |
| Concurrent access | Nguy co race condition | WAL mode xu ly tot |
| Audit log | Phai tu implement | Table `status_log` |
| Lien ket du lieu | Nested JSON kho query | Foreign keys + join |
| Backup/migration | Copy file | Copy file (tuong tu) |
| Stdlib | Co (json) | Co (sqlite3) |

---

## 3. State Machine theo tung loai

### 3.1. Task

```
                    ┌──────────┐
                    │ created  │
                    └────┬─────┘
                         │ (user xac nhan / bat dau lam)
                    ┌────▼─────┐
              ┌─────│in_progress│─────┐
              │     └────┬─────┘      │
              │          │            │
        (block)│    (xong)│      (tam dung)│
              │          │            │
         ┌────▼───┐ ┌────▼────┐ ┌────▼───┐
         │blocked │ │completed│ │ paused │
         └────┬───┘ └─────────┘ └────┬───┘
              │                       │
              │ (unblock)             │ (resume)
              └───────►in_progress◄───┘
                            │
                       (huy bo)
                       ┌────▼─────┐
                       │abandoned │
                       └──────────┘
```

**Trang thai hop le:**
- `created` — Moi tao, chua bat dau
- `in_progress` — Dang lam
- `paused` — Tam dung (chuyen sang lam viec khac)
- `blocked` — Bi chan boi item/dieu kien khac
- `completed` — Hoan thanh
- `abandoned` — Huy bo (khong lam nua)

**Chuyen doi hop le:**
```python
TASK_TRANSITIONS = {
    "created":     ["in_progress", "abandoned"],
    "in_progress": ["completed", "paused", "blocked", "abandoned"],
    "paused":      ["in_progress", "abandoned"],
    "blocked":     ["in_progress", "abandoned"],
    "completed":   [],          # Terminal
    "abandoned":   [],          # Terminal
}
```

### 3.2. Investigation

```
    ┌────────┐     ┌───────────┐     ┌──────────┐
    │ started│────►│in_progress│────►│ concluded│
    └────────┘     └─────┬─────┘     └──────────┘
                         │
                    ┌────▼───┐
                    │ paused │
                    └────────┘
```

**Trang thai:** `started`, `in_progress`, `concluded`, `paused`, `abandoned`

```python
INVESTIGATION_TRANSITIONS = {
    "started":     ["in_progress", "abandoned"],
    "in_progress": ["concluded", "paused", "abandoned"],
    "paused":      ["in_progress", "abandoned"],
    "concluded":   [],          # Terminal — co the ghi findings
    "abandoned":   [],
}
```

### 3.3. Question

```
    ┌───────┐     ┌──────────┐
    │ asked │────►│ answered │
    └───┬───┘     └──────────┘
        │
        └────────►┌──────────┐
                  │deferred  │  (hoi lai sau)
                  └──────────┘
```

**Trang thai:** `asked`, `answered`, `deferred`

```python
QUESTION_TRANSITIONS = {
    "asked":    ["answered", "deferred"],
    "deferred": ["asked", "answered"],
    "answered": [],             # Terminal
}
```

### 3.4. Discussion

```
    ┌────────┐     ┌──────────┐     ┌──────────┐
    │ opened │────►│  active  │────►│ resolved │
    └────────┘     └─────┬─────┘    └──────────┘
                         │
                    ┌────▼───┐
                    │ tabled │  (de lai, xem xet sau)
                    └────────┘
```

**Trang thai:** `opened`, `active`, `resolved`, `tabled`

```python
DISCUSSION_TRANSITIONS = {
    "opened":   ["active", "tabled"],
    "active":   ["resolved", "tabled"],
    "tabled":   ["active"],
    "resolved": [],
}
```

### 3.5. Maintenance

```
    ┌──────────┐     ┌───────────┐     ┌──────────┐
    │ planned  │────►│in_progress│────►│ completed│
    └──────────┘     └─────┬─────┘     └──────────┘
                           │
                      ┌────▼─────┐
                      │ deferred │  (delay, chua can gap)
                      └──────────┘
```

**Trang thai:** `planned`, `in_progress`, `completed`, `deferred`, `abandoned`

```python
MAINTENANCE_TRANSITIONS = {
    "planned":     ["in_progress", "deferred", "abandoned"],
    "in_progress": ["completed", "deferred", "abandoned"],
    "deferred":    ["planned", "in_progress", "abandoned"],
    "completed":   [],
    "abandoned":   [],
}
```

---

## 4. Quan ly vong doi (Lifecycle Management)

### 4.1. Khi nao item duoc tao?

Item duoc tao **tu dong boi SessionStart hook** hoac **thu cong boi agent/command**.

**Tu dong (hook):** Hook `inject_project_context.py` se duoc mo rong de:
1. Nhan request cua user (thong qua hook input)
2. Goi `tracker.classify_request(request_text)` — dung heuristic don gian
3. Tao item moi trong DB voi trang thai ban dau

**Luu y quan trong:** Claude Code SessionStart hook chi chay 1 lan dau session, khong chay cho moi request. Vi vay, viec phan loai tu dong moi request can dung **PostToolUse hook** hoac **mot cach tiep can khac**. Xem phan Integration Points (muc 6).

**Phuong an thuc te:**
- Phan loai **khong tu dong hoan toan** cho moi message
- Thay vao do, agent duoc huong dan trong prompt de goi `tracker.py` CLI khi bat dau va ket thuc mot tuong tac co y nghia
- `/coregy-workflow:start-feature` tu dong tao item type=task
- Agent prompts duoc bo sung section huong dan goi tracker

### 4.2. Ai trigger chuyen trang thai?

| Trigger | Mo ta | Vi du |
|---------|-------|-------|
| Agent (tu dong) | Agent goi tracker API khi bat dau/ket thuc cong viec | Backend agent bat dau, tao item task, chuyen sang in_progress |
| Command | Cac command goi tracker | `/coregy-workflow:start-feature` tao task, `/coregy-workflow:resume` chuyen task sang in_progress |
| Hook | SessionStart hook kiem tra va cap nhat | Phat hien item bi bo qua lau, chuyen sang canh bao |
| User (thu cong) | User yeu cau chuyen trang thai | "Danh dau task nay la completed" |

### 4.3. Flow tao item chi tiet

```
User noi: "Them chuc nang OAuth2 login"
    │
    ▼
Agent (hoac start-feature command) nhan dien: day la TASK
    │
    ▼
Goi tracker.create_item(
    type="task",
    title="Them chuc nang OAuth2 login",
    priority="medium",
    tags=["auth", "oauth2", "login"],
    extra={"feature_type": "new-feature", "estimated_complexity": "large"}
)
    │
    ▼
tracker.py:
  1. Tao ID: itm_a1b2c3d4e5f6
  2. Tao session neu chua co
  3. INSERT vao bang items
  4. INSERT tags vao item_tags
  5. INSERT status_log (null -> created)
  6. Return item dict
    │
    ▼
Neu la task: start-feature tao state.json workflow binh thuong
  + Luu workflow_id vao item.workflow_id
```

### 4.4. Auto-detection heuristics (cho agent prompts)

```python
# Cac tin hieu de phan loai — agent dung logic nay
# KHONG chay tu dong — agent quyet dinh

CLASSIFICATION_SIGNALS = {
    "task": [
        "them", "tao", "build", "implement", "fix", "sua",
        "deploy", "refactor", "cap nhat", "update", "add",
        "create", "migrate", "xoa", "delete", "remove"
    ],
    "investigation": [
        "giai thich", "explain", "phan tich", "analyze",
        "tai sao", "why", "lam sao", "how does",
        "dang ki", "trace", "debug", "tim hieu"
    ],
    "question": [
        "la gi", "what is", "co khong", "does it",
        "bao nhieu", "how many", "khi nao", "when",
        "o dau", "where", "ai", "who"
    ],
    "discussion": [
        "nen dung", "should we", "so sanh", "compare",
        "trade-off", "lua chon", "option", "hay la"
    ],
    "maintenance": [
        "update dep", "upgrade", "clean up", "deprecate",
        "migration", "version", "dependency"
    ],
}
```

---

## 5. Awareness Layer

### 5.1. Thong tin inject vao SessionStart

Khi session bat dau, hook doc tu `tracker.db` va inject context:

```
[Coregy Tracker] Active items:
  - [HIGH] Task: "OAuth2 login" (in_progress, 3 ngay) — workflow: feat-oauth2-login-20260318
  - [MED] Task: "Fix payment timeout" (paused, 5 ngay)
  - [MED] Investigation: "Auth module performance" (paused, 2 tuan)

Warnings:
  ⚠ Task "Fix payment timeout" paused 5 ngay — xem xet resume hoac abandon
  ⚠ 1 investigation chua co ket luan sau 2 tuan
  ℹ 3 tasks completed tuan nay
```

### 5.2. Quy tac hien thi — tranh qua tai thong tin

**Nguyen tac chinh:** Chi hien thi nhung gi ACTIONABLE. Khong dump toan bo lich su.

| Hien thi | Dieu kien | Gioi han |
|----------|-----------|---------|
| Active tasks (in_progress) | Luon luon | Toi da 5 |
| Paused/blocked items | Luon luon | Toi da 3 |
| Canh bao stale items | item.updated_at > 3 ngay truoc | Toi da 3 |
| Completed gan day | Trong 24h qua | Toi da 3 |
| Question chua tra loi | status=deferred | Toi da 2 |
| Discussion chua ket luan | status=tabled | Toi da 2 |

**Khong hien thi:**
- Item da completed > 24h truoc (co trong DB, query khi can)
- Item da abandoned (tru khi user hoi)
- Chi tiet metadata (chi hien title + status + thoi gian)

### 5.3. Canh bao (Warnings)

```python
WARNING_RULES = [
    {
        "condition": "task.status == 'in_progress' AND days_since_update > 3",
        "message": "Task '{title}' khong co tien trien trong {days} ngay",
        "severity": "warning",
    },
    {
        "condition": "task.status == 'paused' AND days_since_update > 7",
        "message": "Task '{title}' bi tam dung {days} ngay — nen resume hoac abandon",
        "severity": "warning",
    },
    {
        "condition": "task.status == 'blocked' AND days_since_update > 5",
        "message": "Task '{title}' bi block {days} ngay — kiem tra blocker",
        "severity": "error",
    },
    {
        "condition": "investigation.status == 'in_progress' AND days_since_update > 14",
        "message": "Investigation '{title}' chua ket luan sau 2 tuan",
        "severity": "info",
    },
    {
        "condition": "count(task.status == 'in_progress') > 3",
        "message": "Dang co {count} tasks dong thoi — xem xet hoan thanh truoc khi bat dau moi",
        "severity": "warning",
    },
    {
        "condition": "question.status == 'deferred' AND days_since_update > 7",
        "message": "Cau hoi '{title}' chua duoc tra loi sau 1 tuan",
        "severity": "info",
    },
]
```

### 5.4. Historical queries (khi agent hoac user can)

Agent hoac user co the hoi ve lich su. Tracker cung cap cac query:

```python
# "3 tuan truoc ta da lam gi voi auth module?"
tracker.search(tags=["auth"], after="2026-03-01")

# "Co cong viec nao chua xong khong?"
tracker.get_incomplete()

# "Nhung quyet dinh kien truc gan day?"
tracker.search(type="discussion", status="resolved", limit=10)

# "Lich su cua file nay?"
tracker.search(related_files=["src/auth/handler.py"])
```

---

## 6. Diem tich hop (Integration Points)

### 6.1. Tich hop voi state.json hien tai

**Nguyen tac:** `state.json` van la nguon chinh cho workflow dang chay. `tracker.db` la lop bao quanh cung cap:
- Lich su cac workflow truoc do
- Lien ket giua workflow va cac item khac
- Canh bao va ngu canh

**Cach lam:**

```
state.json (workflow engine)          tracker.db (interaction tracker)
┌─────────────────────────┐          ┌─────────────────────────────┐
│ workflow_id              │◄────────│ items.workflow_id            │
│ feature                  │         │ items.title                  │
│ status                   │────────►│ items.status (dong bo)       │
│ phases, agents           │         │ item_tags, item_files        │
│ agent_log                │         │ status_log (audit trail)     │
└─────────────────────────┘          └─────────────────────────────┘
```

Khi `start-feature`:
1. Tao `state.json` nhu binh thuong (backward compatible)
2. Tao item type=task trong `tracker.db` voi `workflow_id` link sang state.json

Khi workflow status thay doi trong `state.json`:
- `state.py` goi `tracker.sync_workflow_status(cwd)` de dong bo trang thai

Khi `complete_workflow` hoac `abort_workflow`:
- Cap nhat item tuong ung trong tracker.db

**Neu tracker.db khong ton tai:** Moi thu hoat dong nhu cu. Tracker la optional layer.

### 6.2. Tich hop voi Knowledge Base

Khi agent ghi vao KB file:
```python
# Agent ghi xong api-contracts.md
tracker.add_kb_ref(item_id, "api-contracts.md#OAuth2-endpoints")
tracker.add_related_file(item_id, ".coregy/knowledge/api-contracts.md")
```

Khi search KB (`/coregy-workflow:kb-search`):
- Co the search theo item: "file nao da duoc thay doi boi task OAuth2?"
- Cross-reference: "ADR nao lien quan den investigation nay?"

### 6.3. Tich hop voi SessionStart hook

Mo rong `inject_project_context.py`:

```python
# Trong ham main(), sau khi inject profile:

# --- TRACKER INJECTION ---
tracker_db = os.path.join(cwd, ".coregy", "tracker.db")
if os.path.isfile(tracker_db):
    try:
        # Import tracker module
        sys.path.insert(0, scripts_dir)
        import tracker

        # Tao hoac tiep tuc session
        session_id = tracker.ensure_session(cwd)

        # Lay context summary
        context = tracker.get_session_context(cwd)

        if context["active_items"]:
            system_msg += f" | Tracker: {context['summary']}"

        if context["warnings"]:
            system_msg += f" | Warnings: {'; '.join(context['warnings'][:3])}"

    except Exception:
        pass  # Khong block session khi tracker loi
```

### 6.4. Tich hop voi Agent Prompts

Them section vao moi agent prompt:

```markdown
## Interaction Tracking

Khi bat dau cong viec, ghi nhan vao tracker:

1. Doc `.coregy/tracker.db` context (da inject boi SessionStart hook)
2. Xac dinh yeu cau hien tai thuoc loai nao (task, investigation, question, ...)
3. Neu la cong viec moi: goi tracker CLI de tao item
   ```bash
   python3 .coregy/scripts/tracker.py create --type task --title "..." --tags "auth,api"
   ```
4. Khi hoan thanh: cap nhat trang thai
   ```bash
   python3 .coregy/scripts/tracker.py update <item_id> --status completed
   ```
5. Neu co findings/ket luan: ghi vao notes
   ```bash
   python3 .coregy/scripts/tracker.py note <item_id> "Ket luan: dung JWT voi refresh token"
   ```
```

**Luu y:** Agent prompts la static Markdown. Cac lenh tren la HUONG DAN cho agent, khong phai tu dong chay. Agent (Claude) se doc huong dan va tu quyet dinh khi nao goi CLI.

### 6.5. Tich hop voi Commands

| Command hien tai | Thay doi |
|-----------------|----------|
| `/coregy-workflow:start-feature` | Them buoc: tao item type=task trong tracker.db |
| `/coregy-workflow:resume` | Doc tracker.db de hien thi context day du hon |
| `/coregy-workflow:status` | Them section "Active Items" tu tracker.db |
| `/coregy-workflow:init` | Tao tracker.db (init schema) cung voi cac file khac |

**Command moi:**
| Command | Mo ta |
|---------|-------|
| `/coregy-workflow:track` | Tao/cap nhat/search items trong tracker |
| `/coregy-workflow:history` | Xem lich su items, filter theo type/tag/thoi gian |

---

## 7. Chien luoc di chuyen (Migration Strategy)

### 7.1. Nguyen tac

- **Khong pha vo gi:** `state.json` van hoat dong nhu cu
- **Opt-in:** Tracker chi duoc tao khi user chay `/coregy-workflow:init` (tren project da co) hoac khi project moi
- **Backward compatible:** Moi function trong `state.py` van hoat dong khong can tracker.db

### 7.2. Cac buoc migration

**Buoc 1: Init tracker.db**
```python
def init_tracker(cwd):
    """Tao tracker.db voi schema. An toan goi nhieu lan."""
    db_path = os.path.join(cwd, ".coregy", "tracker.db")
    if os.path.isfile(db_path):
        return  # Da ton tai

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.close()
```

**Buoc 2: Import state.json hien tai (neu co)**
```python
def migrate_from_state_json(cwd):
    """Doc state.json hien tai va tao item tuong ung trong tracker.db."""
    state = state_module.load_state(cwd)
    if state is None:
        return

    # Tao item cho workflow hien tai
    item = create_item(
        cwd,
        type="task",
        title=state["feature"],
        status=_map_workflow_status(state["status"]),
        extra={
            "feature_type": state.get("type", ""),
            "agents_involved": _extract_agents(state),
        },
        workflow_id=state["workflow_id"],
    )

    # Import agent_log thanh status transitions
    for log_entry in state.get("agent_log", []):
        if log_entry.get("completed_at"):
            _add_status_log(
                cwd, item["id"],
                from_status="in_progress",
                to_status="in_progress",  # Agent completion, khong doi status item
                changed_at=log_entry["completed_at"],
                reason=f"Agent {log_entry['agent']} completed: {log_entry.get('output_summary', '')}"
            )
```

**Buoc 3: Hook state.py functions**
```python
# Trong state.py, them optional tracker sync sau moi thay doi:

def _sync_to_tracker(cwd, state):
    """Dong bo trang thai workflow vao tracker.db (neu ton tai)."""
    db_path = os.path.join(cwd, ".coregy", "tracker.db")
    if not os.path.isfile(db_path):
        return  # Tracker chua duoc init
    try:
        import tracker
        tracker.sync_workflow_status(cwd, state)
    except Exception:
        pass  # Khong block workflow khi tracker loi
```

### 7.3. Timeline

1. **v0.6.0** — Tao `tracker.py`, schema, API co ban. Init tracker trong `/coregy-workflow:init`. Khong thay doi behavior hien tai.
2. **v0.6.1** — Tich hop voi SessionStart hook (inject context). Them awareness layer.
3. **v0.7.0** — Commands moi (`/track`, `/history`). Agent prompt updates. Day du tich hop.

---

## 8. API Surface

### 8.1. Module: `tracker.py`

File: `plugins/coregy-workflow/skills/project-profile/scripts/tracker.py`

```python
# ===== DATABASE =====

def init_db(cwd: str) -> None:
    """Tao tracker.db voi schema. Idempotent — an toan goi nhieu lan."""

def get_db(cwd: str) -> sqlite3.Connection:
    """Mo ket noi den tracker.db. Raise FileNotFoundError neu chua init."""


# ===== SESSIONS =====

def ensure_session(cwd: str) -> str:
    """Tao session moi hoac tra ve session hien tai (trong ngay).
    Returns session_id (ses_YYYYMMDD_NNN)."""

def end_session(cwd: str, session_id: str, summary: str = "") -> None:
    """Danh dau session ket thuc."""


# ===== ITEMS: CRUD =====

def create_item(
    cwd: str,
    type: str,               # task|investigation|question|discussion|maintenance
    title: str,
    description: str = "",
    priority: str = "medium",
    tags: list[str] = None,
    related_files: list[str] = None,
    workflow_id: str = None,
    extra: dict = None,
) -> dict:
    """Tao item moi. Return item dict voi id da tao."""

def get_item(cwd: str, item_id: str) -> dict | None:
    """Doc item theo ID. Return None neu khong ton tai."""

def update_item(
    cwd: str,
    item_id: str,
    title: str = None,
    description: str = None,
    priority: str = None,
    notes: str = None,
    extra: dict = None,       # Merge voi extra hien tai
) -> dict:
    """Cap nhat metadata cua item. Chi cap nhat field duoc truyen vao."""

def transition_status(
    cwd: str,
    item_id: str,
    new_status: str,
    reason: str = "",
) -> dict:
    """Chuyen trang thai item. Raise ValueError neu transition khong hop le.
    Tu dong ghi status_log."""


# ===== ITEMS: RELATIONS =====

def add_relation(
    cwd: str,
    from_id: str,
    to_id: str,
    relation: str,            # related|blocked_by|led_to|supersedes|parent|child
) -> None:
    """Tao lien ket giua 2 items."""

def add_tags(cwd: str, item_id: str, tags: list[str]) -> None:
    """Them tags cho item."""

def add_related_files(cwd: str, item_id: str, files: list[str]) -> None:
    """Them file lien quan."""

def add_kb_ref(cwd: str, item_id: str, ref: str) -> None:
    """Them tham chieu KB (vd: 'decisions.md#ADR-005')."""


# ===== QUERIES =====

def get_active_items(cwd: str, limit: int = 10) -> list[dict]:
    """Lay cac item dang active (khong phai terminal state).
    Sap xep theo priority DESC, updated_at DESC."""

def get_incomplete(cwd: str) -> list[dict]:
    """Lay tat ca items chua hoan thanh (non-terminal status)."""

def search(
    cwd: str,
    type: str = None,
    status: str = None,
    tags: list[str] = None,
    related_files: list[str] = None,
    after: str = None,         # ISO date string
    before: str = None,
    query: str = None,         # Full-text search trong title + description
    limit: int = 20,
) -> list[dict]:
    """Tim items theo nhieu tieu chi. Tat ca filter la AND logic."""

def get_item_history(cwd: str, item_id: str) -> list[dict]:
    """Lay toan bo status transitions cua mot item."""


# ===== AWARENESS (dung boi hook) =====

def get_session_context(cwd: str) -> dict:
    """Tra ve context cho SessionStart hook injection.
    Returns:
        {
            "summary": "2 tasks in progress, 1 paused",
            "active_items": [...],    # Toi da 5
            "warnings": [...],        # Toi da 3
            "recent_completed": [...], # Trong 24h, toi da 3
        }
    """

def get_warnings(cwd: str) -> list[dict]:
    """Danh sach canh bao dua tren WARNING_RULES.
    Returns list of {"severity": "warning", "message": "..."}"""


# ===== WORKFLOW SYNC =====

def sync_workflow_status(cwd: str, state: dict = None) -> None:
    """Dong bo trang thai tu state.json vao tracker.db.
    Doc state.json neu state=None."""

def migrate_from_state_json(cwd: str) -> dict | None:
    """Import state.json hien tai vao tracker.db. Return item created hoac None."""


# ===== CLI ENTRY POINT =====

def main():
    """CLI interface cho agent goi truc tiep.

    Usage:
        python3 tracker.py init                          # Init DB
        python3 tracker.py create --type task --title "..." [--tags "a,b"] [--priority high]
        python3 tracker.py update <id> --status completed [--reason "..."]
        python3 tracker.py note <id> "Ghi chu..."
        python3 tracker.py search [--type task] [--tags auth] [--status in_progress]
        python3 tracker.py list [--active] [--all]
        python3 tracker.py history <id>
        python3 tracker.py context                       # Show session context (dung boi hook)
        python3 tracker.py migrate                       # Import state.json
    """
```

### 8.2. Ket qua tra ve (Response format)

Moi function tra ve dict hoac list[dict]. CLI mode in JSON ra stdout.

```python
# Item dict day du:
{
    "id": "itm_a1b2c3d4e5f6",
    "type": "task",
    "title": "Them OAuth2 login",
    "description": "...",
    "status": "in_progress",
    "priority": "high",
    "tags": ["auth", "oauth2"],
    "related_files": ["src/auth/oauth.py"],
    "kb_refs": ["api-contracts.md#OAuth2"],
    "workflow_id": "feat-oauth2-login-20260318",
    "extra": {"feature_type": "new-feature", "estimated_complexity": "large"},
    "created_at": "2026-03-18T10:00:00Z",
    "updated_at": "2026-03-21T14:30:00Z",
    "completed_at": null,
    "session_id": "ses_20260321_001",
    "notes": "",
}
```

---

## 9. Cac truong hop dac biet (Edge Cases)

### 9.1. Nhieu task dong thoi

Nguoi dung co the co 2-3 task dang chay song song (vi du: lam feature A, gap bug B, pause A de fix B).

**Xu ly:**
- Cho phep nhieu item `in_progress` cung luc
- Canh bao khi > 3 items dong thoi (qua nhieu context switching)
- `state.json` van chi track 1 workflow — tracker.db track tat ca

### 9.2. Session gap giua (user dong Claude Code, mo lai)

- SessionStart hook tao session moi
- Doc tracker.db de biet items con dang do
- Inject context vao system message
- Session cu duoc danh dau ended (neu chua)

### 9.3. Tracker.db bi corrupt hoac bi xoa

- Tat ca functions catch exception va fallback
- `state.json` van hoat dong doc lap
- User co the chay `tracker.py init` de tao lai DB (mat lich su)
- Co the them `tracker.py export` de backup ra JSON (recovery)

### 9.4. Item ton tai qua lau

- Sau 30 ngay khong update: tu dong chuyen sang `stale` warning
- Sau 90 ngay: de xuat archive/abandon
- Khong tu dong xoa — user quyet dinh

### 9.5. Trung lap (duplicate items)

- Khi tao item moi, check title tuong tu trong cung type (Levenshtein hoac substring match)
- Neu trung > 80%: hoi user co muon link thay vi tao moi
- CLI: `tracker.py create --title "..." --check-duplicate`

### 9.6. Request khong can track

Nhieu tuong tac la tham (trivial) — khong nen tao item:
- "Da, cam on" — khong track
- "Chay lai test" — khong track (la buoc trong task da co)
- "Hien thi code file X" — co the la phan cua investigation da co

**Quy tac:** Chi tao item moi khi:
1. Yeu cau co MUC DICH RO RANG (build, fix, tim hieu, hoi)
2. Khong phai la buoc tiep theo cua item dang active
3. Agent phan doan day la tuong tac MỚI, khong phai tiep tuc

### 9.7. .gitignore

Them vao template `.gitignore` khi init:
```
# Coregy Workflow (local state)
.coregy/tracker.db
.coregy/tracker.db-wal
.coregy/tracker.db-shm
```

`tracker.db` la local state, khong commit len git. Khac voi `state.json` va knowledge base la shared.

---

## Phu luc A: Vi du session thuc te

```
=== Session bat dau ===

[Hook inject]:
"[Coregy Tracker] Active: 1 task in_progress (OAuth2 login, 3d),
 1 task paused (Payment refactor, 5d).
 Warning: Payment refactor paused 5 ngay."

User: "Toi muon tiep tuc lam OAuth2 login"

Agent:
  1. Doc tracker context — thay OAuth2 task in_progress
  2. Doc state.json — thay workflow dang o BUILD phase, backend agent next
  3. Resume workflow binh thuong
  4. Cap nhat tracker: item.updated_at = now

--- sau khi xong ---

Agent:
  1. Cap nhat state.json: backend agent completed
  2. Cap nhat tracker: add note "Backend API done, 3 endpoints"
  3. Add KB ref: "api-contracts.md#OAuth2-endpoints"

User: "Truoc khi lam frontend, giai thich cho toi cach auth middleware hoat dong"

Agent:
  1. Nhan dien: day la INVESTIGATION (khong phai task tiep tuc)
  2. Tao item moi: type=investigation, title="Auth middleware internals"
  3. Tao relation: related to OAuth2 task
  4. Lam investigation...
  5. Ket thuc: status=concluded, findings="Middleware dung JWT verify..."
  6. Cap nhat: led_to = itm_oauth2_task (lien ket nguoc)
```

---

## Phu luc B: File structure sau khi implement

```
plugins/coregy-workflow/
├── skills/project-profile/scripts/
│   ├── tracker.py             # Module chinh — API + CLI
│   ├── tracker_schema.py      # Schema SQL + migration logic
│   ├── tracker_awareness.py   # Warning rules, context builder
│   └── state.py               # Khong thay doi (+ optional tracker sync)
├── hooks/
│   ├── inject_project_context.py  # Mo rong: inject tracker context
│   └── hooks.json                 # Khong thay doi
├── commands/
│   ├── start-feature.md       # Mo rong: tao tracker item
│   ├── resume.md              # Mo rong: hien thi tracker context
│   ├── status.md              # Mo rong: hien thi active items
│   ├── track.md               # MOI: quan ly tracker items
│   └── history.md             # MOI: xem lich su
└── agents/*.md                # Them section "Interaction Tracking"
```
