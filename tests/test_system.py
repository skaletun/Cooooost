"""End-to-end and failure-mode checks without external API access."""
import io
import json
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from cooooost import core
from cooooost.cache import Cache, eligible, request_key, extract_usage
from cooooost.context import ingest, retrieve
from cooooost.integrations import install_skill, install_claude_hooks, process_hook
from cooooost.proxy import make_handler
from cooooost.watch import cycle, daemon, register


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)


class StateTests(Base):
    def test_state_roundtrip_and_recovery(self):
        core.init(self.project)
        core.update(self.project, goal="Ship fully", append={"constraints": "Never omit tests"})
        p = core.checkpoint(self.project)
        core.update(self.project, goal="Wrong")
        self.assertEqual(core.recover(self.project)["goal"], "Ship fully")
        self.assertTrue(core.verified_checkpoints(self.project))

    def test_corrupt_checkpoint_detected(self):
        p = core.checkpoint(self.project)
        data = json.loads(p.read_text())
        data["state"]["goal"] = "tampered"
        p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            core.verified_checkpoints(self.project)

    def test_init_does_not_overwrite(self):
        core.update(self.project, goal="Original")
        core.init(self.project)
        self.assertEqual(core.read_state(self.project)["goal"], "Original")

    def test_unique_checkpoints(self):
        a = core.checkpoint(self.project)
        b = core.checkpoint(self.project)
        self.assertNotEqual(a, b)

    def test_summary_does_not_silently_drop_constraints(self):
        core.update(self.project, goal="X" * 1000)
        self.assertIn("Read full ledger", core.summary(self.project, 100))

    def test_path_conflict_recovery_refuses_missing(self):
        with self.assertRaises(FileNotFoundError):
            core.recover(self.project)


class ArchiveTests(Base):
    def test_binary_roundtrip_with_dedup_and_no_deletion(self):
        src = self.project / "input.bin"
        data = bytes(range(256)) * 400
        src.write_bytes(data)
        a = core.archive(self.project, src)
        b = core.archive(self.project, src)
        self.assertEqual(a["stored"], b["stored"])
        self.assertEqual(src.read_bytes(), data)
        dest = self.project / "restored.bin"
        core.restore(self.project, a["sha256"], dest)
        self.assertEqual(data, dest.read_bytes())
        with self.assertRaises(FileExistsError):
            core.restore(self.project, a["sha256"], dest)

    def test_corrupted_archive_never_restored(self):
        src = self.project / "a.txt"
        src.write_text("hello")
        a = core.archive(self.project, src)
        Path(a["stored"]).write_bytes(gzip.compress(b"not hello"))
        with self.assertRaises(ValueError):
            core.restore(self.project, a["sha256"], self.project / "out")

    def test_invalid_hash_cannot_traverse(self):
        with self.assertRaises(ValueError):
            core.restore(self.project, "../etc/passwd", self.project / "out")


class ContextTests(Base):
    def test_unicode_retrieval_has_integrity_and_offsets(self):
        src = self.project / "spec.txt"
        src.write_text("Фаана заклинания acceptance required. " * 100, encoding="utf-8")
        ingest(self.project, src, 256)
        got = retrieve(self.project, "Фаана", 1024)
        self.assertGreater(len(got["chunks"]), 0)
        self.assertTrue(all("source_sha256" in x for x in got["chunks"]))
        self.assertFalse(got["complete"])

    def test_bad_utf8_rejected_without_source_change(self):
        src = self.project / "bad.txt"
        src.write_bytes(b"\xff")
        with self.assertRaises(ValueError):
            ingest(self.project, src)
        self.assertEqual(src.read_bytes(), b"\xff")

    def test_no_matches_is_explicit(self):
        src = self.project / "ok.txt"
        src.write_text("orchids")
        ingest(self.project, src)
        got = retrieve(self.project, "batteries")
        self.assertEqual(got["chunks"], [])


class CacheTests(Base):
    def cache(self):
        return Cache(self.project / ".cooooost" / "db.sqlite3")

    def test_identical_payload_and_identity_only(self):
        key = request_key("openai", "/v1/responses", {"model": "a", "input": "x"}, "acct1", "p")
        self.assertEqual(key, request_key("openai", "/v1/responses", {"input": "x", "model": "a"}, "acct1", "p"))
        self.assertNotEqual(key, request_key("openai", "/v1/responses", {"model": "a", "input": "x"}, "acct2", "p"))
        self.assertNotEqual(key, request_key("openai", "/v1/responses", {"model": "a", "input": "y"}, "acct1", "p"))

    def test_refuse_unsafe_payload(self):
        cases = [
            {"model": "m", "stream": True, "temperature": 0},
            {"model": "m", "tools": [{"name": "write"}], "temperature": 0},
            {"model": "m", "temperature": 1},
            {"model": "m", "web_search_options": {}, "temperature": 0},
            {"model": "m"},
        ]
        for case in cases:
            with self.subTest(case=case):
                # Non-empty web_search_options to match actual external access.
                if "web_search_options" in case:
                    case["web_search_options"] = {"active": True}
                self.assertFalse(eligible(case)[0])
        self.assertTrue(eligible({"model": "m", "temperature": 0})[0])

    def test_corruption_ttl_and_metrics(self):
        c = self.cache()
        c.put("key", {"response": "a"}, {"input": 120, "output": 60})
        self.assertEqual(c.get("key")[0]["response"], "a")
        c.record("openai", "hit", avoided={"input": 120, "output": 60})
        self.assertEqual(c.stats()["avoided_output_tokens_estimate"], 60)
        with c._connect() as db:
            db.execute("UPDATE responses SET data=? WHERE key=?", ('{"response":"evil"}', "key"))
        self.assertIsNone(c.get("key"))
        c.put("key", {"response": "a"}, {"input": 1, "output": 1})
        with c._connect() as db:
            db.execute("UPDATE responses SET created=0 WHERE key='key'")
        self.assertIsNone(c.get("key"))

    def test_openai_anthropic_usage(self):
        self.assertEqual(extract_usage("openai", {"usage": {"prompt_tokens": 11, "completion_tokens": 6, "prompt_tokens_details": {"cached_tokens": 8}}})["provider_cache_read"], 8)
        self.assertEqual(extract_usage("anthropic", {"usage": {"input_tokens": 20, "output_tokens": 7, "cache_read_input_tokens": 12}})["provider_cache_read"], 12)


class InstallTests(Base):
    def test_skill_install_each_agent(self):
        for agent in ("claude", "codex", "gemini", "cursor", "opencode"):
            self.assertIn("name: cooooost", (install_skill(agent, self.project) / "SKILL.md").read_text())

    def test_hook_config_non_destructive_and_idempotent(self):
        p = self.project / ".claude/settings.json"
        p.parent.mkdir()
        p.write_text(json.dumps({"permissions": {"allow": ["Bash(git status)"]}}))
        install_claude_hooks(self.project)
        install_claude_hooks(self.project)
        doc = json.loads(p.read_text())
        self.assertEqual(doc["permissions"]["allow"], ["Bash(git status)"])
        self.assertEqual(len(doc["hooks"]["PreCompact"]), 1)
        self.assertTrue((p.parent / "settings.cooooost-backup.json").exists())

    def test_hook_resume_and_precompact_archive(self):
        src = self.project / "history.jsonl"
        src.write_text('{"type":"user"}\n')
        event = json.dumps({"cwd": str(self.project), "transcript_path": str(src)})
        context = process_hook("SessionStart", event)
        self.assertIn("additionalContext", context["hookSpecificOutput"])
        self.assertIsNone(process_hook("PreCompact", event))
        self.assertEqual(len(core.verified_checkpoints(self.project)), 1)
        self.assertEqual(cycle(self.project)["archived"], 1)
        self.assertIsNone(process_hook("PostCompact", json.dumps({"cwd": str(self.project), "compact_summary": "Original native summary"})))
        self.assertTrue(list((core.root_of(self.project) / "native-compactions").glob("*.txt")))

    def test_bad_hook_input_is_fail_open(self):
        self.assertIsNone(process_hook("PreCompact", "invalid"))


class DaemonTests(Base):
    def test_one_cycle_without_real_sleep(self):
        reports = daemon(self.project, minimum=7, maximum=13, iterations=1, sleep=lambda sec: self.assertTrue(420 <= sec <= 780))
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(core.verified_checkpoints(self.project)), 1)


class Upstream(BaseHTTPRequestHandler):
    calls = 0
    body = None
    def log_message(self, *args):
        return
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        value = json.loads(self.rfile.read(length))
        type(self).calls += 1
        type(self).body = value
        if value.get("stream"):
            raw = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
            kind = "text/event-stream"
        else:
            raw = json.dumps({"id": "returned", "choices": [{"message": {"content": "hello"}}],
                              "usage": {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 40}}}).encode()
            kind = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ProxyTests(Base):
    def setUp(self):
        super().setUp()
        Upstream.calls = 0
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.addCleanup(self.upstream.server_close)
        thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.upstream.shutdown)
        self.db = Cache(self.project / "cache.db")
        address = "http://127.0.0.1:" + str(self.upstream.server_port)
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.db, {"openai": address, "anthropic": address}))
        self.addCleanup(self.proxy.server_close)
        thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.proxy.shutdown)

    def request(self, payload, cache="replay", auth="Bearer one"):
        req = urllib.request.Request("http://127.0.0.1:" + str(self.proxy.server_port) + "/v1/chat/completions",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": auth, "Content-Type": "application/json", "X-Cooooost-Cache": cache})
        with urllib.request.urlopen(req) as response:
            return response.read(), response.headers.get("X-Cooooost-Cache")

    def test_exact_replay_and_metrics_and_auth_isolation(self):
        payload = {"model": "model", "temperature": 0, "messages": [{"role": "user", "content": "A"}]}
        a, flag1 = self.request(payload)
        b, flag2 = self.request(payload)
        self.assertEqual(json.loads(a), json.loads(b))
        self.assertEqual((flag1, flag2), ("MISS", "HIT"))
        self.assertEqual(Upstream.calls, 1)
        self.request(payload, auth="Bearer two")
        self.assertEqual(Upstream.calls, 2)
        self.assertEqual(self.db.stats()["avoided_input_tokens_estimate"], 100)
        self.assertEqual(self.db.stats()["provider_cached_input_tokens"], 80)

    def test_tool_calls_never_cached(self):
        payload = {"model": "model", "temperature": 0, "tools": [{"type": "function", "function": {"name": "search"}}]}
        _, a = self.request(payload)
        _, b = self.request(payload)
        self.assertEqual((a, b), ("BYPASS", "BYPASS"))
        self.assertEqual(Upstream.calls, 2)

    def test_streaming_passthrough_preserves_wire_bytes(self):
        payload = {"model": "model", "stream": True}
        raw, status = self.request(payload)
        self.assertIn(b"data: [DONE]", raw)
        self.assertEqual(status, "BYPASS")

    def test_no_cache_unless_opted_in(self):
        payload = {"model": "model", "temperature": 0}
        self.request(payload, cache="off")
        self.request(payload, cache="off")
        self.assertEqual(Upstream.calls, 2)


class CLITests(Base):
    def test_real_command_line(self):
        cmd = [sys.executable, "-m", "cooooost", "init", "--project", str(self.project)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.project / ".cooooost/state.json").exists())


if __name__ == "__main__":
    unittest.main()

class CompatibilityTests(Base):
    def test_schema1_automatic_non_destructive_migration(self):
        old = {"schema": 1, "goal": "Legacy task", "updated_at": "2020-01-01",
               "special_project_fact": "keep", **{k: [] for k in core.FIELDS}}
        state = core.root_of(self.project) / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps(old))
        new = core.read_state(self.project)
        self.assertEqual(new["schema"], 2)
        self.assertEqual(new["goal"], "Legacy task")
        self.assertEqual(new["legacy_extra"], {"special_project_fact": "keep"})
        backups = list(state.parent.glob("state.schema1.*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), old)

    def test_wrong_schema_fails_closed(self):
        state = core.root_of(self.project) / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"schema": 999}')
        with self.assertRaises(ValueError):
            core.read_state(self.project)

    def test_concurrent_cache_writes(self):
        cache = Cache(self.project / "c.sqlite3")
        def writer(n):
            for i in range(15):
                cache.put(f"{n}-{i}", {"number": i}, {"input": 5, "output": 8})
                cache.record("openai", "passthrough", {"input": 5})
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(cache.stats()["entries"], 60)
        self.assertEqual(cache.stats()["requests"]["passthrough"], 60)

    def test_cli_doctor_after_upgrade(self):
        cmd = [sys.executable, "-m", "cooooost", "doctor", "--project", str(self.project)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["state_valid"])