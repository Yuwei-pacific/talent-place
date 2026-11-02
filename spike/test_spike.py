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
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
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


if __name__ == "__main__":
    unittest.main()
