#!/usr/bin/env python3
"""python3 plugin/test_plugin.py

What a colleague receives is the zip, so that is what is tested: its shape, that the
packed engine starts from somewhere else, and that the words Claude follows name
commands and stop codes the engine really has.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NAME = "talent-placement"
JOB_RUN = (REPO / "engine" / "python" / "job_run.py").read_text(encoding="utf-8")


class TestPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        res = subprocess.run([sys.executable, str(HERE / "build.py")], capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise AssertionError(res.stdout + res.stderr)
        cls.zip_path = HERE / "dist" / f"{NAME}.zip"
        cls.names = zipfile.ZipFile(cls.zip_path).namelist()
        cls.root = Path(tempfile.mkdtemp(prefix="plugin-"))
        zipfile.ZipFile(cls.zip_path).extractall(cls.root)
        cls.plugin = cls.root / NAME
        cls.skills = cls.plugin / "skills"
        cls.engine = cls.skills / "cerca-stage" / "engine"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def text(self, *parts):
        return self.skills.joinpath(*parts).read_text(encoding="utf-8")

    def test_zip_shape(self):
        self.assertEqual({n.split("/")[0] for n in self.names}, {NAME})
        self.assertIn(f"{NAME}/.claude-plugin/plugin.json", self.names)
        self.assertFalse((self.plugin / "bin").exists(), "a top-level bin/ stops the app installing it")
        info = zipfile.ZipFile(self.zip_path).infolist()
        self.assertLess(len(info), 5000)
        self.assertLess(sum(i.file_size for i in info), 200 * 1024 * 1024)
        junk = [n for n in self.names if "/test_" in n or "__pycache__" in n or ".DS_Store" in n or "/fixtures/" in n]
        self.assertEqual(junk, [])

    def test_manifest_and_skill_names(self):
        manifest = json.loads((self.plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], NAME)
        for skill in ("cerca-stage", "diagnostica"):
            head = self.text(skill, "SKILL.md").split("---")[1]
            self.assertRegex(head, rf"(?m)^name: {skill}$")
            self.assertLessEqual(len(re.search(r"(?m)^description: (.+)$", head).group(1)), 1024)

    def test_no_config_is_packed(self):
        # A4: there is one copy of A1-A4 and the A2/A3 pairs, where colleagues edit it.
        self.assertEqual([n for n in self.names if "A1-regole" in n or "A3-cohort" in n or "A2-profilo" in n], [])

    def test_packed_engine_starts_from_another_folder(self):
        res = subprocess.run(["node", str(self.engine / "lib" / "cli.js")], capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertIn("discover", res.stdout + res.stderr)
        self.assertIn("type", json.loads((self.engine / "package.json").read_text(encoding="utf-8")))
        self.assertTrue((self.engine / "data" / "aggregators.csv").exists())

    def test_packed_python_brings_its_own_openpyxl(self):
        code = (
            f"import sys; sys.path.insert(0, {str(self.engine / 'python')!r}); "
            "import job_run, openpyxl; print(openpyxl.__file__)"
        )
        res = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("vendor", res.stdout)

    def test_packed_entry_finds_config_from_the_publish_folder(self):
        base = Path(tempfile.mkdtemp(prefix="plugin-od-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        master = "Strategic design ED.28"
        config = base / "talent-place" / "config" / master
        config.mkdir(parents=True)
        (config.parent / "A1-regole-ricerca.md").write_text("A1", encoding="utf-8")
        (config / "A2-profilo-strategic-design.md").write_text("master_id: strategic-design\n", encoding="utf-8")
        (config / "A3-cohort.yaml").write_text(
            f'master_id: strategic-design\nedition: ED.28\nhistory_file: "../../../jobSearch_outPut/{master}/Review.xlsx"\n',
            encoding="utf-8",
        )
        out = base / "jobSearch_outPut" / master
        out.mkdir(parents=True)
        res = subprocess.run(
            [sys.executable, "-X", "utf8", str(self.engine / "python" / "job_run.py"), "masters"],
            capture_output=True, text=True, encoding="utf-8", cwd=out,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        rows = json.loads(res.stdout)["masters"]
        self.assertEqual([(r["master"], r["ready"]) for r in rows], [(master, True)])

        res = subprocess.run(
            [sys.executable, "-X", "utf8", str(self.engine / "python" / "job_run.py"), "masters"],
            capture_output=True, text=True, encoding="utf-8", cwd=tempfile.gettempdir(),
        )
        self.assertEqual(res.returncode, 3)
        self.assertEqual(json.loads(res.stdout)["stop"], "config_not_found")

    def test_every_stop_code_is_explained(self):
        codes = set(re.findall(r'Stop\("([a-z_0-9]+)"', JOB_RUN))
        self.assertGreater(len(codes), 15)
        explained = self.text("cerca-stage", "references", "arresti.md")
        self.assertEqual(sorted(c for c in codes if f"`{c}`" not in explained), [])

    def test_instructions_only_name_commands_that_exist(self):
        real = set(re.findall(r'add_parser\("([a-z-]+)"', JOB_RUN))
        for skill, *rest in (("cerca-stage", "SKILL.md"), ("diagnostica", "SKILL.md")):
            used = set(re.findall(r"JOB (\w[\w-]*)", self.text(skill, *rest)))
            self.assertTrue(used, skill)
            self.assertEqual(sorted(used - real), [], skill)

    def test_the_write_waits_for_a_person(self):
        skill = self.text("cerca-stage", "SKILL.md")
        self.assertIn("Never run `JOB publish` with `--confirm` unless", skill)
        self.assertLess(skill.index("Scrivo queste aziende in Review.xlsx?"), skill.index("--confirm` and"))

    def test_verdict_guide_matches_the_builder(self):
        guide = self.text("cerca-stage", "references", "verdetti.md")
        builder = (REPO / "engine" / "python" / "build_tsv.py").read_text(encoding="utf-8")
        for label in re.search(r'LABELS = INCLUDED \+ \(([^)]*)\)', builder).group(1).replace('"', "").split(","):
            self.assertIn(label.strip(), guide)
        for field in ("id", "label", "area", "quotes", "reason", "score", "workMode", "location", "ground", "company"):
            self.assertIn(f"`{field}`", guide)
        for mode in ("onsite", "hybrid", "fully_remote", "to_verify"):
            self.assertIn(mode, guide)


if __name__ == "__main__":
    unittest.main()
