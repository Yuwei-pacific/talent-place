#!/usr/bin/env python3
"""python3 python/test_run_entry.py

Covers `build-tsv` and `job_run.py`: the two steps that replace what a person, or a
script left in a run directory, used to do by hand. Runs offline: `prepare`'s calls
to the network are replaced, and `publish` runs the real commands on a temp folder.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_tsv  # noqa: E402
import job_run  # noqa: E402
import sync_export  # noqa: E402

A2 = """# A2
master_id: strategic-design

### Service Design / CX

**Presenza nel percorso:** Da confermare

**Termini di ricerca — a cura di Talent Placement:** service design, customer journey

**Termini secondari, non eseguiti di default dal 2026-11-02:** clienteling

### Consulting

**Presenza nel percorso:** Confermata

**Termini di ricerca — a cura di Talent Placement:** consulting

### Old Area

**Presenza nel percorso:** Non prevista

**Termini di ricerca — a cura di Talent Placement:** legacy

## Falsi positivi

- Customer care
  `termini:` call center; recupero crediti
"""

A3 = """master_id: strategic-design
edition: ED.28
history_file: "{history}"
search_preferences:
  geography_priority:
    - Milan
    - EU
  job_languages:
    - it
    - en
"""


def card(jid, title="Service Design Intern", company="Acme", location="Milan, Lombardy, Italy", **extra):
    return {
        "title": title,
        "company": company,
        "location": location,
        "url": f"https://it.linkedin.com/jobs/view/role-{jid}",
        "posted": "2 days ago",
        "sourceJobId": jid,
        "source": "linkedin",
        "discoveryQuery": "service design stage — Italy",
        "alternateUrls": [],
        **extra,
    }


def desc(c, text="You map customer journeys with users.", **extra):
    return {**c, "desc": text, "closedOnPage": False, **extra}


def verdict(jid, label="pertinente", **extra):
    v = {
        "id": jid,
        "label": label,
        "score": 80,
        "area": ["Service Design / CX"],
        "quotes": ["map customer journeys"],
        "reason": "Mappa i journey.",
    }
    v.update(extra)
    return v


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()
        self.a2 = self.tmp / "A2.md"
        self.a2.write_text(A2, encoding="utf-8")
        self.history = self.tmp / "history.csv"
        header = list(sync_export.A4_COLUMNS) + ["Company ID"]
        with self.history.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(header)
            w.writerow(["Known Co"] + [""] * (len(header) - 1))

    def write_run(self, cards, descriptions, verdicts):
        (self.run_dir / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
        (self.run_dir / "descriptions.json").write_text(json.dumps(descriptions), encoding="utf-8")
        (self.run_dir / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")

    def build(self, **kw):
        return build_tsv.build(
            self.run_dir, a2_path=self.a2, history=self.history, date="2026-11-03", **kw
        )

    def rows(self):
        text = (self.run_dir / "final" / "run.tsv").read_text(encoding="utf-8")
        header, rows = sync_export.parse_tsv(text)
        return [dict(zip(header, r)) for r in rows]

    def assertRefused(self, fragment):
        with self.assertRaises(build_tsv.BuildError) as ctx:
            self.build()
        self.assertIn(fragment, str(ctx.exception))
        self.assertFalse((self.run_dir / "final" / "run.tsv").exists(), "a refusal must write nothing")


class TestBuild(Case):
    def test_builds_a_row_stage_accepts_from_card_data(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1")])
        self.build()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["Company / Outreach Account"], "Acme")
        self.assertEqual(r["Job Links"], "1. " + c["url"])
        self.assertEqual(r["Matching Job Titles"], "1. Service Design Intern")
        self.assertEqual(r["Matching Score"], "1. 80")
        self.assertEqual(r["In Italy?"], "Yes")
        self.assertEqual(r["Contact Search Status"], "New job found")
        self.assertEqual(r["Last Checked"], "2026-11-03")
        self.assertTrue(r["Notes"].startswith("[NEW COMPANY] 1. [pertinente] «map customer journeys»"))
        text = (self.run_dir / "final" / "run.tsv").read_text(encoding="utf-8")
        header, parsed = sync_export.parse_tsv(text)
        self.assertEqual(sync_export.validate_rows(header, parsed), [])

    def test_a_company_already_in_history_is_an_update(self):
        c = card("1", company="Known Co")
        self.write_run([c], [desc(c)], [verdict("1")])
        self.build()
        self.assertTrue(self.rows()[0]["Notes"].startswith("[UPDATE EXISTING ROW]"))

    def test_verdict_for_a_card_the_run_never_saw_is_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("999")])
        self.assertRefused("999")

    def test_a_quote_not_in_the_description_is_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", quotes=["design the whole future of banking"])])
        self.assertRefused("design the whole future of banking")

    def test_a_quote_differing_only_in_whitespace_is_accepted(self):
        c = card("1")
        self.write_run([c], [desc(c, "You   map\n customer  journeys.")], [verdict("1")])
        self.build()
        self.assertEqual(len(self.rows()), 1)

    def test_a_label_without_a_read_description_is_refused(self):
        c = card("1")
        self.write_run([c], [], [verdict("1")])
        self.assertRefused("description")

    def test_an_included_role_needs_a_quote(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", quotes=[])])
        self.assertRefused("quote")

    def test_a_closed_posting_cannot_be_included(self):
        c = card("1")
        self.write_run([c], [desc(c, closedOnPage=True)], [verdict("1")])
        self.assertRefused("closed")

    def test_a_url_nobody_verified_is_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", url="https://acme.example/careers/made-up")])
        self.assertRefused("made-up")

    def test_an_employer_url_the_probe_checked_becomes_primary_and_keeps_the_portal(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", url="https://acme.example/job/1")])
        (self.run_dir / "employer-checks.csv").write_text(
            ";".join(sync_export.CHECK_COLUMNS)
            + "\nhttps://acme.example/job/1;Acme;Employer verified active;true;true;true;Job;ok;10\n",
            encoding="utf-8",
        )
        self.build()
        self.assertEqual(self.rows()[0]["Job Links"], "1. https://acme.example/job/1")
        ev = list(csv.DictReader((self.run_dir / "final" / "role-evidence.csv").open(encoding="utf-8"), delimiter=";"))
        self.assertEqual(ev[0]["alternate_urls"], c["url"])
        self.assertEqual(ev[0]["posted"], "2 days ago")

    def test_a_pipe_in_a_title_does_not_add_a_role(self):
        c = card("1", title="Junior Consultant | Customer Advisory")
        self.write_run([c], [desc(c)], [verdict("1")])
        self.build()
        role_rows, _ = sync_export.explode_roles(
            sync_export.parse_tsv((self.run_dir / "final" / "run.tsv").read_text(encoding="utf-8"))[1]
        )
        self.assertEqual(len(role_rows), 1)
        self.assertEqual(role_rows[0]["Job Title"], "Junior Consultant / Customer Advisory")

    def test_an_area_a2_does_not_have_is_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", area=["Astrology"])])
        self.assertRefused("Astrology")

    def test_an_area_a2_rules_out_is_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", area=["Old Area"])])
        self.assertRefused("Old Area")

    def test_an_unconfirmed_area_is_flagged_and_a_confirmed_one_is_not(self):
        c, k = card("1"), card("2", company="Beta")
        self.write_run([c, k], [desc(c), desc(k)], [verdict("1"), verdict("2", area=["Consulting"])])
        self.build()
        notes = {r["Company / Outreach Account"]: r["Notes"] for r in self.rows()}
        self.assertIn("ipotesi operativa", notes["Acme"])
        self.assertNotIn("ipotesi operativa", notes["Beta"])

    def test_a_location_without_a_country_is_refused_until_a_verdict_states_it(self):
        c = card("1", location="Greater Padova (Padua) Metropolitan Area")
        self.write_run([c], [desc(c, "You map customer journeys. Campodarsego, Padova Italy")], [verdict("1")])
        self.assertRefused("Greater Padova")
        self.write_run([c], [desc(c, "You map customer journeys. Campodarsego, Padova Italy")], [verdict("1", location="Campodarsego, Padova, Italy")])
        self.build()
        self.assertEqual(self.rows()[0]["In Italy?"], "Yes")

    def test_a_stated_location_must_come_from_the_posting(self):
        c = card("1", location="Greater Padova (Padua) Metropolitan Area")
        self.write_run([c], [desc(c)], [verdict("1", location="Atlantis, Italy")])
        self.assertRefused("Atlantis")

    def test_two_verdicts_for_one_card_are_refused(self):
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1"), verdict("1")])
        self.assertRefused("1")

    def test_roles_are_ordered_pertinente_first_within_and_across_companies(self):
        a, b, z = card("1"), card("2"), card("3", company="Zeta")
        self.write_run(
            [a, b, z],
            [desc(a), desc(b), desc(z)],
            [verdict("1", label="adiacente", score=90), verdict("2", score=70), verdict("3", score=75)],
        )
        self.build()
        rows = self.rows()
        self.assertEqual([r["Company / Outreach Account"] for r in rows], ["Zeta", "Acme"])
        self.assertEqual(rows[1]["Matching Score"], "1. 70 | 2. 90")

    def test_fuori_profilo_and_exclusions_leave_the_tsv_and_are_recorded(self):
        a, b, m = card("1"), card("2", company="Beta"), card("3", company="Mono")
        self.write_run(
            [a, b, m],
            [desc(a), desc(b), desc(m)],
            [
                verdict("1"),
                verdict("2", label="fuori profilo", reason="Solo data entry."),
                verdict("3", label="escluso", ground="extracurricular_only", quotes=["map customer journeys"]),
            ],
        )
        self.build()
        self.assertEqual([r["Company / Outreach Account"] for r in self.rows()], ["Acme"])
        rec = json.loads((self.run_dir / "final" / "exclusions-read.json").read_text(encoding="utf-8"))
        self.assertEqual({e["company"] for e in rec}, {"Beta", "Mono"})
        self.assertEqual(rec[0]["url"], b["url"])

    def test_admit_excludes_even_a_role_labelled_pertinente(self):
        a, b = card("1"), card("2", company="Beta")
        self.write_run([a, b], [desc(a), desc(b)], [verdict("1"), verdict("2")])
        final = self.run_dir / "final"
        final.mkdir()
        (final / "exclusions.json").write_text(
            json.dumps({"excluded": [{"url": b["url"], "ground": "mandatory-language", "detail": "french"}]}),
            encoding="utf-8",
        )
        summary = self.build()
        self.assertEqual([r["Company / Outreach Account"] for r in self.rows()], ["Acme"])
        self.assertEqual(summary["excluded_by_admit"], 1)

    def test_read_without_verdict_and_unread_cards_go_to_unresolved(self):
        a, b, u = card("1"), card("2", company="Beta"), card("3", company="Unread")
        self.write_run([a, b, u], [desc(a), desc(b)], [verdict("1")])
        summary = self.build()
        un = json.loads((self.run_dir / "final" / "unresolved.json").read_text(encoding="utf-8"))
        self.assertEqual({(x["company"], x["missing"]) for x in un}, {("Beta", "giudizio"), ("Unread", "descrizione")})
        self.assertEqual(summary["unresolved"], 2)


class TestCarry(Case):
    def previous(self):
        prev = self.tmp / "prev"
        prev.mkdir()
        header = list(sync_export.A4_COLUMNS)
        cells = dict.fromkeys(header, "")
        cells.update({
            "Company / Outreach Account": "Acme",
            "In Italy?": "Yes",
            "Locations": "1. Turin, Italy | 2. Rome, Italy",
            "Master-fit Themes": "Consulting",
            "Matching Job Titles": "1. Old One | 2. Old Two",
            "Matching Score": "1. 90 | 2. 50",
            "Job Links": "1. https://x.example/old-1 | 2. https://x.example/old-2",
            "Role Count": "2",
            "Curricular Evidence": "To verify — curricular status",
            "Work Modes": "1. Not stated | 2. Hybrid (dichiarato)",
            "Sources / Portals": "LinkedIn Jobs",
            "Previously Contacted?": "To verify",
            "Contact Search Status": "New job found",
            "Outreach Decision": "Review",
            "Notes": "[NEW COMPANY] 1. [pertinente] Vecchio uno. 2. [adiacente] Vecchio due.",
            "Verification Status": "Portal verified",
            "Last Checked": "2026-11-02",
        })
        other = dict(cells)
        other.update({
            "Company / Outreach Account": "Gone Co",
            "Locations": "1. Paris, France",
            "In Italy?": "No",
            "Matching Job Titles": "1. Only Old",
            "Matching Score": "1. 60",
            "Job Links": "1. https://x.example/only",
            "Role Count": "1",
            "Work Modes": "Not stated",
            "Notes": "[UPDATE EXISTING ROW] 1. [adiacente] Solo vecchio.",
        })
        with (prev / "run.tsv").open("w", encoding="utf-8") as f:
            for row in (header, [cells[c] for c in header], [other[c] for c in header]):
                f.write("\t".join(row) + "\n")
        with (prev / "role-evidence.csv").open("w", encoding="utf-8") as f:
            f.write("url;posted;alternate_urls;search_query\n")
            for u in ("old-1", "old-2", "only"):
                f.write(f"https://x.example/{u};1 week ago;;q — Italy\n")
        return prev / "run.tsv"

    def test_previous_roles_survive_and_merge_by_company(self):
        prev = self.previous()
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1", score=70)])
        summary = self.build(carry=prev)
        rows = {r["Company / Outreach Account"]: r for r in self.rows()}
        self.assertEqual(set(rows), {"Acme", "Gone Co"})
        acme = rows["Acme"]
        self.assertEqual(acme["Role Count"], "3")
        self.assertEqual(acme["Matching Job Titles"], "1. Old One | 2. Service Design Intern | 3. Old Two")
        self.assertEqual(acme["Matching Score"], "1. 90 | 2. 70 | 3. 50")
        self.assertEqual(acme["Work Modes"], "1. Not stated | 2. Not stated | 3. Hybrid (dichiarato)")
        self.assertEqual(acme["Last Checked"], "2026-11-03")
        self.assertIn("1. [pertinente] Vecchio uno.", acme["Notes"])
        self.assertIn("3. [adiacente] Vecchio due.", acme["Notes"])
        self.assertEqual(rows["Gone Co"]["Last Checked"], "2026-11-02")
        self.assertEqual(rows["Gone Co"]["Verification Status"], "Portal verified")
        self.assertEqual((summary["roles_new"], summary["roles_carried"]), (1, 3))

    def test_a_role_found_again_appears_once_with_the_new_reading(self):
        prev = self.previous()
        c = card("1")
        c["url"] = "https://x.example/old-1"
        self.write_run([c], [desc(c)], [verdict("1", score=70)])
        summary = self.build(carry=prev)
        acme = {r["Company / Outreach Account"]: r for r in self.rows()}["Acme"]
        self.assertEqual(acme["Role Count"], "2")
        self.assertEqual(acme["Matching Score"], "1. 70 | 2. 50")
        self.assertEqual(summary["roles_carried"], 2)

    def test_a_carried_place_with_no_country_keeps_the_previous_answer(self):
        prev = self.previous()
        text = prev.read_text(encoding="utf-8").replace("1. Paris, France", "1. Greater Paris Metropolitan Region")
        prev.write_text(text, encoding="utf-8")
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1")])
        self.build(carry=prev)
        rows = {r["Company / Outreach Account"]: r for r in self.rows()}
        self.assertEqual(rows["Gone Co"]["In Italy?"], "No")

    def test_first_seen_marks_what_is_new_and_keeps_the_older_date(self):
        prev = self.previous()
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1")])
        self.build(carry=prev)
        final = self.run_dir / "final"
        evidence = sync_export.load_evidence(str(final))
        rows = sync_export.parse_tsv((final / "run.tsv").read_text(encoding="utf-8"))[1]
        role_rows, _ = sync_export.explode_roles(rows, evidence)
        seen = {r["Job Title"]: r["First Seen"] for r in role_rows}
        self.assertEqual(seen["Service Design Intern"], "2026-11-03")
        self.assertEqual(seen["Old One"], "2026-11-02")

    def test_a_previous_row_whose_notes_cannot_be_split_is_refused(self):
        prev = self.previous()
        text = prev.read_text(encoding="utf-8").replace("1. [pertinente] Vecchio uno. 2. [adiacente] Vecchio due.", "prose")
        prev.write_text(text, encoding="utf-8")
        c = card("1")
        self.write_run([c], [desc(c)], [verdict("1")])
        with self.assertRaises(build_tsv.BuildError) as ctx:
            self.build(carry=prev)
        self.assertIn("Acme", str(ctx.exception))


class Master(Case):
    def setUp(self):
        super().setUp()
        self.config = self.tmp / "repo" / "config"
        self.folder = self.config / "Strategic design ED.28"
        self.folder.mkdir(parents=True)
        (self.folder / "A2-profilo-strategic-design.md").write_text(A2, encoding="utf-8")
        self.master_dir = self.tmp / "out" / "Strategic design ED.28"
        self.master_dir.mkdir(parents=True)
        (self.folder / "A3-cohort.yaml").write_text(
            A3.format(history="../../../out/Strategic design ED.28/Review.xlsx"), encoding="utf-8"
        )

    def resolve(self, name="Strategic design ED.28"):
        return job_run.resolve_master(name, config_root=self.config)


class TestResolve(Master):
    def test_finds_the_folder_from_a3(self):
        m = self.resolve()
        self.assertEqual(m.master_id, "strategic-design")
        self.assertEqual(m.edition, "ED.28")
        self.assertEqual(m.dir.resolve(), self.master_dir.resolve())

    def assertStops(self, code, name="Strategic design ED.28"):
        with self.assertRaises(job_run.Stop) as ctx:
            self.resolve(name)
        self.assertEqual(ctx.exception.code, code)

    def test_a_mistyped_master_stops_and_lists_what_exists(self):
        with self.assertRaises(job_run.Stop) as ctx:
            self.resolve("Strategic desing ED.28")
        self.assertEqual(ctx.exception.code, "master_unknown")
        self.assertIn("Strategic design ED.28", ctx.exception.detail)

    def test_a_path_cannot_stand_in_for_a_master(self):
        self.assertStops("master_unknown", "../Strategic design ED.28")

    def test_a2_and_a3_that_disagree_stop(self):
        (self.folder / "A2-profilo-strategic-design.md").write_text(A2.replace("strategic-design", "accessory"), encoding="utf-8")
        self.assertStops("master_id_mismatch")

    def test_a_missing_publish_folder_stops_and_is_not_created(self):
        shutil.rmtree(self.master_dir)
        self.assertStops("master_dir_missing")
        self.assertFalse(self.master_dir.exists())


class TestConfigRoot(Master):
    """The packed engine no longer sits beside config/, so it has to be found."""

    def test_found_from_a_folder_below_the_repo(self):
        deep = self.tmp / "repo" / "engine" / "python"
        deep.mkdir(parents=True)
        (self.config / "A1-regole-ricerca.md").write_text("A1", encoding="utf-8")
        self.assertEqual(job_run.find_config_root(deep).resolve(), self.config.resolve())

    def test_found_from_the_folder_that_holds_the_repo(self):
        (self.config / "A1-regole-ricerca.md").write_text("A1", encoding="utf-8")
        (self.tmp / "repo").rename(self.tmp / "talent-place")
        found = job_run.find_config_root(self.tmp)
        self.assertEqual(found.resolve(), (self.tmp / "talent-place" / "config").resolve())

    def test_found_from_a_sibling_such_as_the_publish_folder(self):
        (self.config / "A1-regole-ricerca.md").write_text("A1", encoding="utf-8")
        (self.tmp / "repo").rename(self.tmp / "talent-place")
        self.assertTrue(job_run.find_config_root(self.master_dir).samefile(self.tmp / "talent-place" / "config"))

    def test_a_folder_that_only_looks_like_config_is_not_taken(self):
        with self.assertRaises(job_run.Stop) as ctx:
            job_run.find_config_root(self.tmp / "repo")
        self.assertEqual(ctx.exception.code, "config_not_found")

    def test_masters_lists_each_one_and_whether_its_folder_is_there(self):
        other = self.config / "Accessory design ED.14"
        other.mkdir()
        (other / "A3-cohort.yaml").write_text(A3.format(history="../../../out/missing/Review.xlsx"), encoding="utf-8")
        rows = {r["master"]: r for r in job_run.masters(config_root=self.config)["masters"]}
        self.assertTrue(rows["Strategic design ED.28"]["ready"])
        self.assertFalse(rows["Accessory design ED.14"]["ready"])
        self.assertTrue(rows["Accessory design ED.14"]["problem"])


class TestPortability(Master):
    def test_children_speak_utf8_and_see_the_packed_openpyxl(self):
        seen = {}

        def fake(cmd, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(job_run.subprocess, "run", side_effect=fake):
            job_run.run_step(["x"])
        self.assertEqual(seen["encoding"], "utf-8")
        self.assertEqual(seen["env"]["PYTHONUTF8"], "1")
        self.assertIn(str(job_run.HERE / "vendor"), seen["env"]["PYTHONPATH"])

    def test_windows_is_kept_awake_for_the_run_and_released_after(self):
        calls = []
        kernel = mock.Mock()
        kernel.SetThreadExecutionState.side_effect = lambda flags: calls.append(flags)
        with mock.patch.object(job_run.sys, "platform", "win32"), mock.patch.object(job_run, "_kernel32", lambda: kernel):
            with job_run.keep_awake():
                self.assertEqual(calls, [0x80000001])
        self.assertEqual(calls, [0x80000001, 0x80000000])

    def test_keeping_awake_never_stops_a_run(self):
        def broken():
            raise OSError("no kernel32")

        with mock.patch.object(job_run.sys, "platform", "win32"), mock.patch.object(job_run, "_kernel32", broken):
            with job_run.keep_awake():
                pass

    def test_doctor_does_not_fail_the_mount_check_where_it_cannot_ask(self):
        proc_args = [sys.executable, str(HERE / "sync_export.py"), "doctor", "--dir", str(self.master_dir)]
        with mock.patch.object(sync_export.sys, "platform", "win32"):
            import argparse, io, contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sync_export.cmd_doctor(argparse.Namespace(dir=str(self.master_dir)))
        checks = {c["check"]: c for c in json.loads(buf.getvalue())["checks"]}
        mount = [c for name, c in checks.items() if "OneDrive" in name]
        self.assertEqual(len(mount), 1)
        self.assertTrue(mount[0]["ok"], mount[0])
        self.assertIn("not checked", mount[0]["detail"])


class TestShortlist(Master):
    def setUp(self):
        super().setUp()
        self.run_dir = self.master_dir / "_machine" / "runs" / "2026-11-03-strategic-design-ED28"
        self.run_dir.mkdir(parents=True)
        self.cards = [
            {"sourceJobId": "11", "title": "Service Design Intern", "company": "A", "location": "Milan, Italy",
             "url": "https://it.linkedin.com/jobs/view/11", "posted": "2 days ago", "areas": ["Service Design / CX"], "snippet": "x" * 500},
            {"sourceJobId": "22", "title": "UX Intern", "company": "B", "location": "Rome, Italy",
             "url": "https://it.linkedin.com/jobs/view/22", "posted": "1 week ago", "areas": ["Product / UX"]},
        ]
        (self.run_dir / "cards.json").write_text(json.dumps(self.cards), encoding="utf-8")

    def test_cards_are_copied_whole_not_retyped(self):
        out = job_run.shortlist("Strategic design ED.28", self.run_dir.name, ["22"], config_root=self.config)
        self.assertEqual(out["shortlisted"], 1)
        self.assertEqual(json.loads((self.run_dir / "shortlist.json").read_text(encoding="utf-8")), [self.cards[1]])

    def test_an_id_the_run_never_saw_stops_and_writes_nothing(self):
        with self.assertRaises(job_run.Stop) as ctx:
            job_run.shortlist("Strategic design ED.28", self.run_dir.name, ["22", "99"], config_root=self.config)
        self.assertEqual(ctx.exception.code, "card_unknown")
        self.assertIn("99", ctx.exception.detail)
        self.assertFalse((self.run_dir / "shortlist.json").exists())

    def test_the_listing_is_compact_and_keeps_what_a_choice_needs(self):
        rows = job_run.cards("Strategic design ED.28", self.run_dir.name, config_root=self.config)["cards"]
        self.assertEqual([r["id"] for r in rows], ["11", "22"])
        self.assertEqual(rows[0]["areas"], ["Service Design / CX"])
        self.assertNotIn("url", rows[0])
        self.assertLessEqual(len(rows[0]["snippet"]), 200)


class TestRunConfig(Master):
    def test_terms_come_from_a2_and_places_from_a3(self):
        cfg = job_run.run_config(self.resolve(), recency_days=7)
        self.assertEqual(cfg["areas"]["Service Design / CX"], ["service design", "customer journey"])
        self.assertEqual(cfg["locations"], ["Milan", "EU"])
        self.assertEqual(cfg["internshipTerms"], ["stage", "internship"])
        self.assertEqual(cfg["falseFriends"], ["call center", "recupero crediti"])
        self.assertEqual(cfg["admittedLanguages"], ["it", "en"])
        self.assertEqual(cfg["recencyDays"], 7)
        self.assertEqual(cfg["cooldownMinutes"], 20)
        self.assertNotIn("rates", cfg, "the pace is the engine's default, not a per-run guess")

    def test_an_area_a2_rules_out_is_not_searched(self):
        cfg = job_run.run_config(self.resolve(), recency_days=None)
        self.assertNotIn("Old Area", cfg["areas"])
        self.assertNotIn("recencyDays", cfg)

    def test_the_window_covers_the_gap_since_the_last_run_with_overlap(self):
        m = self.resolve()
        self.assertIsNone(job_run.recency_days(m, today="2026-11-20"))
        run = m.dir / "_machine" / "runs" / "2026-11-03-strategic-design-ED28"
        run.mkdir(parents=True)
        self.assertIsNone(job_run.recency_days(m, today="2026-11-20"), "a run with no report did not cover anything")
        (run / "run-report.json").write_text("{}", encoding="utf-8")
        self.assertEqual(job_run.recency_days(m, today="2026-11-20"), 17 + job_run.RECENCY_OVERLAP_DAYS)


class TestCoverage(Master):
    def test_says_which_pairs_were_not_searched_yet(self):
        m = self.resolve()
        cfg = job_run.run_config(m, recency_days=7)
        run = self.tmp / "r"
        run.mkdir()
        (run / "checkpoint.jsonl").write_text(
            json.dumps({"key": "service design stage — Milan — 7", "cards": [card("1"), card("2")]}) + "\n",
            encoding="utf-8",
        )
        cov = job_run.coverage(run, cfg)
        self.assertEqual(cov["planned"], 3 * 2 * 2)
        self.assertEqual(cov["searched"], 1)
        self.assertEqual(len(cov["not_searched"]), 11)
        self.assertEqual(cov["per_area"]["Service Design / CX"], {"searched": 1, "planned": 8, "cards": 2})
        self.assertEqual(cov["per_area"]["Consulting"], {"searched": 0, "planned": 4, "cards": 0})

    def test_the_eu_key_matches_what_the_adapter_writes(self):
        cfg = job_run.run_config(self.resolve(), recency_days=7)
        run = self.tmp / "r"
        run.mkdir()
        (run / "checkpoint.jsonl").write_text(
            json.dumps({"key": "consulting stage — European Union — 7", "cards": []}) + "\n", encoding="utf-8"
        )
        self.assertEqual(job_run.coverage(run, cfg)["searched"], 1)


class TestPrepare(Master):
    def test_runs_the_steps_in_order_and_resumes_an_existing_run(self):
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            joined = " ".join(map(str, cmd))
            if " discover " in joined:
                out = Path(cmd[cmd.index("--out") + 1])
                (out / "run-report.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
                (out / "checkpoint.jsonl").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "{}", "")

        with mock.patch.object(job_run, "run_step", side_effect=fake):
            first = job_run.prepare("Strategic design ED.28", config_root=self.config, today="2026-11-03")
            run = Path(first["run_dir"])
            self.assertEqual(run.name, "2026-11-03-strategic-design-ED28")
            self.assertEqual(json.loads((run / "run.json").read_text(encoding="utf-8"))["masterId"], "strategic-design")
            names = [" ".join(map(str, c)) for c in calls]
            self.assertIn("doctor", names[0])
            self.assertIn("export-history", names[1])
            self.assertIn(" discover ", names[2])
            self.assertNotIn("--resume", names[2])
            calls.clear()
            job_run.prepare("Strategic design ED.28", config_root=self.config, today="2026-11-03")
            self.assertIn("--resume", " ".join(map(str, calls[-1])))

    def test_a_blocked_source_is_reported_not_hidden(self):
        def fake(cmd, **kw):
            if "discover" in cmd:
                out = Path(cmd[cmd.index("--out") + 1])
                (out / "run-report.json").write_text(
                    json.dumps({"sources": [{"id": "linkedin-guest", "status": "blocked", "reason": "5 x HTTP 429"}]}),
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(cmd, 0, "{}", "")

        with mock.patch.object(job_run, "run_step", side_effect=fake):
            out = job_run.prepare("Strategic design ED.28", config_root=self.config, today="2026-11-03")
        self.assertFalse(out["complete"])
        self.assertEqual(out["sources"][0]["status"], "blocked")
        self.assertEqual(out["coverage"]["searched"], 0)


class TestPublish(Master):
    """The real admit, build-tsv, stage and append, on a temp Review.xlsx."""

    def setUp(self):
        super().setUp()
        engine = HERE.parent
        if not (engine / "lib" / "cli.js").exists():
            self.skipTest("build first: lib/cli.js is missing")
        seed = self.tmp / "seed.csv"
        header = list(sync_export.A4_COLUMNS) + ["Company ID"]
        with seed.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(header)
            cells = dict.fromkeys(header, "")
            cells.update({"Company / Outreach Account": "Known Co", "Contact Search Status": "Not started"})
            w.writerow([cells[c] for c in header])
        subprocess.run(
            [sys.executable, str(HERE / "sync_export.py"), "init-review", "--dir", str(self.master_dir), "--history", str(seed)],
            check=True, capture_output=True, text=True,
        )
        self.m = self.resolve()
        self.run_path = self.m.dir / "_machine" / "runs" / "2026-11-03-strategic-design-ED28"
        self.run_path.mkdir(parents=True)
        self.run_dir = self.run_path
        shutil.copy(self.history, self.run_path / "history.csv")
        subprocess.run(
            [sys.executable, str(HERE / "sync_export.py"), "export-history", "--dir", str(self.master_dir), "--out", str(self.run_path / "history.csv")],
            check=True, capture_output=True, text=True,
        )
        (self.run_path / "run-report.json").write_text("{}", encoding="utf-8")
        a, b = card("1"), card("2", company="Paris Co", location="Paris, France")
        self.write_run(
            [a, b],
            [desc(a), desc(b, "You map customer journeys. Français courant obligatoire.")],
            [
                verdict("1"),
                verdict("2", requiredLanguages=["French", "English"], languageRequirement="all", label="escluso", ground="admit"),
            ],
        )

    def publish(self, **kw):
        return job_run.publish(
            "Strategic design ED.28", self.run_path.name, config_root=self.config, today="2026-11-03", **kw
        )

    def review_companies(self):
        from openpyxl import load_workbook

        ws = load_workbook(self.m.dir / "Review.xlsx").worksheets[0]
        return [r[0].value for r in ws.iter_rows(min_row=3) if r[0].value]

    def test_stops_at_the_dry_run_until_confirmed(self):
        before = (self.m.dir / "Review.xlsx").read_bytes()
        out = self.publish()
        self.assertEqual(out["state"], "awaiting_confirmation")
        self.assertEqual(out["would_append"], ["Acme"])
        self.assertEqual(out["excluded_by_admit"], 1)
        self.assertEqual((self.m.dir / "Review.xlsx").read_bytes(), before, "no write before the colleague says yes")
        self.assertTrue((self.m.dir / "Roles.xlsx").exists())

    def test_confirm_appends(self):
        self.publish()
        out = self.publish(confirm=True)
        self.assertEqual(out["state"], "written")
        self.assertEqual(out["appended"], 1)
        self.assertEqual(self.review_companies(), ["Known Co", "Acme"])

    def test_a_refused_build_stops_with_its_reason_and_writes_nothing(self):
        verdicts = json.loads((self.run_path / "verdicts.json").read_text(encoding="utf-8"))
        verdicts[0]["quotes"] = ["invented sentence"]
        (self.run_path / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
        with self.assertRaises(job_run.Stop) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.code, "verdicts_refused")
        self.assertFalse((self.m.dir / "Roles.xlsx").exists())

    def test_a_run_outside_the_master_stops(self):
        with self.assertRaises(job_run.Stop) as ctx:
            job_run.publish("Strategic design ED.28", "../../elsewhere", config_root=self.config, today="2026-11-03")
        self.assertEqual(ctx.exception.code, "run_unknown")

    def test_the_previous_runs_roles_are_carried_automatically(self):
        old = self.m.dir / "_machine" / "runs" / "2026-11-02-strategic-design-ED28" / "final"
        old.mkdir(parents=True)
        header = list(sync_export.A4_COLUMNS)
        cells = dict.fromkeys(header, "")
        cells.update({
            "Company / Outreach Account": "Known Co", "In Italy?": "Yes", "Locations": "1. Rome, Italy",
            "Master-fit Themes": "Consulting", "Matching Job Titles": "1. Earlier Role", "Matching Score": "1. 60",
            "Job Links": "1. https://x.example/earlier", "Role Count": "1", "Curricular Evidence": "To verify — curricular status",
            "Work Modes": "Not stated", "Sources / Portals": "LinkedIn Jobs", "Previously Contacted?": "To verify",
            "Contact Search Status": "New job found", "Outreach Decision": "Review",
            "Notes": "[UPDATE EXISTING ROW] 1. [adiacente] Prima.", "Verification Status": "Portal verified", "Last Checked": "2026-11-02",
        })
        with (old / "run.tsv").open("w", encoding="utf-8") as f:
            f.write("\t".join(header) + "\n" + "\t".join(cells[c] for c in header) + "\n")
        (old / "role-evidence.csv").write_text(
            "url;posted;alternate_urls;search_query\nhttps://x.example/earlier;1 week ago;;q — Italy\n", encoding="utf-8"
        )
        out = self.publish()
        self.assertEqual(out["roles_carried"], 1)
        self.assertEqual(out["roles_out"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
