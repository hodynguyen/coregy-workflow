---
tags: [spec, refactor, runtime, cli, wiring, tech-debt]
date: 2026-07-26
author-agent: start-feature
status: confirmed
---

# Spec: Sửa lỗi wiring runtime & nối lại các script chết

Type: refactor
Priority: high
Execution mode: guided

## Summary

Sửa 2 bug làm hỏng runtime của plugin, thêm CLI cho 7 script đang chết và nối chúng
vào command thật, rồi dọn doc drift + rác. Mục tiêu: mọi thứ đã viết và đã test phải
thực sự chạy khi user gõ lệnh.

## Bối cảnh (từ review v0.12.0)

Bằng chứng các script chết thật sự không chạy:
- `.coregy/tracker.db` không tồn tại dù `state.json` ghi 3 agent đã chạy xong
- `.coregy/knowledge/_index.json` không tồn tại dù `/init` mô tả phải tạo
- `.coregy/state.json` thiếu `execution_mode`, `spec_file`, `log_file`, `spec_confirmed`
  (Claude viết tay theo template v0.6 cũ, bỏ qua schema v0.10 mà `state.py` định nghĩa)

Nguyên nhân gốc: command mô tả công việc bằng văn xuôi để LLM làm tay, thay vì gọi
script đã viết sẵn. Cộng thêm bug `${PLUGIN_ROOT}` khiến kể cả command có gọi script
thì lệnh cũng fail.

## Requirements

### P0 — Bug runtime

| # | Việc | Chi tiết |
|---|------|---------|
| R1 | `${PLUGIN_ROOT}` → `${CLAUDE_PLUGIN_ROOT}` | 40 dòng, 10 commands + 9 agents. Biến cũ không tồn tại trong Claude Code → mọi lệnh bash trong command/agent expand thành path rỗng và fail. `hooks/hooks.json` đã dùng đúng tên. |
| R2 | Regex quality gate | `hooks/quality_gate.py:265` — `^\s*git\s+commit\b` bỏ sót `git add && git commit`, `VAR=x git commit`, `git -C path commit`. Chưa từng chặn commit nào của chính repo này. |

### P1 — Nối lại script chết

Thêm `__main__` + argparse cho từng script, đổi prose trong command thành lệnh bash thật.

| # | Script | Dòng | CLI subcommands | Nối vào |
|---|--------|------|-----------------|---------|
| R3 | `state.py` | 506 | `init-workflow`, `start-agent`, `complete-agent`, `skip-agent`, `confirm-spec`, `set-mode`, `next-agent`, `complete`, `abort`, `log-append`, `show` | `/start-feature` bước 10-12, `/resume` bước 5, 9 agent |
| R4 | `health.py` | 570 | `report` (+`--section`, `--json`) | `/health` — thay toàn bộ prose |
| R5 | `kb_index.py` | 266 | `build`, `search` | `/init` bước 4, `/update-kb`, `/kb-search` |
| R6 | `kb_archive.py` | 187 | `check`, `run` | `/init` bước 5, `/update-kb` |
| R7 | `contracts.py` | 202 | `validate --from --to`, `list` | 6 agent — thay "contract check" bằng văn xuôi |
| R8 | `ci_monitor.py` | 422 | `status`, `summary`, `feedback` | `/ci-report` |
| R9 | `team.py` | 374 | `init`, `show`, `check-agent`, `check-workflow` | Command mới `/coregy-workflow:team` (14 → 15 commands) |

### P2 — Dọn dẹp

| # | Việc |
|---|------|
| R10 | Doc drift: `README.md` 309/25 → 615+/32+; `ARCHITECTURE.md` + `PROPOSAL.md` 539/30 → 615+/32+ |
| R11 | Xóa `plugins/.../scripts/graphify-out/` (324KB rác do chạy graphify sai cwd); thêm guard `.gitignore`; thêm `.coregy/tracker.db` vào `.gitignore` theo ADR-005 |
| R12 | Nối 3 output-style mồ côi: `review-report` → code-reviewer, `test-report` → unit-tester + integration-tester, `design-doc` → architect |
| R13 | Ghi vào `tech-debt.md`: agent prompt lặp ~35 dòng × 9 file (chốt để sau) |
| R14 | Bump `0.12.0` → `0.13.0`, cập nhật `CLAUDE.md` |

## Technical Design

- **Pattern CLI**: theo đúng `rules.py` / `tracker.py` hiện có — `argparse` + `--cwd`
  mặc định `.`, in text cho người đọc, `--json` khi cần máy đọc. Không thêm dependency
  ngoài stdlib + PyYAML.
- **Backward compat**: `state.py` phải đọc được `state.json` schema cũ (thiếu
  `execution_mode` / `spec_file` / `log_file` / `spec_confirmed`).
  `get_execution_mode()` đã default `guided`; cần đối xử tương tự cho các field còn lại.
- **Không đổi hành vi thiết kế**: spec-driven flow, 3 execution mode, phân chia 4 phase
  giữ nguyên. Chỉ đổi *ai* thực thi — script thay vì LLM làm tay.
- **Test**: mỗi CLI mới cần test ở mức subprocess (gọi thật qua `sys.executable`), không
  chỉ test hàm. Đây chính là lỗ hổng đã để lọt R1 và R2.

## Out of Scope

- Gom trùng lặp trong 9 agent prompt (chốt để sau → ghi `tech-debt.md`)
- Xóa `.venv-graphify-spike/` — venv local của user, không đụng
- Integration test cho full init flow (nợ cũ đã có trong `tech-debt.md`)
- Thay đổi logic `detect_stack.py` / `detectors/`

## Agent Workflow

```
THINK:  architect        — thiết kế CLI surface 7 script + bản đồ command→script
BUILD:  backend          — implement CLI, wire command/agent, fix R1/R2, dọn P2
VERIFY: unit-tester      — test subprocess-level cho CLI mới + regex quality gate
        code-reviewer    — soát chất lượng
        spec-verifier    — đối chiếu R1–R14 đã làm đủ chưa
```

Ước tính: 5 agents / 3 phases. Không có SHIP (`ci: none`).

## Acceptance Criteria

1. `grep -rn '\${PLUGIN_ROOT}' plugins/` trả về 0 kết quả
2. Mỗi script R3–R9 chạy được `python3 <script>.py --help` và trả exit 0
3. Mỗi command trong bảng R3–R9 chứa lệnh bash gọi script tương ứng
4. Quality gate chặn được `git add -A && git commit -m x` khi có secret staged
5. Toàn bộ test suite pass, số test tăng so với 615
6. `README.md` / `ARCHITECTURE.md` / `PROPOSAL.md` khớp số test thực tế
