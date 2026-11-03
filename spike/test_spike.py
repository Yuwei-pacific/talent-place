#!/usr/bin/env python3
"""python3 spike/test_spike.py

Offline tests for the Windows probe. Throwaway, like everything under spike/: this
kit gets one chance on a colleague's computer, so what would waste that chance is
pinned here and nothing more.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "windows-probe" / "skills" / "probe" / "scripts" / "probe.py"


def run_probe(*args, env=None, script=PROBE):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=full_env,
        timeout=120,
    )


def report(master):
    path = Path(master) / "probe-report.jsonl"
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {r["test"]: r for r in rows}


class ProbeCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="probe-"))
        self.master = self.root / "TEST probe - spaced"
        self.master.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "A1-regole-ricerca.md").write_text("A1", encoding="utf-8")
        (self.config / "A4-regole-registrazione.md").write_text("A4", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make_review(self):
        from openpyxl import Workbook

        wb = Workbook()
        wb.active["A1"] = "Company"
        path = self.master / "Review.xlsx"
        wb.save(path)
        return path


class TestRefusals(ProbeCase):
    def test_refuses_non_test_folder(self):
        real = self.root / "Strategic design ED.28"
        real.mkdir()
        res = run_probe("env", "--master", real)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(list(real.iterdir()), [])

    def test_test_in_a_parent_is_not_enough(self):
        real = self.master / "Strategic design ED.28"
        real.mkdir()
        self.assertEqual(run_probe("env", "--master", real).returncode, 2)

    def test_refuses_missing_folder(self):
        missing = self.root / "TEST-missing"
        self.assertEqual(run_probe("env", "--master", missing).returncode, 2)
        self.assertFalse(missing.exists())


class TestEnv(ProbeCase):
    def test_output_survives_legacy_console(self):
        master = self.root / "TEST perché — probe"
        master.mkdir()
        res = run_probe("env", "--master", master, env={"PYTHONIOENCODING": "cp437"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("UnicodeEncodeError", res.stderr)
        self.assertIn("T2", report(master))

    def test_env_records_t2(self):
        res = run_probe("env", "--master", self.master)
        self.assertEqual(res.returncode, 0, res.stderr)
        detail = report(self.master)["T2"]["detail"]
        for key in ("platform", "python_version", "node_version", "openpyxl_source", "skill_dir_writable"):
            self.assertIn(key, detail)
        self.assertEqual(report(self.master)["T2"]["status"], "PASS", detail)
        self.assertIn("T2 PASS", res.stdout)

    def test_env_missing_node_is_fail_not_crash(self):
        empty = self.root / "empty-path"
        empty.mkdir()
        res = run_probe("env", "--master", self.master, env={"PATH": str(empty)})
        self.assertEqual(res.returncode, 0, res.stderr)
        row = report(self.master)["T2"]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("node", row["detail"]["missing"])


class TestFs(ProbeCase):
    def test_fs_passes_on_good_folders(self):
        self.make_review()
        res = run_probe("fs", "--master", self.master, "--config", self.config)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = report(self.master)
        self.assertEqual(rows["T4"]["status"], "PASS", rows["T4"])
        self.assertEqual(rows["T5-write"]["status"], "PASS", rows["T5-write"])
        from openpyxl import load_workbook

        load_workbook(self.master / "probe-roundtrip.xlsx")
        self.assertTrue(list(self.master.glob("probe-marker-*.txt")))

    def test_fs_missing_review_is_reported(self):
        res = run_probe("fs", "--master", self.master, "--config", self.config)
        self.assertEqual(res.returncode, 0, res.stderr)
        row = report(self.master)["T5-write"]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("Review.xlsx", json.dumps(row["detail"]))

    def test_fs_missing_config_is_t4_fail(self):
        self.make_review()
        (self.config / "A1-regole-ricerca.md").unlink()
        run_probe("fs", "--master", self.master, "--config", self.config)
        self.assertEqual(report(self.master)["T4"]["status"], "FAIL")

    def test_fs_never_touches_review(self):
        review = self.make_review()
        before = (review.read_bytes(), review.stat().st_mtime_ns)
        run_probe("fs", "--master", self.master, "--config", self.config)
        self.assertEqual((review.read_bytes(), review.stat().st_mtime_ns), before)


class TestState(ProbeCase):
    def state(self, label):
        return run_probe("state", "--master", self.master, "--label", label)

    def test_state_normal_allowed(self):
        self.make_review()
        self.assertEqual(self.state("normal").returncode, 0)
        row = report(self.master)["T5-normal"]
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["detail"]["guard"], "allowed")

    def test_state_excel_lock_refused(self):
        review = self.make_review()
        (self.master / "~$Review.xlsx").write_bytes(b"owner")
        before = review.read_bytes()
        self.assertEqual(self.state("excel-open").returncode, 0)
        row = report(self.master)["T5-excel-open"]
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["detail"]["guard"], "refused:excel_lock")
        self.assertEqual(row["detail"]["replace_while_open"], "ok")
        self.assertEqual(review.read_bytes(), before)

    def test_state_lock_undetected_is_fail(self):
        self.make_review()
        self.assertEqual(self.state("excel-open").returncode, 0)
        row = report(self.master)["T5-excel-open"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["guard"], "allowed")

    def test_state_missing_review_is_fail(self):
        self.assertEqual(self.state("normal").returncode, 0)
        self.assertEqual(report(self.master)["T5-normal"]["status"], "FAIL")


SEARCH_PAGE = '<li><div data-entity-urn="urn:li:jobPosting:4242"></div></li>'
POSTING_PAGE = '<div class="show-more-less-html__markup">The role</div>'


class FakeWeb:
    """A local LinkedIn and employer. `routes` maps a path prefix to (status, body)."""

    def __init__(self, routes):
        self.seen = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(self.path)
                for prefix, (status, body) in routes.items():
                    if self.path.startswith(prefix):
                        self.send_response(status)
                        self.end_headers()
                        self.wfile.write(body.encode("utf-8"))
                        return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def linkedin_requests(self):
        return [path for path in self.seen if path.startswith("/jobs-guest/")]


GOOD_ROUTES = {
    "/jobs-guest/jobs/api/seeMoreJobPostings/search": (200, SEARCH_PAGE),
    "/jobs-guest/jobs/api/jobPosting/4242": (200, POSTING_PAGE),
    "/employer": (200, "<html>careers</html>"),
}


class TestNet(ProbeCase):
    def net(self, routes):
        web = FakeWeb(routes)
        self.addCleanup(web.close)
        res = run_probe(
            "net", "--master", self.master, "--linkedin-base", web.base,
            "--employer-url", f"{web.base}/employer", "--pause", "0",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return web, report(self.master)["T3"]

    def test_all_ok_is_pass(self):
        web, row = self.net(GOOD_ROUTES)
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(len(web.linkedin_requests()), 2)

    def test_429_is_inconclusive_and_stops(self):
        routes = {**GOOD_ROUTES, "/jobs-guest/jobs/api/seeMoreJobPostings/search": (429, "slow down")}
        web, row = self.net(routes)
        self.assertEqual(row["status"], "INCONCLUSIVE", row)
        self.assertEqual(row["detail"]["retry_after_minutes"], 20)
        self.assertEqual(len(web.linkedin_requests()), 1)
        self.assertIn("/employer", web.seen)

    def test_429_on_the_posting_is_inconclusive(self):
        routes = {**GOOD_ROUTES, "/jobs-guest/jobs/api/jobPosting/4242": (429, "slow down")}
        _, row = self.net(routes)
        self.assertEqual(row["status"], "INCONCLUSIVE", row)

    def test_allowlist_403_named(self):
        routes = {**GOOD_ROUTES, "/jobs-guest/jobs/api/seeMoreJobPostings/search": (403, "403 blocked-by-allowlist")}
        _, row = self.net(routes)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["search"], "allowlist_blocked")

    def test_empty_results_is_fail(self):
        routes = {**GOOD_ROUTES, "/jobs-guest/jobs/api/seeMoreJobPostings/search": (200, "<html></html>")}
        web, row = self.net(routes)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["search"], "no_cards")
        self.assertEqual(len(web.linkedin_requests()), 1)

    def test_posting_without_description_is_fail(self):
        routes = {**GOOD_ROUTES, "/jobs-guest/jobs/api/jobPosting/4242": (200, "<html>sign in</html>")}
        _, row = self.net(routes)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["posting"], "no_description")

    def test_connection_refused_is_network_error(self):
        res = run_probe(
            "net", "--master", self.master, "--linkedin-base", "http://127.0.0.1:9",
            "--employer-url", "http://127.0.0.1:9/employer", "--pause", "0",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        row = report(self.master)["T3"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["search"], "network_error")


class RefusingProxy:
    """What a Cowork allowlist reportedly does: answers CONNECT with 403 and a header."""

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def do_CONNECT(self):
                self.send_response(403)
                self.send_header("X-Proxy-Error", "blocked-by-allowlist")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestNetFindings(ProbeCase):
    def run_net(self, web, **env):
        res = run_probe(
            "net", "--master", self.master, "--linkedin-base", web.base,
            "--employer-url", f"{web.base}/employer", "--pause", "0", env=env,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return report(self.master)["T3"]

    def test_connect_403_is_allowlist_with_raw_error(self):
        proxy = RefusingProxy()
        self.addCleanup(proxy.close)
        res = run_probe(
            "net", "--master", self.master, "--linkedin-base", "https://www.linkedin.invalid",
            "--employer-url", "https://employer.invalid/", "--pause", "0",
            env={"https_proxy": proxy.url, "no_proxy": ""},
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        row = report(self.master)["T3"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["search"], "allowlist_blocked")
        self.assertIn("Tunnel connection failed: 403", row["detail"]["errors"]["search"])

    def test_engine_stack_is_measured_separately(self):
        web = FakeWeb(GOOD_ROUTES)
        self.addCleanup(web.close)
        row = self.run_net(web)
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["detail"]["engine_http"], "ok")
        self.assertEqual(row["detail"]["statuses"]["engine_http"], 200)

    def test_python_reaching_it_is_not_enough(self):
        # urllib can pass while the engine's own HTTP stack cannot leave at all.
        web = FakeWeb(GOOD_ROUTES)
        self.addCleanup(web.close)
        empty = self.root / "no-node"
        empty.mkdir()
        row = self.run_net(web, PATH=str(empty))
        self.assertEqual(row["status"], "FAIL", row)
        self.assertEqual(row["detail"]["engine_http"], "no_node")

    def test_closed_employer_page_still_proves_reachability(self):
        web = FakeWeb({k: v for k, v in GOOD_ROUTES.items() if k != "/employer"})
        self.addCleanup(web.close)
        row = self.run_net(web)
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["detail"]["statuses"]["employer"], 404)

    def test_employer_rate_limit_is_not_a_failure(self):
        web = FakeWeb({**GOOD_ROUTES, "/employer": (429, "slow down")})
        self.addCleanup(web.close)
        self.assertEqual(self.run_net(web)["status"], "PASS")

    def test_status_of_each_page_is_recorded(self):
        web = FakeWeb({**GOOD_ROUTES, "/jobs-guest/jobs/api/seeMoreJobPostings/search": (999, "no")})
        self.addCleanup(web.close)
        row = self.run_net(web)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["statuses"]["search"], 999)

    def test_truncated_response_is_recorded_not_a_crash(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write(b"short")

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        res = run_probe(
            "net", "--master", self.master, "--linkedin-base", base,
            "--employer-url", f"{base}/e", "--pause", "0",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(report(self.master)["T3"]["detail"]["search"], "network_error")


@unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions")
class TestUnwritable(ProbeCase):
    def test_result_survives_an_unwritable_folder(self):
        os.chmod(self.master, 0o555)
        try:
            res = run_probe("env", "--master", self.master)
        finally:
            os.chmod(self.master, 0o755)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("T2 ", res.stdout)
        self.assertIn("could not be saved", res.stdout)

    def test_read_only_config_fails_t4(self):
        self.make_review()
        os.chmod(self.config, 0o555)
        try:
            run_probe("fs", "--master", self.master, "--config", self.config)
        finally:
            os.chmod(self.config, 0o755)
        row = report(self.master)["T4"]
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(row["detail"]["config_writable"])


class TestLongRun(ProbeCase):
    def test_timer_records_start_and_finish(self):
        res = run_probe("longrun", "--master", self.master, "--label", "timer", "--seconds", "1", "--heartbeat", "0.2")
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = report(self.master)
        self.assertEqual(rows["T6-timer-start"]["status"], "INCONCLUSIVE")
        finish = rows["T6-timer"]
        self.assertEqual(finish["status"], "PASS", finish)
        self.assertGreaterEqual(finish["detail"]["elapsed_seconds"], 1)
        self.assertLess(finish["detail"]["max_gap_seconds"], 1)
        beats = (self.master / "_probe-run" / "longrun-timer.heartbeat").read_text(encoding="utf-8").splitlines()
        self.assertGreater(len(beats), 1)

    def test_command_exit_code_and_output_are_kept(self):
        code = "print('hello from the command'); raise SystemExit(3)"
        res = run_probe(
            "longrun", "--master", self.master, "--label", "job", "--heartbeat", "0.2", "--", sys.executable, "-c", code,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        row = report(self.master)["T6-job"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail"]["exit_code"], 3)
        self.assertIn("hello", (self.master / "_probe-run" / "longrun-job.log").read_text(encoding="utf-8"))

    def test_a_killed_run_leaves_a_start_and_no_finish(self):
        proc = subprocess.Popen(
            [sys.executable, str(PROBE), "longrun", "--master", str(self.master), "--label", "killed",
             "--seconds", "60", "--heartbeat", "0.1"],
            stdout=subprocess.DEVNULL,
        )
        heartbeat = self.master / "_probe-run" / "longrun-killed.heartbeat"
        for _ in range(100):
            if heartbeat.exists() and heartbeat.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.1)
        proc.kill()
        proc.wait()
        rows = report(self.master)
        self.assertIn("T6-killed-start", rows)
        self.assertNotIn("T6-killed", rows)
        self.assertTrue(heartbeat.read_text(encoding="utf-8").strip())

    def test_nothing_to_run_is_refused(self):
        res = run_probe("longrun", "--master", self.master, "--label", "none")
        self.assertEqual(res.returncode, 2)

    def test_refuses_non_test_folder(self):
        real = self.root / "Strategic design ED.28"
        real.mkdir()
        res = run_probe("longrun", "--master", real, "--label", "x", "--seconds", "1")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(list(real.iterdir()), [])


class TestReviewShape(ProbeCase):
    def real_shape_review(self):
        """A workbook with the live columns, built by the engine from the checked-in fixture."""
        target = self.root / "real"
        fixture = HERE.parent / "engine" / "test" / "fixtures" / "strategic-design-history.csv"
        sync_export = HERE.parent / "engine" / "python" / "sync_export.py"
        res = subprocess.run(
            [sys.executable, str(sync_export), "init-review", "--dir", str(target), "--history", str(fixture)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return target / "Review.xlsx"

    def test_blank_workbook_is_named_as_not_ready_for_t6(self):
        self.make_review()
        run_probe("fs", "--master", self.master, "--config", self.config)
        detail = report(self.master)["T5-write"]["detail"]
        self.assertEqual(detail["ready_for_full_run"], False)

    def test_test_copy_blanks_contacts_and_still_exports(self):
        from openpyxl import load_workbook

        source = self.real_shape_review()
        script = HERE / "make_test_copy.py"
        res = subprocess.run(
            [sys.executable, str(script), "--from", str(source), "--to", str(self.master)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        sheet = load_workbook(self.master / "Review.xlsx").worksheets[0]
        header = {cell.value: cell.column for cell in sheet[2]}
        for name in ("Contact Name", "Contact Role", "Contact Email / LinkedIn", "Notes"):
            values = [sheet.cell(row=r, column=header[name]).value for r in range(3, sheet.max_row + 1)]
            self.assertTrue(all(v is None for v in values), name)
        companies = [sheet.cell(row=r, column=header["Company / Outreach Account"]).value for r in range(3, sheet.max_row + 1)]
        self.assertTrue(any(companies))

        run_probe("fs", "--master", self.master, "--config", self.config)
        self.assertEqual(report(self.master)["T5-write"]["detail"]["ready_for_full_run"], True)

        sync_export = HERE.parent / "engine" / "python" / "sync_export.py"
        out = self.master / "_probe-run" / "history.csv"
        res = subprocess.run(
            [sys.executable, str(sync_export), "export-history", "--dir", str(self.master), "--out", str(out)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_test_copy_refuses_a_real_folder(self):
        source = self.real_shape_review()
        real = self.root / "Strategic design ED.28"
        real.mkdir()
        res = subprocess.run(
            [sys.executable, str(HERE / "make_test_copy.py"), "--from", str(source), "--to", str(real)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 2)
        self.assertEqual(list(real.iterdir()), [])


class TestInstructions(unittest.TestCase):
    """The words a colleague and Claude follow are the interface here."""

    skill = (HERE / "windows-probe" / "skills" / "probe" / "SKILL.md").read_text(encoding="utf-8")
    full_run = (HERE / "windows-probe" / "skills" / "probe" / "references" / "full-run.md").read_text(encoding="utf-8")
    guide = (HERE / "GUIDA-collega.md").read_text(encoding="utf-8")
    results = (HERE / "RESULTS-template.md").read_text(encoding="utf-8")

    def test_files_are_kept_offline_before_the_first_test(self):
        self.assertLess(self.skill.index("Mantieni sempre su questo dispositivo"), self.skill.index(" env --master"))
        self.assertIn("Mantieni sempre su questo dispositivo", self.guide)

    def test_paths_resolve_where_they_are_used(self):
        self.assertIn('ENGINE` is `${CLAUDE_SKILL_DIR}/engine', self.skill)
        self.assertIn("${CLAUDE_SKILL_DIR}/references/full-run.md", self.skill)
        self.assertNotIn("${CLAUDE_SKILL_DIR}", self.full_run)
        self.assertNotIn('--master "TEST"', self.skill)
        self.assertIn("<TEST-folder-path>", self.skill)

    def test_full_run_checks_the_folder_first(self):
        first = self.full_run.index("REFUSED")
        self.assertLess(first, self.full_run.index("export-history"))

    def test_long_commands_are_measured_without_polling(self):
        self.assertIn("longrun", self.full_run)
        self.assertIn("--seconds 10800", self.full_run)
        self.assertRegex(self.full_run, r"Do not poll")

    def test_guide_asks_for_everything_t6_produces(self):
        for name in ("probe-report.jsonl", "run-report.json", "read-report.json", "FOGLIO-risultati.md"):
            self.assertIn(name, self.guide)
        self.assertTrue((HERE / "FOGLIO-risultati.md").exists())

    def test_results_say_inconclusive_is_not_a_failure(self):
        self.assertIn("INCONCLUSIVE", self.results)


class TestClassify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("probe", PROBE)
        cls.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probe)

    def test_classes(self):
        classify = self.probe.classify_response
        self.assertEqual(classify(200, "<html>fine</html>", None), "ok")
        self.assertEqual(classify(429, "", None), "rate_limited")
        self.assertEqual(classify(403, "403 blocked-by-allowlist", None), "allowlist_blocked")
        self.assertEqual(classify(403, "go away", None), "forbidden")
        self.assertEqual(classify(200, "Just a moment...", None), "challenge")
        self.assertEqual(classify(500, "", None), "http_error")
        self.assertEqual(classify(None, "", "timed out"), "network_error")
        self.assertEqual(classify(None, "", "OSError: Tunnel connection failed: 403 Forbidden"), "allowlist_blocked")
        self.assertEqual(classify(None, "", "OSError: Tunnel connection failed: 502 Bad Gateway"), "network_error")


class TestBuild(unittest.TestCase):
    """Built once: it runs `npm run build`. Tested from the zip, as the colleague gets it."""

    @classmethod
    def setUpClass(cls):
        res = subprocess.run(
            [sys.executable, str(HERE / "build.py")], capture_output=True, text=True, timeout=300
        )
        if res.returncode != 0:
            raise AssertionError(res.stdout + res.stderr)
        cls.zip_path = HERE / "dist" / "talent-placement-probe.zip"
        cls.names = zipfile.ZipFile(cls.zip_path).namelist()
        cls.root = Path(tempfile.mkdtemp(prefix="probe-unzipped-"))
        zipfile.ZipFile(cls.zip_path).extractall(cls.root)
        cls.plugin = cls.root / "talent-placement-probe"
        cls.skill = cls.plugin / "skills" / "probe"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_zip_layout(self):
        self.assertEqual({name.split("/")[0] for name in self.names}, {"talent-placement-probe"})
        self.assertIn("talent-placement-probe/.claude-plugin/plugin.json", self.names)
        self.assertIn("talent-placement-probe/skills/probe/SKILL.md", self.names)
        self.assertFalse((self.plugin / "bin").exists(), "a top-level bin/ stops Cowork installing it")

    def test_zip_limits(self):
        info = zipfile.ZipFile(self.zip_path).infolist()
        self.assertLess(len(info), 5000)
        self.assertLess(sum(i.file_size for i in info), 200 * 1024 * 1024)

    def test_no_test_files_shipped(self):
        self.assertFalse([n for n in self.names if "test_sync_export" in n or "__pycache__" in n or ".DS_Store" in n])

    def test_staged_engine_runs_from_other_cwd(self):
        res = subprocess.run(
            ["node", str(self.skill / "engine" / "lib" / "cli.js")],
            capture_output=True, text=True, cwd=tempfile.gettempdir(),
        )
        self.assertIn("discover", res.stdout + res.stderr)
        self.assertIn("read", res.stdout + res.stderr)
        self.assertNotIn("SyntaxError", res.stderr)

    def test_engine_finds_its_data(self):
        self.assertTrue((self.skill / "engine" / "data" / "aggregators.csv").exists())

    def test_vendored_openpyxl_imports(self):
        vendor = self.skill / "engine" / "python" / "vendor"
        code = f"import sys; sys.path.insert(0, {str(vendor)!r}); import openpyxl; print(openpyxl.__file__)"
        res = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("vendor", res.stdout)

    def test_probe_uses_staged_engine(self):
        master = self.root / "TEST staged"
        master.mkdir()
        script = self.skill / "scripts" / "probe.py"
        self.assertEqual(run_probe("env", "--master", master, script=script).returncode, 0)
        row = report(master)["T2"]
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["detail"]["openpyxl_source"], "vendor")

    def test_skill_frontmatter(self):
        text = (self.skill / "SKILL.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        self.assertRegex(head, r"(?m)^name: probe$")
        description = re.search(r"(?m)^description: (.+)$", head).group(1)
        self.assertLessEqual(len(description), 1024)
        self.assertIn("${CLAUDE_SKILL_DIR}/scripts/probe.py", text)

    def test_full_run_never_publishes(self):
        text = (self.skill / "references" / "full-run.md").read_text(encoding="utf-8")
        self.assertIn("--resume", text)
        self.assertIn("Do not run `stage` or `append`", text)


if __name__ == "__main__":
    unittest.main()
