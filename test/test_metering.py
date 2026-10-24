"""Tests for per-agent token metering (metering.py) and its SubagentStop hook."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "plugins", "coregy-workflow")
SCRIPTS_DIR = os.path.join(PLUGIN, "skills", "project-profile", "scripts")
METERING_PY = os.path.join(SCRIPTS_DIR, "metering.py")
HOOK = os.path.join(PLUGIN, "hooks", "metering_hook.py")
sys.path.insert(0, SCRIPTS_DIR)

import metering
from state import init_workflow, start_agent, complete_agent, request_fixes

PHASES = {"BUILD": ["backend"], "VERIFY": ["code-reviewer"]}


def usage(inp=0, cw=0, cr=0, out=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr, "output_tokens": out}


def assistant(msg_id, u, ts, model="claude-opus-5", tools=()):
    content = [{"type": "text", "text": "x"}]
    content += [{"type": "tool_use", "id": t, "name": "Bash", "input": {}} for t in tools]
    return {"type": "assistant", "agentId": "a1", "sessionId": "s1", "timestamp": ts,
            "message": {"id": msg_id, "model": model, "usage": u, "content": content}}


def write_transcript(path, entries, meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")
    if meta is not None:
        with open(path[:-len(".jsonl")] + ".meta.json", "w") as f:
            json.dump(meta, f)
    return path


class MeteringCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cwd = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.cwd, ".coregy"))
        self.projects = os.path.join(self.tmp, "claude-projects")
        self.session_dir = os.path.join(
            metering.project_transcript_dir(self.cwd, self.projects), "s1")

    def agent_file(self, agent_id, agent_type="coregy-workflow:backend",
                   start="2026-01-01T10:00:00Z", end="2026-01-01T10:02:00Z",
                   u=None, model="claude-opus-5"):
        path = os.path.join(self.session_dir, "subagents", "agent-%s.jsonl" % agent_id)
        u = u or usage(10, 1000, 5000, 200)
        return write_transcript(path, [
            {"type": "user", "timestamp": start, "agentId": agent_id, "message": {"content": "go"}},
            assistant("m1-" + agent_id, u, end, model=model, tools=("t1",)),
        ], meta={"agentType": agent_type, "description": "do it"})


class TestParseTranscript(MeteringCase):
    def test_streamed_lines_are_counted_once(self):
        path = write_transcript(os.path.join(self.tmp, "t.jsonl"), [
            assistant("m1", usage(2, 100, 0, 4), "2026-01-01T10:00:00Z"),
            assistant("m1", usage(2, 100, 0, 4), "2026-01-01T10:00:01Z", tools=("t1",)),
            assistant("m1", usage(2, 100, 0, 345), "2026-01-01T10:00:02Z", tools=("t1",)),
            assistant("m2", usage(1, 0, 100, 50), "2026-01-01T10:01:00Z", tools=("t2", "t3")),
        ])
        u = metering.parse_transcript(path)
        self.assertEqual((u["input"], u["cache_write"], u["cache_read"], u["output"]),
                         (3, 100, 100, 395))
        self.assertEqual(u["total"], 598)
        self.assertEqual(u["fresh"], 498)
        self.assertEqual(u["turns"], 2)
        self.assertEqual(u["tool_uses"], 3)
        self.assertEqual(u["duration_s"], 60)

    def test_per_model_breakdown(self):
        path = write_transcript(os.path.join(self.tmp, "t.jsonl"), [
            assistant("m1", usage(out=10), "2026-01-01T10:00:00Z", model="claude-opus-5"),
            assistant("m2", usage(out=90), "2026-01-01T10:00:01Z", model="claude-haiku-5"),
            assistant("m3", usage(out=5), "2026-01-01T10:00:02Z", model="<synthetic>"),
        ])
        u = metering.parse_transcript(path)
        self.assertEqual(u["models"], ["claude-haiku-5", "claude-opus-5"])
        self.assertEqual(u["by_model"]["claude-opus-5"]["output"], 10)
        self.assertNotIn("<synthetic>", u["by_model"])

    def test_garbage_lines_are_skipped(self):
        path = write_transcript(os.path.join(self.tmp, "t.jsonl"), [
            "not json", "[1, 2]", "",
            assistant("m1", usage(out=7), "2026-01-01T10:00:00Z"),
            {"type": "assistant", "message": "oops"},
        ])
        self.assertEqual(metering.parse_transcript(path)["output"], 7)

    def test_missing_file(self):
        self.assertIsNone(metering.parse_transcript(os.path.join(self.tmp, "nope.jsonl")))


class TestPaths(MeteringCase):
    def test_project_dir_slug(self):
        self.assertEqual(
            os.path.basename(metering.project_transcript_dir("/Users/a/My_App.v2", "/p")),
            "-Users-a-My-App-v2")

    def test_agent_transcript_from_session_transcript(self):
        self.assertEqual(
            metering.agent_transcript_path("/p/proj/s1.jsonl", "abc"),
            "/p/proj/s1/subagents/agent-abc.jsonl")
        self.assertIsNone(metering.agent_transcript_path(None, "abc"))

    def test_normalize_agent(self):
        self.assertEqual(metering.normalize_agent("coregy-workflow:unit-tester"), "unit-tester")
        self.assertEqual(metering.normalize_agent("Explore"), "Explore")
        self.assertEqual(metering.normalize_agent(""), "unknown")


class TestRecord(MeteringCase):
    def test_record_ad_hoc_run(self):
        run = metering.record(self.cwd, self.agent_file("a1"))
        self.assertEqual(run["agent"], "backend")
        self.assertEqual(run["agent_id"], "a1")
        self.assertEqual(run["description"], "do it")
        self.assertIsNone(run["workflow_id"])
        self.assertEqual(metering.load_runs(self.cwd)["a1"]["fresh"], 1210)

    def test_record_is_idempotent(self):
        path = self.agent_file("a1")
        metering.record(self.cwd, path)
        metering.record(self.cwd, path)
        self.assertEqual(len(metering.load_runs(self.cwd)), 1)

    def test_meter_file_is_gitignored_once(self):
        metering.record(self.cwd, self.agent_file("a1"))
        metering.record(self.cwd, self.agent_file("a2"))
        with open(os.path.join(self.cwd, ".coregy", ".gitignore")) as f:
            self.assertEqual(f.read().split().count("metering.json"), 1)

    def test_no_coregy_dir_records_nothing(self):
        shutil.rmtree(os.path.join(self.cwd, ".coregy"))
        self.assertIsNone(metering.record(self.cwd, self.agent_file("a1")))

    def test_ad_hoc_run_links_the_auto_track_item(self):
        with open(os.path.join(self.cwd, ".coregy", "auto_track.json"), "w") as f:
            json.dump({"item_id": "item-7", "title": "x"}, f)
        self.assertEqual(metering.record(self.cwd, self.agent_file("a1"))["item_id"], "item-7")


class TestAttribution(MeteringCase):
    def now(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def test_open_entry_binds_the_run(self):
        init_workflow(self.cwd, "add login", "new-feature", PHASES, spec_confirmed=True)
        start_agent(self.cwd, "backend")
        run = metering.record(self.cwd, self.agent_file("a1", start=self.now(), end=self.now()))
        self.assertTrue(run["workflow_id"].startswith("feat-add-login"))
        self.assertEqual((run["phase"], run["log_index"], run["fix_round"]), ("BUILD", 0, None))

    def test_fix_round_rerun_is_marked(self):
        init_workflow(self.cwd, "add login", "new-feature", PHASES, spec_confirmed=True)
        for agent in ("backend", "code-reviewer"):
            start_agent(self.cwd, agent)
            complete_agent(self.cwd, agent)
        request_fixes(self.cwd, "code-reviewer", ["null check missing"])
        start_agent(self.cwd, "backend")
        run = metering.record(self.cwd, self.agent_file("a2", start=self.now(), end=self.now()))
        self.assertEqual((run["log_index"], run["fix_round"]), (2, 1))

    def test_agent_not_in_workflow_is_ad_hoc(self):
        init_workflow(self.cwd, "add login", "new-feature", PHASES, spec_confirmed=True)
        run = metering.record(self.cwd, self.agent_file(
            "a1", agent_type="Explore", start=self.now(), end=self.now()))
        self.assertIsNone(run["workflow_id"])

    def test_archived_workflow_is_matched_by_time(self):
        init_workflow(self.cwd, "first", "bug-fix", PHASES, spec_confirmed=True)
        start_agent(self.cwd, "backend")
        started = self.now()
        complete_agent(self.cwd, "backend")
        init_workflow(self.cwd, "second", "bug-fix", PHASES, spec_confirmed=True)
        run = metering.record(self.cwd, self.agent_file("old", start=started, end=started))
        self.assertTrue(run["workflow_id"].startswith("feat-first"), run["workflow_id"])

    def test_resumed_agent_keeps_its_binding(self):
        init_workflow(self.cwd, "add login", "new-feature", PHASES, spec_confirmed=True)
        start_agent(self.cwd, "backend")
        path = self.agent_file("a1", start=self.now(), end=self.now())
        first = metering.record(self.cwd, path)
        complete_agent(self.cwd, "backend")
        init_workflow(self.cwd, "other", "bug-fix", PHASES, spec_confirmed=True)
        again = metering.record(self.cwd, path, agent_id="a1")
        self.assertEqual(again["workflow_id"], first["workflow_id"])


class TestCollect(MeteringCase):
    def test_collect_finds_transcripts_and_skips_unchanged(self):
        self.agent_file("a1")
        self.agent_file("a2", agent_type="coregy-workflow:code-reviewer")
        self.assertEqual(metering.collect(self.cwd, self.projects),
                         {"added": 2, "updated": 0, "runs": 2})
        self.assertEqual(metering.collect(self.cwd, self.projects)["added"], 0)

    def test_collect_needs_init(self):
        shutil.rmtree(os.path.join(self.cwd, ".coregy"))
        with self.assertRaises(FileNotFoundError):
            metering.collect(self.cwd, self.projects)

    def test_collect_ignores_other_projects(self):
        other = os.path.join(metering.project_transcript_dir("/elsewhere", self.projects),
                             "s9", "subagents", "agent-zz.jsonl")
        write_transcript(other, [assistant("m", usage(out=1), "2026-01-01T10:00:00Z")])
        self.assertEqual(metering.collect(self.cwd, self.projects)["runs"], 0)


class TestReport(MeteringCase):
    def runs(self):
        return [
            {"agent": "backend", "phase": "BUILD", "workflow_id": "w1", "input": 10,
             "cache_write": 100, "cache_read": 1000, "output": 50, "total": 1160,
             "fresh": 160, "tool_uses": 3, "duration_s": 60, "fix_round": None,
             "models": ["claude-opus-5"],
             "by_model": {"claude-opus-5": {"input": 10, "cache_write": 100,
                                            "cache_read": 1000, "output": 50}}},
            {"agent": "backend", "phase": "BUILD", "workflow_id": "w1", "input": 5,
             "cache_write": 0, "cache_read": 500, "output": 20, "total": 525,
             "fresh": 25, "tool_uses": 1, "duration_s": 30, "fix_round": 1,
             "models": ["claude-opus-5"],
             "by_model": {"claude-opus-5": {"input": 5, "cache_write": 0,
                                            "cache_read": 500, "output": 20}}},
            {"agent": "code-reviewer", "phase": "VERIFY", "workflow_id": "w1", "input": 1,
             "cache_write": 300, "cache_read": 9000, "output": 100, "total": 9401,
             "fresh": 401, "tool_uses": 9, "duration_s": 90, "fix_round": None,
             "models": ["claude-sonnet-5"],
             "by_model": {"claude-sonnet-5": {"input": 1, "cache_write": 300,
                                              "cache_read": 9000, "output": 100}}},
        ]

    def test_group_by_agent_sorted_by_fresh(self):
        s = metering.summarize(self.runs(), "agent")
        self.assertEqual([r["key"] for r in s["rows"]], ["code-reviewer", "backend"])
        backend = s["rows"][1]
        self.assertEqual((backend["runs"], backend["fresh"], backend["fix_tokens"]), (2, 185, 25))
        self.assertEqual(s["totals"]["total"], 11086)
        self.assertIsNone(s["totals"]["cost"])

    def test_group_by_phase_and_model(self):
        self.assertEqual({r["key"] for r in metering.summarize(self.runs(), "phase")["rows"]},
                         {"BUILD", "VERIFY"})
        self.assertEqual(metering.summarize(self.runs(), "model")["rows"][0]["key"],
                         "claude-sonnet-5")

    def test_bad_grouping(self):
        with self.assertRaises(ValueError):
            metering.summarize([], "color")

    def test_cost_with_prices(self):
        prices = {"claude-opus": {"input": 5, "output": 25, "cache_write": 6.25, "cache_read": 0.5},
                  "claude-sonnet": {"input": 3, "output": 15, "cache_write": 3.75, "cache_read": 0.3}}
        s = metering.summarize(self.runs(), "agent", prices)
        reviewer = s["rows"][0]
        expected = (1 * 3 + 300 * 3.75 + 9000 * 0.3 + 100 * 15) / 1e6
        self.assertAlmostEqual(reviewer["cost"], round(expected, 4))
        self.assertIsNotNone(s["totals"]["cost"])

    def test_unpriced_model_leaves_cost_unknown(self):
        s = metering.summarize(self.runs(), "agent", {"claude-opus": {
            "input": 5, "output": 25, "cache_write": 6.25, "cache_read": 0.5}})
        self.assertIsNone(s["rows"][0]["cost"])
        self.assertIsNotNone(s["rows"][1]["cost"])
        self.assertIsNone(s["totals"]["cost"])

    def test_load_prices_defaults_cache_ratios(self):
        with open(os.path.join(self.cwd, ".coregy", "metering.yaml"), "w") as f:
            f.write("prices:\n  claude-opus:\n    input: 5\n    output: 25\n"
                    "  claude-opus-5-5:\n    input: 4\n    output: 20\n    cache_read: 0.2\n")
        prices = metering.load_prices(self.cwd)
        self.assertEqual(prices["claude-opus"]["cache_write"], 6.25)
        self.assertEqual(prices["claude-opus"]["cache_read"], 0.5)
        self.assertEqual(metering._price_for(prices, "claude-opus-5-5")["input"], 4)
        self.assertEqual(metering._price_for(prices, "claude-opus-5")["input"], 5)
        self.assertIsNone(metering._price_for(prices, "claude-haiku-5"))

    def test_no_price_file(self):
        self.assertEqual(metering.load_prices(self.cwd), {})

    def test_format_report(self):
        text = metering.format_report(metering.summarize(self.runs()), "T")
        self.assertIn("code-reviewer", text)
        self.assertIn("Fix rounds: 25 fresh tokens", text)
        self.assertNotIn("cost", text)
        self.assertEqual(metering.format_report(metering.summarize([])),
                         "No agent runs recorded.")

    def test_human(self):
        self.assertEqual([metering.human(n) for n in (0, 999, 1500, 25_000, 2_500_000)],
                         ["0", "999", "1.5k", "25k", "2.5M"])

    def test_select_current_workflow(self):
        init_workflow(self.cwd, "add login", "new-feature", PHASES, spec_confirmed=True)
        start_agent(self.cwd, "backend")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        metering.record(self.cwd, self.agent_file("in", start=now, end=now))
        metering.record(self.cwd, self.agent_file("out", agent_type="Explore"))
        current, wid = metering.select_runs(self.cwd)
        self.assertEqual([r["agent_id"] for r in current], ["in"])
        self.assertEqual(len(metering.select_runs(self.cwd, "all")[0]), 2)
        self.assertIn("backend", metering.brief(self.cwd))


class TestCli(MeteringCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, METERING_PY] + list(args) + ["--cwd", self.cwd],
                              capture_output=True, text=True)

    def test_record_and_report_json(self):
        result = self.cli("record", "--transcript", self.agent_file("a1"), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["agent"], "backend")
        data = json.loads(self.cli("report", "--workflow", "all", "--json").stdout)
        self.assertEqual(data["rows"][0]["key"], "backend")
        self.assertEqual(data["totals"]["fresh"], 1210)

    def test_collect_with_projects_dir(self):
        self.agent_file("a1")
        result = self.cli("collect", "--projects-dir", self.projects)
        self.assertIn("1 new", result.stdout)

    def test_report_brief_without_runs(self):
        self.assertIn("no agent runs", self.cli("report", "--brief").stdout)

    def test_record_missing_transcript_fails(self):
        result = self.cli("record", "--transcript", os.path.join(self.tmp, "x.jsonl"))
        self.assertEqual(result.returncode, 1)

    def test_clear_needs_force(self):
        metering.record(self.cwd, self.agent_file("a1"))
        self.assertEqual(self.cli("clear").returncode, 1)
        self.assertEqual(self.cli("clear", "--force").returncode, 0)
        self.assertEqual(metering.load_runs(self.cwd), {})


class TestHook(MeteringCase):
    def run_hook(self, payload, **env):
        return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=10,
                              env=dict(os.environ, **env))

    def test_hook_records_from_agent_transcript_path(self):
        path = self.agent_file("a1")
        result = self.run_hook({"cwd": self.cwd, "agent_id": "a1",
                                "agent_type": "coregy-workflow:backend",
                                "agent_transcript_path": path})
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("a1", metering.load_runs(self.cwd))

    def test_hook_derives_path_from_session_transcript(self):
        self.agent_file("a1")
        session = os.path.join(os.path.dirname(self.session_dir), "s1.jsonl")
        self.run_hook({"cwd": self.cwd, "agent_id": "a1", "session_id": "s1",
                       "transcript_path": session})
        self.assertIn("a1", metering.load_runs(self.cwd))

    def test_hook_disabled(self):
        path = self.agent_file("a1")
        self.run_hook({"cwd": self.cwd, "agent_id": "a1", "agent_transcript_path": path},
                      COREGY_METERING="0")
        self.assertEqual(metering.load_runs(self.cwd), {})

    def test_hook_survives_bad_input(self):
        result = subprocess.run([sys.executable, HOOK], input="garbage",
                                capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_hook_is_registered(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        commands = [h["command"] for entry in hooks["SubagentStop"] for h in entry["hooks"]]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/metering_hook.py", commands)
        self.assertTrue(os.access(HOOK, os.X_OK))


if __name__ == "__main__":
    unittest.main()
