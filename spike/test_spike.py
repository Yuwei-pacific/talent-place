#!/usr/bin/env python3
"""python3 spike/test_spike.py

Offline tests for the Windows probe. Throwaway, like everything under spike/: this
kit gets one chance on a colleague's computer, so what would waste that chance is
pinned here and nothing more.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
