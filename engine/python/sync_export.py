#!/usr/bin/env python3
"""Publish a search run into a synced SharePoint folder. JSON on stdout.

Ownership is split by FILE, not by sheet:

  Roles.xlsx     machine-owned, read-only for humans, regenerated wholesale
                 every run. Two sheets: `Roles` (one row per role) and
                 `Company Summary` (one row per company, carrying a read-only
                 copy of the human-owned columns).
  Review.xlsx    human-owned. The machine only ever APPENDS new company rows to
                 it, behind guards. Never written by `stage`.
  _machine/      plain-text CSVs + a run manifest. Diffable, no openpyxl.

`Roles.xlsx` is NOT a "pending review file" that someone merges — nothing is
ever merged. It is a rendering. That is what keeps it out of the anti-pattern
where a human must hand-merge a machine file back into the main one.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synced_fs  # noqa: E402
from reconcile import (  # noqa: E402
    _ALT_SPLIT,
    DATE_COLUMNS,
    HUMAN_COLS,
    load_aliases,
    load_canonical,
    match_company,
    norm_company,
    parse_date,
    propose_company_id,
    same_value,
    split_column,
    split_multi,
)

# --------------------------------------------------------------------------
# A4 column contract
# --------------------------------------------------------------------------

# `Brands / Business Units` used to sit second here and in REVIEW_COLUMNS. It
# was removed on 2026-09-23: the only writer was a verbatim copy of this TSV's
# own cell (`explode_roles`), no run ever populated it, and `reconcile.py` never
# knew it existed. It was not dead so much as frozen -- `init-review` fills it
# once from history and nothing updates it again, so it read as "someone forgot"
# in every column of every new row.
A4_COLUMNS = [
    "Company / Outreach Account",
    "In Italy?",
    "Locations",
    "Master-fit Themes",
    "Matching Job Titles",
    # Sits with the other per-role positional columns (Locations, Matching Job
    # Titles, Job Links) because it SHARES THEIR INDEX: the N-th score belongs to
    # the N-th title and the N-th link. That is why it is written `1. 92 | 2. 78`
    # and not as a bare number.
    "Matching Score",
    "Job Links",
    "Role Count",
    "Curricular Evidence",
    "Work Modes",
    "Sources / Portals",
    "Previously Contacted?",
    "Contact Search Status",
    "Contact Name",
    "Contact Role",
    "Contact Email / LinkedIn",
    "Outreach Decision",
    "Notes",
    "Verification Status",
    "Last Checked",
    "First Contact Date",
    "Recall",
]

# Per-role sheet. Restores the retired io.py's original `Role Evidence` design,
# which the flat 22-column projection had destroyed.
ROLE_COLUMNS = [
    "Company / Outreach Account",
    "Job Title",
    "Location",
    "In Italy?",
    "Why It Fits",
    "Primary Job URL",
    "Alternate / Portal URLs",
    "Source / Portal",
    "Work Mode",
    "Curricular Status",
    "Previously Contacted?",
    "Verification Status",
    "Posted / Result Age",
    "Search Query",
    "Date Checked",
]

COMPANY_SUMMARY_COLUMNS = A4_COLUMNS + ["Company ID"]

# --------------------------------------------------------------------------
# The human-facing workbook.
#
# The A4 columns with `Notes` accompanied by `Matching Score` (machine), plus
# `Company ID`, minus the two A4 columns this sheet does not render (see the
# note on REVIEW_COLUMNS below).
#
# `Notes` was SPLIT into `Matching Notes` (machine) + `Reviewer Notes` (human)
# on 2026-09-16, because it was the one column both sides wrote and
# `add_verified.py` fused machine text into whatever a colleague had typed,
# joined with ' | ', irreversibly. The two halves are back in ONE column as of
# 2026-09-23: the colleague asked for a single place to write, `add_verified.py`
# is gone (2026-09-18), and `append` never touches an existing cell.
#
# What replaces the structural guard is a RULE, and it is load-bearing:
#
#     THE MACHINE WRITES `Notes` ONLY WHEN IT CREATES THE ROW.
#     It never writes `Notes` on a row that already exists.
#
# That holds today because of the command set, not by construction -- which is
# exactly how the original fusing got in. `_new_company_values` is the only
# writer and a test asserts it; the cost of losing the rule is the original one,
# and it is unrecoverable.
#
# Built programmatically rather than from a checked-in .xlsx template: the
# column set, number formats and validation live in code, so they appear in a
# diff instead of inside an opaque binary.
# --------------------------------------------------------------------------

# 21 columns. Two A4 columns are deliberately NOT rendered here:
#
#   Previously Contacted?  and  Outreach Decision
#
# Both stay in A4 and both stay in the TSV; this file simply stops showing them.
# "Previously Contacted?" was never typed by a colleague -- its 14 `Yes` come
# from the canonical CSV, and `stage` still copies it into the Company Summary
# sheet, so dropping it from here costs the ability to EDIT it, not the value.
# `Outreach Decision` was a constant in practice (179 `Review`, 1 `No`), and the
# one real decision it carried is better expressed by the status vocabulary:
# "No" is what "Job not suitable" now means.
REVIEW_COLUMNS = [
    "Company / Outreach Account",
    "In Italy?",
    "Locations",
    "Master-fit Themes",
    "Matching Job Titles",
    # Same position as in A4, so the two lists read alike and the machine block
    # stays A-K -- the freeze and the banner below both depend on that block
    # being contiguous, and neither computes it.
    "Matching Score",  # machine
    "Job Links",
    "Role Count",
    "Curricular Evidence",
    "Work Modes",
    "Sources / Portals",
    "Contact Search Status",  # the column the whole row is coloured by
    "Contact Name",
    "Contact Role",
    "Contact Email / LinkedIn",
    "Notes",  # machine-seeded on row creation, then the colleague's
    "Verification Status",
    "Last Checked",
    "First Contact Date",
    "Recall",
    "Company ID",
]

REVIEW_BANNER = (
    "Review file — this one is YOURS. Columns A-K are filled by the machine; "
    "edit Contact Search Status, Notes, Contact * and the dates. "
    "The whole row is coloured by Contact Search Status. "
    "Per-role evidence is in Roles.xlsx. Do not use modern Comments here: "
    "Excel's threaded comments are lost when the machine appends new rows."
)

# Historical `Notes` in the canonical CSV is machine text (every non-empty cell
# carries the [NEW COMPANY]/[pertinente]/Match-score form). It seeds the
# workbook's `Notes` -- on row creation only. The per-role scores now arrive as
# their own A4 column rather than being read back out of this prose.
NOTES_SOURCE_COLUMN = "Notes"

# DATE_COLUMNS is defined in reconcile.py (it is column metadata, and
# reconcile.same_value needs it). This is only the display format.
DATE_NUMBER_FORMAT = "DD/MM/YYYY"

# The colleague-facing status vocabulary, IN ORDER. This tuple is the single
# source of truth: the membership set, the dropdown and the colour rules are all
# derived from it. It used to be declared twice -- an unordered `set` here and an
# ordered list in the dropdown -- so adding a status meant editing both, and only
# one of them was the colour axis.
#
# The order IS the colour axis, in the sense that each value below carries its
# own fill in `_install_color_rules`. `New job found` deliberately has none: it
# is the machine's default, and white is the sheet's own background, so the
# default needs no formula to maintain -- the same reasoning that used to apply
# to `Not started`, which now DOES need a colour because it means a person has
# accepted the row rather than that nobody has looked.
CONTACT_STATUS_ORDER = (
    "New job found",      # machine: a new role was found; nobody has looked yet
    "Job not suitable",   # a person: not a fit, keep the row as a trace
    "Not started",        # a person: accepted, contact search not begun
    "Potential contact",  # a person: fits, referent not yet identified
    "Contact found",      # a person: referent identified and verified
    "Contacted",          # a person: we have made contact
    "Job found",          # a person: the referent confirmed the role is open
)

# Dropdowns, so colleagues pick a value instead of typing one.
VALIDATION = {
    "Contact Search Status": list(CONTACT_STATUS_ORDER),
}

# What a NEW company row starts as, for the human-owned columns. A4: no invented
# contact, no invented prior contact, no guessed date, and the outreach decision
# stays with a person -- which is why `Outreach Decision` is a constant here and
# not something a run supplies.
NEW_COMPANY_DEFAULTS = {
    # The machine's default moved off `Not started` on 2026-09-23. It now says
    # what it actually knows -- a new role was found here -- and leaves
    # `Not started` to mean what only a person can mean: "I have seen this and
    # accepted it, and the contact search has not begun."
    "Contact Search Status": "New job found",
    "Outreach Decision": "Review",
    "Previously Contacted?": "To verify",
}

# Columns that exist per-role now but had NO home in the flat TSV, so no value
# can be recovered for a historical run. They are present so that future runs
# (once the search output carries them) do not lose them again.
# Columns a run cannot express through A4's fixed 22-column TSV. "Alternate /
# Portal URLs" used to be listed here; it is not, because the TSV's own `alt.`
# marker carries it and _role_values now reads it out.
NOT_RECOVERABLE_FROM_FLAT_TSV = {"Posted / Result Age", "Search Query"}

# Columns the `--evidence` sidecar fills. Deliberately NOT the same set as
# NOT_RECOVERABLE_FROM_FLAT_TSV: `Alternate / Portal URLs` IS recoverable from the
# TSV's own `alt.` marker, so it is not "unrecoverable" -- but the sidecar fills
# it too, so a run that supplies evidence and gets nothing has to hear about that
# column as well. One list, so the report cannot disagree with what the sidecar
# is read for.
EVIDENCE_FILLED_COLUMNS = ["Alternate / Portal URLs", "Posted / Result Age", "Search Query"]


# --------------------------------------------------------------------------
# Per-role evidence sidecar
#
# A4's TSV is a fixed 22 columns and one row per COMPANY, so a run has nowhere
# to put a role's posting date, the query that found it, or its portal mirrors.
# Rather than widen the human-owned A4 contract, a run may emit a sidecar keyed
# by job URL and pass it here with --evidence. Without it those columns stay
# empty -- which is how the freshness signal A1 asks for ("verify the
# opportunity is current") got dropped between the card stage and the report.
# --------------------------------------------------------------------------

EVIDENCE_COLUMNS = ["url", "posted", "alternate_urls", "search_query"]

# Written by `cli verify`: one row per employer URL actually probed.
CHECK_COLUMNS = ["url", "label", "status", "reachable", "has_apply", "has_intern_signal", "title", "detail", "elapsed_ms"]


# Tracking parameters, by exact name. Anything absent and not matched by
# _is_tracking below is KEPT. Mirrors TRACKING_PARAMS in engine/src/normalize.ts —
# `test_sync_export.py` asserts the two are equal, the same way it does for
# MULTI_VALUE_SPEC and norm_company.
TRACKING_PARAMS = frozenset({
    "refid",
    "trackingid",
    "trk",
    "trkinternal",
    "originalreferer",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
})


def _is_tracking(key: str) -> bool:
    """Is this query parameter tracking rather than identity?

    `utm` and the whole `utm_*` family are Google's campaign prefixes, matched by
    PREFIX because the family keeps growing (`utm_id`, `utm_source_platform`, …)
    and enumerating it is a list that rots. The bare `utm` counts too — some tools
    emit it — while `utmost` does not, which is why this is not a bare
    `startswith("utm")`.
    """
    k = (key or "").lower()
    return k == "utm" or k.startswith("utm_") or k in TRACKING_PARAMS


def norm_role_url(url: str) -> str:
    """Canonical form of a posting URL. Mirrors `normalizeUrl()` in
    engine/src/normalize.ts, so a run's URL and the TSV's land on the same key.

    String manipulation rather than `urlparse`, deliberately: the value is a
    dictionary key compared against one built in another language, so it has to be
    predictable rather than correct about every RFC detail. Percent-encoding
    differences between Node and Python would be a parity bug nobody would find.

    Keeps the query, minus tracking. `?gh_jid=123` and `?gh_jid=456` are two
    different postings on one path, and dropping the whole query merges them —
    silently, because a merged card leaves no trace.
    """
    s = (url or "").strip().split("#", 1)[0]
    if not s:
        return ""
    head, sep, query = s.partition("?")
    head = head.rstrip("/")
    if not sep:
        return head.lower()
    kept = sorted(p for p in query.split("&") if p and not _is_tracking(p.split("=")[0]))
    return (f"{head}?{'&'.join(kept)}" if kept else head).lower()


def _read_sidecar(path: Path, columns: list[str]) -> dict:
    text = path.read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return {}
    missing = [c for c in columns if c not in header]
    if missing:
        raise StageError("evidence file %s is missing column(s): %s" % (path, ", ".join(missing)))
    idx = {c: header.index(c) for c in columns}
    out = {}
    for row in reader:
        if not row or not row[0].strip():
            continue
        key = norm_role_url(row[0])
        if key:
            out[key] = {c: (row[idx[c]].strip() if idx[c] < len(row) else "") for c in columns}
    return out


def load_evidence(path: str | None) -> dict:
    """Read a run's sidecars into {"roles": {...}, "checks": {...}}, both keyed
    by normalised job URL.

    `path` may be a FILE (a role-evidence sidecar) or a DIRECTORY, in which case
    every sidecar a run wrote is read. A run that only produced employer checks
    still supplies something useful, so neither file is required.
    """
    if not path:
        return {"roles": {}, "checks": {}}
    target = Path(path)
    if target.is_dir():
        roles = target / "role-evidence.csv"
        checks = target / "employer-checks.csv"
        return {
            "roles": _read_sidecar(roles, EVIDENCE_COLUMNS) if roles.exists() else {},
            "checks": _read_sidecar(checks, CHECK_COLUMNS) if checks.exists() else {},
        }
    # A single FILE: work out which sidecar it is from its header rather than
    # assuming. Passing an employer-checks file used to fail with "missing
    # column: posted", which tells the caller nothing about what to do.
    head = target.read_text(encoding="utf-8").split("\n", 1)[0]
    columns = head.split(";")
    if "status" in columns and "has_apply" in columns:
        return {"roles": {}, "checks": _read_sidecar(target, CHECK_COLUMNS)}
    return {"roles": _read_sidecar(target, EVIDENCE_COLUMNS), "checks": {}}

class StageError(Exception):
    pass


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


def read_tsv_source(tsv_path: str | None) -> str:
    """--tsv PATH, raw TSV on stdin, or {"tsv": "..."} on stdin.

    All three work. The JSON form is kept because it was the contract an earlier
    writer used, but `cat run.tsv | sync_export.py stage ...` is the natural
    invocation and must not fail with a JSON parse error.
    """
    if tsv_path:
        return Path(tsv_path).read_text(encoding="utf-8")
    raw = sys.stdin.read()
    if not raw.strip():
        raise StageError('no TSV: pass --tsv PATH, or pipe a TSV / {"tsv": "..."} on stdin')
    # Only treat it as JSON when it announces itself as one.
    if raw.lstrip().startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StageError(f'stdin starts with "{{" but is not valid JSON: {exc}') from exc
        if not isinstance(payload, dict) or "tsv" not in payload:
            raise StageError('JSON on stdin must be an object with a "tsv" field')
        return payload["tsv"]
    return raw


# A4's closed value sets. Validating these catches a whole row shifted sideways,
# which the tab-count rule cannot see: 22 tabs is 22 tabs no matter which column
# the values landed in.
VERIFICATION_PREFIXES = (
    "Employer verified active",
    "Portal verified",
    "Legacy result",
    "Blocked",
    "To verify",
)
# A4's `Outreach Decision` still rides in the TSV (it is column 17 there) and is
# still validated; it is only Review.xlsx that stops rendering it.
DECISION_VALUES = {"Review", "Yes", "No"}

# Membership, DERIVED from the ordered tuple rather than declared a second time.
# The order lives in exactly one place -- see CONTACT_STATUS_ORDER above.
#
# A4 §31 makes this list closed on purpose: it is the axis the whole row is
# coloured by, `stage` refuses every row whose value falls outside it, and the
# red fallback in `_install_color_rules` builds its exclusions from this set. So
# A4's text and CONTACT_STATUS_ORDER must move together.
CONTACT_STATUS_VALUES = set(CONTACT_STATUS_ORDER)

# Statuses that existed before a vocabulary change. Read only by
# `migrate-review`, so an old sheet can be carried onto a new column set without
# a human retyping 180 rows.
#
# This is NOT the place to re-interpret a value that is still live. The census
# in `cmd_migrate_review` skips anything already in CONTACT_STATUS_VALUES
# (`if value in CONTACT_STATUS_VALUES: continue`), so an entry for a live value
# can never fire. `Not started` was the machine default until 2026-09-23 but is
# still a live value; moving its existing rows to `New job found` is
# `--reinterpret`, an explicit flag on the command line, not an entry here.
#
# `Contacted` was REMOVED from this map on 2026-09-23 -- it is a live value now,
# and translating a historical `Contacted` down to `Contact found` would
# silently demote a row a colleague had progressed. The identity entry for
# `Not started` went with it: an identity mapping cannot fire either.
LEGACY_CONTACT_STATUS = {
    "No suitable contact": "Job not suitable",
}


def validate_rows(header: list[str], rows: list[list[str]]) -> list[str]:
    """Check each row's values against the closed sets and types A4 defines for
    those columns.

    Motivated by a real case: `engine/test/fixtures/tsv-shifted-2026-09-11.tsv`
    has all six rows
    shifted +2 from column 16, so `Verification Status` holds 'Review' (a
    decision), `Last Checked` holds the Notes prose, and `First Contact Date`
    holds the verification text. The tab count is a correct 22, so the A4
    tab-count rule passes and the garbage would flow straight into Review.xlsx.
    """
    problems: list[str] = []

    def idx(name: str) -> int | None:
        return header.index(name) if name in header else None

    i_verif, i_dec = idx("Verification Status"), idx("Outreach Decision")
    i_status = idx("Contact Search Status")
    date_idx = {c: idx(c) for c in DATE_COLUMNS if idx(c) is not None}

    for n, cells in enumerate(rows, start=1):
        if len(cells) != len(header):
            continue
        who = cells[0].strip()[:36] or f"row {n}"

        if i_verif is not None and i_verif < len(cells):
            v = cells[i_verif].strip()
            if v and not v.startswith(VERIFICATION_PREFIXES):
                problems.append(
                    f"{who}: Verification Status = {v[:44]!r} is not one of A4's values "
                    f"({', '.join(p.split()[0] for p in VERIFICATION_PREFIXES)})"
                )
        if i_dec is not None and i_dec < len(cells):
            v = cells[i_dec].strip()
            if v and v not in DECISION_VALUES:
                problems.append(f"{who}: Outreach Decision = {v[:30]!r} is not in {sorted(DECISION_VALUES)}")
        if i_status is not None and i_status < len(cells):
            v = cells[i_status].strip()
            if v and v not in CONTACT_STATUS_VALUES:
                problems.append(f"{who}: Contact Search Status = {v[:30]!r} is not in {sorted(CONTACT_STATUS_VALUES)}")
        for col, ci in date_idx.items():
            if ci < len(cells):
                v = cells[ci].strip()
                if v and parse_date(v) is None:
                    problems.append(f"{who}: {col} = {v[:40]!r} is not a date")
    return problems


def workbook_problems(header: list, rows: list[list]) -> list[str]:
    """Closed-set columns in the workbook holding a value outside their set.

    `Contact Search Status` ONLY, and that restriction is the point.

    `Contact Search Status` is structural: it is the axis the whole row is
    coloured by, A4 calls its list closed *"di proposito"*, and the dropdown
    enforces it on entry. A value outside it is a fault, and the wording here is
    deliberately `validate_rows`' wording so one fault reads the same from `stage`
    and from `doctor`.

    `Verification Status` is A4's closed set too — but for what a RUN produces.
    `stage` enforces it on the TSV, which is the output contract. In the workbook
    the column is a REFERENCE: the workflow does not select, group or filter on
    it, and Talent Placement has said so explicitly. Checking it here reported 71
    of 164 rows as failures while nothing was wrong, and a check that is
    permanently red is how its exit code — the signal that says "do not run the
    publish commands" — becomes noise. The 71 rows were left as they are, on
    purpose; see YUW-60.

    Empty cells are fine and never reported: an empty cell says "not stated",
    which A4 allows. `rows` are raw cell values; values are stringified here.
    """
    checks = (
        ("Contact Search Status", lambda v: v in CONTACT_STATUS_VALUES, str(sorted(CONTACT_STATUS_VALUES))),
    )
    out: list[str] = []
    for name, ok, allowed in checks:
        if name not in header:
            continue
        ci = header.index(name)
        for cells in rows:
            if ci >= len(cells) or cells[ci] in (None, ""):
                continue
            value = str(cells[ci]).strip()
            if value and not ok(value):
                who = str(cells[0]).strip()[:36] if cells else ""
                out.append(f"{who}: {name} = {value[:40]!r} is not one of {allowed}")
    return out


def parse_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse the A4 TSV. Enforces A4's tab-count rule.

    A4: "verificare che ogni riga abbia esattamente lo stesso numero di Tab
    dell'header; ... se contiene un Tab la riga è invalida". This is not
    theoretical — two rows of the canonical CSV are already column-shifted by
    +1 from `Verification Status` onward (Bain & Company, Moncler), which is
    exactly what a mis-pasted row looks like. Refuse rather than propagate.
    """
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        raise StageError("TSV is empty")
    header = lines[0].split("\t")
    if len(header) != len(A4_COLUMNS):
        raise StageError(f"header has {len(header)} columns, expected {len(A4_COLUMNS)}")

    rows: list[list[str]] = []
    bad: list[str] = []
    for i, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(header):
            bad.append(f"line {i}: {len(cells)} cols (expected {len(header)}) — {cells[0][:40]!r}")
            continue
        if not cells[0].strip() or cells[0].strip().startswith("["):
            continue
        rows.append(cells)
    if bad:
        raise StageError(
            "TSV has rows with the wrong number of tabs (A4 forbids this). Give every row the "
            "same number of tabs as the header, using empty fields for columns with no value "
            "(do not omit trailing tabs, and do not insert blanks mid-row):\n  "
            + "\n  ".join(bad[:10])
        )
    return header, rows

# --------------------------------------------------------------------------
# Explode one row per company -> one row per role
# --------------------------------------------------------------------------


# Job Links carries a per-role "alt." mirror on the SAME entry as its primary.
# Expanded (the default for that column, so `split_column` callers see both
# URLs), the mirror becomes a list item of its own, and any positional read of
# the list then hands every role after it someone else's URL.
_LINKS_NO_ALT = {"semicolon": False, "numbered": True}


def _job_link_entries(cells: list[str]) -> list[str]:
    """The per-role Job Links entries, with each `alt.` mirror still attached."""
    return split_multi(cells[A4_COLUMNS.index("Job Links")], _LINKS_NO_ALT)


def _split_alt(entry: str) -> tuple[str, list[str]]:
    """(primary, alternates) for one role's Job Links entry."""
    parts = [p.strip() for p in _ALT_SPLIT.split(entry) if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def _role_values(cells: list[str], index: int, count: int) -> dict[str, str]:
    """Pick the index-th value of the columns that are per-role in the flat TSV.

    `Matching Job Titles`, `Job Links` and `Locations` share one positional
    index (A4: "mantenendo lo stesso indice"). Where a shorter list cannot
    supply the index, fall back to the first entry rather than inventing a
    value — and never fabricate a URL.

    Job Links is indexed WITHOUT expanding `alt.`, because the index addresses
    a ROLE. With the expansion on, a company whose first role has a mirror
    pushes every later role onto the wrong URL — the second role gets the
    first's mirror and so on. Verified against the pre-fix code:

        role 1 "Global CRM Internship"  -> job/20457            (right)
        role 2 "Market Insights Intern" -> 4467208467, role 1's mirror  (wrong)
        role 3 "Business Planning"      -> job/21152,  role 2's employer URL (wrong)

    Colleagues open `Roles.xlsx` to reach one specific posting, so a wrong URL
    there sends them to the wrong job.
    """
    def at(column: str) -> list[str]:
        return split_column(cells[A4_COLUMNS.index(column)], column)

    def pick(column: str) -> str:
        items = at(column)
        if not items:
            return ""
        return items[index] if index < len(items) else (items[0] if count else "")

    entries = _job_link_entries(cells)
    if not entries:
        primary, alternates = "", []
    else:
        entry = entries[index] if index < len(entries) else (entries[0] if count else "")
        primary, alternates = _split_alt(entry)

    return {
        "Job Title": pick("Matching Job Titles"),
        "Location": pick("Locations"),
        "Primary Job URL": primary,
        "Alternate / Portal URLs": "; ".join(alternates),
    }


def explode_roles(
    rows: list[list[str]], evidence: dict | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (role_rows, company_rows).

    `evidence` is {"roles": {...}, "checks": {...}} keyed by normalised job URL
    -- see load_evidence. Columns it cannot supply stay empty rather than being
    guessed at.
    """
    evidence = evidence or {}
    role_ev = evidence.get("roles", {})
    checks = evidence.get("checks", {})
    role_rows: list[dict[str, str]] = []
    company_rows: list[dict[str, str]] = []

    for cells in rows:
        col = lambda name: cells[A4_COLUMNS.index(name)].strip()  # noqa: E731
        company = col("Company / Outreach Account")
        titles = split_column(col("Matching Job Titles"), "Matching Job Titles")
        count = len(titles)

        company_rows.append({c: cells[A4_COLUMNS.index(c)].strip() for c in A4_COLUMNS})

        if count == 0:
            # A company with no parsable role still belongs in the summary.
            continue

        for i in range(count):
            rv = _role_values(cells, i, count)
            key = norm_role_url(rv["Primary Job URL"])
            ev = role_ev.get(key, {})
            check = checks.get(key, {})
            role_rows.append(
                {
                    "Company / Outreach Account": company,
                    "Job Title": rv["Job Title"],
                    "Location": rv["Location"],
                    "In Italy?": col("In Italy?"),
                    "Why It Fits": col("Master-fit Themes"),
                    "Primary Job URL": rv["Primary Job URL"],
                    # Recovered from the TSV's own `alt.` marker, so this is no
                    # longer one of the columns a live run cannot supply.
                    "Alternate / Portal URLs": ev.get("alternate_urls") or rv["Alternate / Portal URLs"],
                    "Source / Portal": col("Sources / Portals"),
                    "Work Mode": col("Work Modes"),
                    "Curricular Status": col("Curricular Evidence"),
                    "Previously Contacted?": col("Previously Contacted?"),
                    # Per-role when the run actually probed THIS url, otherwise the
                    # company-level value. Never invented: an unprobed role keeps the
                    # company answer rather than inheriting a neighbour's.
                    "Verification Status": check.get("status") or col("Verification Status"),
                    "Posted / Result Age": ev.get("posted", ""),
                    "Search Query": ev.get("search_query", ""),
                    "Date Checked": col("Last Checked"),
                }
            )
    return role_rows, company_rows


def evidence_report(role_rows: list[dict[str, str]], evidence: dict, supplied: str | None) -> dict:
    """What the evidence join actually achieved, as a property of the rows.

    The three columns below are the ones a flat 22-column TSV cannot carry, so
    they are what `--evidence` exists to fill. Whether it filled them is a
    property of the data, not of the command line, and the difference is not
    academic: a run that followed A1 and wrote the EMPLOYER url into the TSV --
    A1 prefers it over the portal url -- joins on nothing, because the sidecar is
    keyed by the url of the posting the run actually saw. That run used to
    receive `columns_without_source: []`, a manifest declaring nothing missing
    while all three columns sat empty.

    Naming the sample URLs is what makes the failure diagnosable rather than
    merely reported: the operator can see that the two URL families differ.
    """
    cols = EVIDENCE_FILLED_COLUMNS
    total = len(role_rows)
    sidecar_rows = len(evidence.get("roles", {}))
    filled = {c: sum(1 for r in role_rows if (r.get(c) or "").strip()) for c in cols}

    out: dict = {
        "source": supplied,
        "roles": total,
        "sidecar_rows": sidecar_rows,
        "filled": {c: f"{filled[c]}/{total}" for c in cols},
        "without_source": sorted(c for c in cols if total and not filled[c]),
    }
    if supplied and total and sidecar_rows and not any(filled.values()):
        out["note"] = (
            "no role joined the sidecar; it is keyed by the portal URL, so a TSV "
            "carrying the employer URL (A1's preference) cannot match it"
        )
        out["sample_urls"] = [(r.get("Primary Job URL") or "").strip() for r in role_rows[:5]]
    return out


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])


def _write_roles_workbook(
    path: Path,
    role_rows: list[dict[str, str]],
    company_rows: list[dict[str, str]],
) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    banner_font = Font(bold=True, color="FFFFFF")
    banner_fill = PatternFill("solid", fgColor="C00000")
    head_font = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="F2F2F2")

    wb = Workbook()

    def add_sheet(ws, columns, rows, note):
        ws.cell(1, 1, note).font = banner_font
        ws.cell(1, 1).fill = banner_fill
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(columns), 4))
        for c, name in enumerate(columns, start=1):
            cell = ws.cell(2, c, name)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            ws.column_dimensions[get_column_letter(c)].width = min(max(len(name) + 2, 12), 42)
        for r, row in enumerate(rows, start=3):
            for c, name in enumerate(columns, start=1):
                ws.cell(r, c, row.get(name, ""))
        ws.freeze_panes = "A3"
        if rows:
            ws.auto_filter.ref = f"A2:{get_column_letter(len(columns))}{len(rows) + 2}"

    ws1 = wb.active
    ws1.title = "Roles"
    add_sheet(
        ws1,
        ROLE_COLUMNS,
        role_rows,
        "GENERATED by sync_export.py — edits are lost on the next run. "
        "Review and record decisions in Review.xlsx.",
    )

    ws2 = wb.create_sheet("Company Summary")
    add_sheet(
        ws2,
        COMPANY_SUMMARY_COLUMNS,
        company_rows,
        "GENERATED — read-only. Human-owned columns are copied here for "
        "convenience; edit them in Review.xlsx, not here.",
    )

    wb.save(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    report: dict = {"dir": str(d), "checks": [], "ok": True}

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    check("dir exists", d.exists(), str(d))
    if not d.exists():
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    check("dir is a directory", d.is_dir())
    check("dir writable", os.access(d, os.W_OK))

    # Is this actually on a OneDrive File Provider mount? Guessing wrong would
    # silently write somewhere colleagues cannot see.
    try:
        import subprocess

        out = subprocess.run(
            ["xattr", "-p", "com.apple.file-provider-domain-id", str(d)],
            capture_output=True,
            text=True,
        )
        if out.returncode == 0:
            domain = out.stdout.strip()
            on_mount = "OneDrive" in domain or "SharePoint" in domain
            detail = domain
        else:
            # The attribute is absent, which is the normal answer for any path
            # outside a sync domain — /tmp included.
            on_mount = False
            detail = out.stderr.strip() or "no file-provider xattr (not inside a sync domain)"
        check("on a OneDrive File Provider mount", on_mount, detail)
    except FileNotFoundError:
        check("on a OneDrive File Provider mount", False, "xattr command not available")
    except Exception as exc:  # noqa: BLE001
        check("on a OneDrive File Provider mount", False, f"could not determine: {exc}")

    for name in ("Roles.xlsx", "Review.xlsx"):
        target = d / name
        if target.exists():
            info = synced_fs.describe(target)
            check(f"{name} not dataless", not info.get("dataless"), info.get("mtime", ""))
            check(f"{name} not locked by Excel", info.get("excel_lock") is None, info.get("excel_lock") or "")
        else:
            check(f"{name} (absent, will be created)", True, "")

    # Two different questions about the same cells, answered from ONE pass:
    #
    #   * a CF formula like `$W2<=TODAY()` compares STRINGS against "03/09/2026"
    #     and silently returns the wrong answer while the cell still looks right,
    #     so a date column must hold a real date — not text that merely parses;
    #   * a closed-set column must hold a value from its set. `stage` enforces
    #     that on TSV rows; nothing enforced it here, which is how the live
    #     workbook came to hold 105 rows whose `Verification Status` is prose.
    #
    # One `iter_rows` for both. A read-only sheet is a STREAM, so the per-column
    # re-iteration this replaced happened to work — which is not the same as
    # being supported.
    review = d / "Review.xlsx"
    if review.exists() and not synced_fs.is_dataless(review):
        try:
            from openpyxl import load_workbook

            wb = load_workbook(review, read_only=True, data_only=True)
            ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
            stream = ws.iter_rows(min_row=2, values_only=True)
            header = list(next(stream))
            body = [list(r) for r in stream]
            wb.close()

            for col in DATE_COLUMNS:
                if col not in header:
                    continue
                ci = header.index(col)
                bad = [
                    str(r[0])[:28]
                    for r in body
                    if ci < len(r) and r[ci] not in (None, "") and not isinstance(r[ci], datetime)
                ]
                check(f"Review.xlsx '{col}' holds dates", not bad, f"non-date in: {bad[:4]}" if bad else "")

            problems = workbook_problems(header, body)
            check(
                "Review.xlsx closed-set columns hold A4's values",
                not problems,
                f"{len(problems)} value(s): " + " | ".join(problems[:3]) if problems else "",
            )
        except Exception as exc:  # noqa: BLE001
            check("Review.xlsx readable", False, str(exc)[:120])

    report["dirs"] = {"_machine": str(d / "_machine"), "backups": str(d / "_machine" / "backups")}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_stage(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    synced_fs.ensure_dir(d)
    machine = synced_fs.ensure_dir(d / "_machine")

    text = read_tsv_source(args.tsv)
    header, rows = parse_tsv(text)
    evidence = load_evidence(args.evidence)
    role_rows, company_rows = explode_roles(rows, evidence)

    # Human-owned columns are copied in read-only from canonical history so
    # colleagues see one joined view without the machine touching their file.
    canon = load_canonical(args.history) if args.history else None
    if canon is not None:
        canon_by_name: dict[str, list] = {}
        for r in canon.rows:
            canon_by_name.setdefault(r.norm_name, []).append(r)
        for cr in company_rows:
            from reconcile import norm_company

            hits = canon_by_name.get(norm_company(cr["Company / Outreach Account"]), [])
            cr["Company ID"] = hits[0].company_id if hits and len(hits) == 1 else ""
            for hc in HUMAN_COLS:
                # Every human column is seeded from history when the run supplied
                # nothing. `Notes` used to be skipped here, when it was a column
                # the canonical did not have at all (`Reviewer Notes`); it is an
                # A4 column now, so the canonical carries it and the skip went.
                if hc in cr and not cr.get(hc) and hits and len(hits) == 1:
                    cr[hc] = hits[0].get(hc)
        for cr in company_rows:
            cr.setdefault("Company ID", "")

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    roles_csv = machine / f"roles-{run_id}.csv"
    companies_csv = machine / f"companies-{run_id}.csv"
    roles_xlsx = d / "Roles.xlsx"

    # Values must be plausible for their columns, not merely the right count.
    problems = validate_rows(header, rows)
    if problems and not args.lenient:
        raise StageError(
            f"{len(problems)} value(s) do not fit their column. This usually means the row is "
            "shifted sideways, which the tab-count rule cannot detect. Fix the source TSV, "
            "or pass --lenient to stage it anyway (the problems are then recorded in the manifest):\n  "
            + "\n  ".join(problems[:8])
        )

    evidence_path = getattr(args, "evidence", None)
    join = evidence_report(role_rows, evidence, evidence_path)
    summary = {
        "run_id": run_id,
        "tsv": args.tsv or "<stdin>",
        "validation_problems": problems,
        "companies_in": len(rows),
        "roles_out": len(role_rows),
        "companies_out": len(company_rows),
        "role_columns": len(ROLE_COLUMNS),
        # Both derived from the rows, not from whether the flag was passed.
        "columns_without_source": join["without_source"],
        "evidence_join": join,
        "evidence": evidence_path,
        "target": str(roles_xlsx),
        "never_touched": str(d / "Review.xlsx"),
    }

    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    _write_csv(roles_csv, ROLE_COLUMNS, role_rows)
    # `Company ID` rides along even though it is not an A4 column: `stage` already
    # resolves it above, and `append` reads it back when giving a new company an
    # identity. Without it here that lookup could never hit, and the id would be
    # recomputed rather than carried.
    _write_csv(companies_csv, A4_COLUMNS + ["Company ID"], company_rows)
    synced_fs.write_atomically(
        roles_xlsx,
        lambda tmp: _write_roles_workbook(tmp, role_rows, company_rows),
        allow_hydrate=args.allow_hydrate,
        backup_dir=machine / "backups",
    )

    summary["artifacts"] = {
        "Roles.xlsx": _sha256(roles_xlsx),
        f"_machine/roles-{run_id}.csv": _sha256(roles_csv),
        f"_machine/companies-{run_id}.csv": _sha256(companies_csv),
    }
    summary["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (machine / "last-run.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _write_csv_rows(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


# Named for what it now is. The string is only ever printed as JSON -- it is not
# stored in the workbook -- so pointing it at the closed proposal file was
# misinformation with no upside.
COLOR_RULES_SPEC = "A4 · Contatti e decisioni (Contact Search Status, 5 valori) — colore per riga"

# Range padding: rules must still apply to rows a colleague inserts later.
CF_RANGE_ROWS = 2000


def _install_color_rules(ws, columns: list[str]) -> list[str]:
    """Install the conditional-formatting rulesets. Idempotent: existing rules
    on these ranges are cleared first, so re-running after a rule change is safe.

    Conditional formatting rather than literal fills, deliberately. The machine
    then never writes a STYLE into the colleague's file — its entire recurring
    footprint is "append values into empty rows". It also means the colour
    updates the instant a colleague changes a dropdown, with no script run.

    Only classic rule types are used. openpyxl's worksheet `extLst` extension
    passthrough is dropped on save, which rules out x14-extended CF.
    """
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    def ref(col_name: str, row: int) -> str:
        letter = get_column_letter(columns.index(col_name) + 1)
        return f"${letter}{row}"

    applied: list[str] = []

    def clear(col_name: str) -> None:
        letter = get_column_letter(columns.index(col_name) + 1)
        rng = f"{letter}2:{letter}{CF_RANGE_ROWS}"
        ws.conditional_formatting._cf_rules.pop(rng, None)
        return rng

    # The whole row is coloured by Contact Search Status. One rule per
    # coloured status, one shared anchor cell, nothing nested: the previous
    # ruleset included a three-branch OR that detected a status/date
    # contradiction, and simplifying it was an explicit ask.
    #
    # `New job found` gets no rule on purpose -- white is the sheet's own
    # background, and it is the MACHINE's default, so the default needs no
    # formula to maintain. That was `Not started`'s role until 2026-09-23;
    # `Not started` now means a person has accepted the row, which is a state
    # worth seeing, so it gained a fill instead of keeping the default's.
    #
    # Six of the seven values carry a fill; the seventh is the default. The
    # order here is the colour order and CONTACT_STATUS_ORDER is the vocabulary
    # order -- `test_every_status_except_the_default_has_a_colour` keeps them in
    # step, because nothing in the code derives one from the other.
    status_col = ref("Contact Search Status", 3)
    status_letter = get_column_letter(columns.index("Contact Search Status") + 1)
    row_range = f"A3:{get_column_letter(len(columns))}{CF_RANGE_ROWS}"
    ws.conditional_formatting._cf_rules.pop(row_range, None)

    STATUS_FILLS = [
        ("Job not suitable", "D9D9D9", "grey"),
        ("Not started", "E4DFEC", "lilac"),
        ("Potential contact", "FFE699", "yellow"),
        ("Contact found", "DDEBF7", "blue"),
        ("Contacted", "BDD7EE", "deeper blue"),
        ("Job found", "C6EFCE", "green"),
    ]
    for value, colour, name in STATUS_FILLS:
        ws.conditional_formatting.add(
            row_range,
            FormulaRule(
                formula=[f'${status_letter}3="{value}"'],
                fill=PatternFill("solid", bgColor=colour),
                stopIfTrue=False,
            ),
        )

    # The fallback, added last so the exact-match rules above keep priority.
    #
    # Every rule above is exact-equality, so a value matching none of them fell
    # through to the sheet's own white -- the same white a "New job found" row
    # has, which is the machine's default and therefore the most common row.
    # A status that was mistyped, pasted in (Excel's list validation does not run
    # on paste), or written by an older tool therefore read as untouched. This
    # makes it loud instead.
    #
    # The exclusion list is built from CONTACT_STATUS_VALUES rather than written
    # out, so adding a status to the vocabulary cannot silently start reddening
    # it. Empty is exempt on purpose: A4 uses an empty status for "not stated",
    # and the fallback must not paint a row nobody has touched.
    exclusions = "".join(f'${status_letter}3<>"{v}",' for v in sorted(CONTACT_STATUS_VALUES))
    ws.conditional_formatting.add(
        row_range,
        FormulaRule(
            formula=[f'AND(${status_letter}3<>"",{exclusions.rstrip(",")})'],
            fill=PatternFill("solid", bgColor="FFC7CE"),
            stopIfTrue=False,
        ),
    )
    applied.append(
        "Contact Search Status: whole row A..{last} by status -- "
        "Job not suitable=grey, Potential contact=yellow, Contact found=blue, "
        "Job found=green, Not started=no fill, anything else=red  [{rng}]".format(
            last=get_column_letter(len(columns)), rng=row_range
        )
    )

    # Recall — due vs scheduled. Unchanged.
    rng = clear("Recall")
    w = ref("Recall", 2)
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[f'AND({w}<>"",{w}<=TODAY())'], fill=PatternFill("solid", bgColor="FFC000"), stopIfTrue=False),
    )
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[f'AND({w}<>"",{w}>TODAY())'], fill=PatternFill("solid", bgColor="9BD9D9"), stopIfTrue=False),
    )
    applied.append(f"Recall: due=orange, scheduled=teal  [{rng}]")

    return applied


def _write_review_header(ws) -> None:
    """Banner, header row and column widths.

    Shared by `init-review` and `migrate-review` on purpose: two copies of this
    block would drift, and a migrated file that does not look like a fresh one
    is how a colleague concludes the machine broke something.
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ncols = len(REVIEW_COLUMNS)
    ws.cell(1, 1, REVIEW_BANNER).font = Font(bold=True, color="FFFFFF")
    ws.cell(1, 1).fill = PatternFill("solid", fgColor="C00000")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=min(ncols, 10))
    ws.row_dimensions[1].height = 30

    for c, name in enumerate(REVIEW_COLUMNS, start=1):
        cell = ws.cell(2, c, name)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="F2F2F2")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = min(max(len(name) + 2, 12), 38)


def _apply_review_validation(ws) -> None:
    """Dropdowns, so colleagues pick a value instead of typing one.

    `showErrorMessage=True` is load-bearing, not decoration. openpyxl defaults it
    to False, and with that default Excel ACCEPTS an out-of-list entry and says
    nothing — the cell merely gets no dropdown suggestion. Measured against
    openpyxl 3.1.5. Without it the sheet looked protected and was not, and an
    unrecognised value is invisible in a second way too: the conditional
    formatting matches exactly, so a value outside the vocabulary matches no rule
    and the row stays white, which is what `Not started` looks like.

    (`showDropDown=False` reads backwards but is correct: in OOXML
    `showDropDown="1"` means HIDE the in-cell dropdown.)
    """
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    for col_name, options in VALIDATION.items():
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(options) + '"',
            allow_blank=True,
            showDropDown=False,
            showErrorMessage=True,
            errorStyle="stop",
            errorTitle="Valore non ammesso",
            error="Scegliete un valore dal menu a tendina: la riga si colora in base a questo campo.",
        )
        ws.add_data_validation(dv)
        letter = get_column_letter(REVIEW_COLUMNS.index(col_name) + 1)
        dv.add(f"{letter}3:{letter}{CF_RANGE_ROWS}")

def _build_review_workbook(path: Path, canon) -> int:
    """Create Review.xlsx, seeded from canonical history. Returns rows written."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Review"
    ncols = len(REVIEW_COLUMNS)
    _write_review_header(ws)

    row = 3
    for cr in canon.rows:
        for c, name in enumerate(REVIEW_COLUMNS, start=1):
            if name == "Matching Score":
                # A canonical history written before 2026-09-23 carries the score
                # inline in `Notes`, so seeding a fresh workbook means splitting
                # it out -- otherwise the score column would be born empty and
                # the note would go on saying the same thing twice.
                score_cell, _ = split_scores_from_notes(cr.get(NOTES_SOURCE_COLUMN))
                value: object = score_cell
            elif name == "Notes":
                _, value = split_scores_from_notes(cr.get(NOTES_SOURCE_COLUMN))
            elif name in DATE_COLUMNS:
                # Real dates, not text — see DATE_NUMBER_FORMAT's comment.
                parsed = parse_date(cr.get(name))
                value = parsed if parsed is not None else cr.get(name)
                if parsed is not None:
                    ws.cell(row, c).number_format = DATE_NUMBER_FORMAT
            elif name == "Contact Search Status":
                # The canonical being seeded from can still hold a superseded value
                # (`Contacted`, `No suitable contact`) — the shipped history fixture
                # carries one. `migrate-review` translates those on a live sheet;
                # without the same step here a freshly created file is born outside
                # the vocabulary, and `doctor` then fails on the very first run —
                # which is how a check gets learned as noise and ignored.
                raw = cr.get(name)
                value = LEGACY_CONTACT_STATUS.get(raw.strip(), raw)
            else:
                value = cr.get(name)
            ws.cell(row, c, value if value not in (None, "") else None)
        row += 1

    _apply_review_validation(ws)

    ws.freeze_panes = "C3"
    ws.auto_filter.ref = f"A2:{get_column_letter(ncols)}{max(row - 1, 2)}"
    wb.save(path)
    return row - 3


def find_bad_dates(canon) -> list[dict]:
    """Non-empty values in a date column that do not parse as a date.

    These are not parser bugs. In the canonical CSV exactly two turn up, and
    both are the known column-shift corruption from a bad paste:
    `Last Checked = 'Brands / Business Units'` (header text landed in a data
    cell, Bain & Company) and `Last Checked = 'Dentsu Creative'` (the next row's
    company name, Moncler). Reported, never silently repaired or dropped --
    a visible wrong value beats a silent conversion.
    """
    out: list[dict] = []
    for r in canon.rows:
        for col in DATE_COLUMNS:
            v = r.get(col).strip()
            if v and parse_date(v) is None:
                out.append({"row": r.index, "company": r.company, "column": col, "value": v})
    return out


def cmd_init_review(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    target = d / "Review.xlsx"
    if target.exists() and not args.force:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "exists",
                    "error": f"{target} already exists. Refusing to overwrite: it holds colleague edits. "
                    "Use --force only if you have a backup and intend to discard them.",
                },
                ensure_ascii=False,
            )
        )
        return 1

    synced_fs.ensure_dir(d)
    canon = load_canonical(args.history)
    bad_dates = find_bad_dates(canon)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "target": str(target),
                    "columns": len(REVIEW_COLUMNS),
                    "rows_to_seed": len(canon.rows),
                    "date_columns": DATE_COLUMNS,
                    "dropdowns": {k: v for k, v in VALIDATION.items()},
                    "seeded_from": str(args.history),
                    "unparseable_dates": bad_dates,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    synced_fs.write_atomically(
        target,
        lambda tmp: _build_review_workbook(tmp, canon),
        allow_hydrate=args.allow_hydrate,
        backup_dir=d / "_machine" / "backups",
    )

    summary = {
        "ok": True,
        "created": str(target),
        "columns": len(REVIEW_COLUMNS),
        "rows_seeded": len(canon.rows),
        "next": "run `color` to install the status rules",
    }
    if bad_dates:
        summary["warning"] = (
            f"{len(bad_dates)} value(s) in a date column are not dates and were written as text. "
            "These are the known paste column-shift; fix the source rows in the canonical CSV."
        )
        summary["unparseable_dates"] = bad_dates
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_export_history(args: argparse.Namespace) -> int:
    """Write Review.xlsx out as a semicolon CSV the search run can read.

    Why this exists: `Review.xlsx` is the company record that is actually
    maintained — it has the companies colleagues have decided about, and on
    2026-09-18 it held 180 against the canonical CSV's 118, because nothing had
    run `pull` for weeks. The search run must dedup against what is current, and
    the TypeScript CLI cannot read xlsx (the engine has no dependencies). So the
    Python side, which already knows how to read the workbook, converts it.

    This is the same `_review_as_canonical` the `append` guard uses, so there is
    one answer to "which companies do we know" rather than two that drift.

    Columns the workbook does not render come out empty rather than invented:
    `Previously Contacted?` and `Outreach Decision` are not in Review.xlsx.
    """
    d = Path(args.dir)
    target = d / "Review.xlsx"
    if not target.exists():
        print(json.dumps({"ok": False, "error": f"{target} does not exist"}, ensure_ascii=False))
        return 2

    from openpyxl import load_workbook

    wb = load_workbook(target, read_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    canon = _review_as_canonical(ws)

    header = A4_COLUMNS + ["Company ID"]
    rows: list[list[str]] = []
    for cr in canon.rows:
        out: list[str] = []
        for col in A4_COLUMNS:
            # No renaming: Review.xlsx and A4 both call the column `Notes`, and
            # `Matching Score` exists under the same name on both sides.
            out.append(cr.get(col))
        out.append(cr.get("Company ID"))
        rows.append(out)

    dest = Path(args.out) if args.out else d / "_machine" / "review-history.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_csv_rows(dest, header, rows)

    with_roles = sum(1 for r in rows if r[A4_COLUMNS.index("Matching Job Titles")].strip())
    print(
        json.dumps(
            {
                "ok": True,
                "source": str(target),
                "out": str(dest),
                "companies": len(rows),
                "with_roles": with_roles,
                "note": "feed this to `discover --history` so the run dedups against what colleagues maintain",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _parse_reinterpret(rules: list[str]) -> dict[str, str]:
    """Parse `--reinterpret OLD=NEW` pairs, refusing anything that cannot land.

    The escape hatch for a value that CHANGED MEANING but kept its name.
    `LEGACY_CONTACT_STATUS` cannot carry that case, and the reason is structural:
    the census in `cmd_migrate_review` skips any value already in
    `CONTACT_STATUS_VALUES`, so a live value never reaches the translation
    branch. `Not started` moved from "the machine's default" to "a person has
    taken this row on" on 2026-09-23, and every row written before that day means
    the first thing.

    Refused rather than guessed at, on the same principle as `unmapped_status`:
    re-reading a colleague-editable column is a decision somebody makes on the
    command line, not one this tool makes for them.
    """
    out: dict[str, str] = {}
    for rule in rules:
        old, sep, new = rule.partition("=")
        old, new = old.strip(), new.strip()
        if not sep or not old or not new:
            raise StageError(f"--reinterpret expects OLD=NEW, got {rule!r}")
        if new not in CONTACT_STATUS_VALUES:
            raise StageError(
                f"--reinterpret target {new!r} is not in the vocabulary: {', '.join(CONTACT_STATUS_ORDER)}"
            )
        if old not in CONTACT_STATUS_VALUES and old not in LEGACY_CONTACT_STATUS:
            raise StageError(f"--reinterpret source {old!r} is neither a current value nor a known-legacy one")
        if old == new:
            raise StageError(f"--reinterpret {rule!r} maps a value to itself")
        out[old] = new
    return out


def _migrated_notes(row: list, old_header: list[str]) -> tuple[str, str, bool]:
    """(score_cell, note_cell, merged) for one row of the sheet being rebuilt.

    The old sheet may carry the split pair (`Matching Notes` + `Reviewer Notes`),
    a single `Notes` (a sheet older than that split), or neither. Three things
    happen here, and they are why this is a function rather than three lines in
    the loop:

      * the machine half goes through `split_scores_from_notes`, so an inline
        `Match score: NN/100` lands in the score column instead of being thrown
        away along with the prose;
      * the human half is APPENDED to the note and never allowed to overwrite
        it: a colleague's sentence is the one thing in this sheet that cannot be
        regenerated;
      * when both halves exist the join is MARKED -- this is the fusion the
        2026-09-16 split existed to prevent, done once, on one row, with the
        reader still able to tell which sentence is whose.
    """

    def get(name: str):
        return row[old_header.index(name)] if name in old_header else None

    machine = get("Matching Notes") or get("Notes") or ""
    human = get("Reviewer Notes") or ""
    score_cell, note = split_scores_from_notes(str(machine) if machine else "")
    merged = False
    if str(human).strip():
        human_text = str(human).strip()
        if note.strip():
            note = f"{note}\n— nota della persona ({date.today().isoformat()}): {human_text}"
            merged = True
        else:
            note = human_text
    return score_cell, note, merged


def cmd_migrate_review(args: argparse.Namespace) -> int:
    """Rebuild Review.xlsx onto the current REVIEW_COLUMNS.

    Needed because `init-review` refuses to overwrite a file holding colleague
    edits, and `append` writes by looking each column up in the sheet's OWN
    row-2 header -- so a renamed or newly added column gets no value written
    into it at all, while a column that has left the schema keeps its old values
    sitting in a sheet that the readers then refuse.

    Every cell is carried across BY COLUMN NAME, so a column that moves, is
    added, or is dropped does not shift anything.

    Three things are NOT a plain carry, and each is reported rather than assumed:

      * a column whose CONTENT moved (`Matching Notes` -> `Matching Score` +
        `Notes`) is *consumed*, not dropped;
      * a dropped column is exported on request via `--export-dropped`, because
        otherwise its values survive only inside `_machine/backups`;
      * a status value that is neither current nor known-legacy is reported and
        left as it is -- guessing at a colleague's intent is how a decision gets
        lost. A value that is still current but CHANGED MEANING needs
        `--reinterpret`: see `_parse_reinterpret`.
    """
    from openpyxl import Workbook, load_workbook
    from openpyxl.utils import get_column_letter

    d = Path(args.dir)
    to_name = args.to or "Review.xlsx"
    # A bare filename only. The sheet has to end up in the folder the other
    # commands read, and a path here would let a typo put it somewhere nothing
    # looks -- which fails the same way as naming it V2 without a cutover plan.
    if Path(to_name).name != to_name:
        raise StageError(f"--to takes a filename, not a path: {to_name!r}")
    target = d / to_name
    # `--from` and `--to` are INDEPENDENT: reading the record and writing the
    # record are two decisions. Defaulting `--from` to the target (as this did)
    # would make `--to Review-v2.xlsx` read a file that does not exist yet.
    source = Path(args.source) if args.source else d / "Review.xlsx"
    if not source.exists():
        print(json.dumps({"ok": False, "error": f"{source} does not exist"}, ensure_ascii=False))
        return 2

    old_wb = load_workbook(source, rich_text=True)
    old_ws = old_wb["Review"] if "Review" in old_wb.sheetnames else old_wb.active
    old_header = [old_ws.cell(2, c).value for c in range(1, old_ws.max_column + 1)]
    if not old_header or old_header[0] != REVIEW_COLUMNS[0]:
        print(json.dumps({"ok": False, "error": f"{source} row 2 does not look like a Review header"}, ensure_ascii=False))
        return 2

    carried = [c for c in REVIEW_COLUMNS if c in old_header]
    added = [c for c in REVIEW_COLUMNS if c not in old_header]
    dropped = [c for c in old_header if c and c not in REVIEW_COLUMNS]

    # Snapshot every row before touching anything: `write_atomically` replaces
    # the file, and reading from the same handle afterwards would read the new one.
    data = [
        [old_ws.cell(r, c).value for c in range(1, old_ws.max_column + 1)]
        for r in range(3, old_ws.max_row + 1)
    ]
    data = [row for row in data if row and str(row[0] or "").strip()]

    reinterpret = _parse_reinterpret(args.reinterpret or [])

    i_status = old_header.index("Contact Search Status") if "Contact Search Status" in old_header else None
    translated: dict[str, int] = {}
    reinterpreted: dict[str, int] = {}
    unknown: dict[str, int] = {}
    if i_status is not None:
        for row in data:
            raw = row[i_status]
            if raw in (None, ""):
                continue
            value = str(raw).strip()
            # `--reinterpret` is consulted FIRST, because its sources are by
            # definition values still in the vocabulary -- and the `elif` below
            # skips exactly those.
            if value in reinterpret:
                reinterpreted[value] = reinterpreted.get(value, 0) + 1
            elif value in CONTACT_STATUS_VALUES:
                continue
            elif value in LEGACY_CONTACT_STATUS:
                translated[value] = translated.get(value, 0) + 1
            else:
                unknown[value] = unknown.get(value, 0) + 1

    if unknown and not args.force:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "unmapped_status",
                    "error": "some Contact Search Status values are neither current nor known-legacy. "
                    "Migrating would leave them as-is under a new vocabulary. Add them to "
                    "LEGACY_CONTACT_STATUS or fix them first, then re-run.",
                    "unmapped": unknown,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    # Where each departing column's CONTENT went. A dropped column NOT named here
    # is one whose values are genuinely leaving the record -- which is the case
    # `--export-dropped` exists to make recoverable.
    consumed: dict[str, str] = {}
    if "Matching Notes" in old_header:
        consumed["Matching Notes"] = "Matching Score + Notes"
    if "Reviewer Notes" in old_header:
        consumed["Reviewer Notes"] = "Notes"

    migrated = [_migrated_notes(row, old_header) for row in data]
    notes_split = sum(1 for score_cell, _, _ in migrated if score_cell)
    notes_merged = sum(1 for _, _, merged in migrated if merged)

    # Before the rebuild, never after: `write_atomically` replaces the file, so a
    # dropped column's values would be gone from disk by the time anything could
    # read them back. Written even when the rebuild then fails -- an export that
    # was not needed costs a file, a lost column costs a record.
    exported: dict | None = None
    if args.export_dropped and dropped and not args.dry_run:
        dest = Path(args.export_dropped)
        dest.mkdir(parents=True, exist_ok=True)
        out_path = dest / f"Review-dropped-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        idx = [old_header.index(c) for c in dropped]
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([REVIEW_COLUMNS[0]] + dropped)
            for row in data:
                w.writerow([row[0]] + [row[j] for j in idx])
        exported = {"file": str(out_path), "rows": len(data), "columns": dropped}

    def apply(tmp: Path) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Review"
        _write_review_header(ws)
        for i, row in enumerate(data):
            out_row = 3 + i
            score_cell, note_cell, _ = migrated[i]
            for c, name in enumerate(REVIEW_COLUMNS, start=1):
                if name == "Matching Score":
                    # An ADDED column: there is nothing in the old header to look
                    # up. Its value comes out of the old machine notes, which is
                    # what makes this a carry rather than a loss.
                    value: object = score_cell
                elif name == "Notes":
                    value = note_cell
                elif name == "Contact Search Status":
                    raw = row[old_header.index(name)] if name in old_header else None
                    if raw in (None, ""):
                        value = raw
                    else:
                        seen = str(raw).strip()
                        seen = LEGACY_CONTACT_STATUS.get(seen, seen)
                        value = reinterpret.get(seen, seen)
                else:
                    if name not in old_header:
                        continue
                    value = row[old_header.index(name)]
                ws.cell(out_row, c, value if value not in (None, "") else None)
                if name in DATE_COLUMNS and isinstance(value, datetime):
                    ws.cell(out_row, c).number_format = DATE_NUMBER_FORMAT
        _apply_review_validation(ws)
        _install_color_rules(ws, REVIEW_COLUMNS)
        # Freeze the company column -- the sheet is keyed by it. This read "C3"
        # (Company + Brands) until `Brands / Business Units` was deleted on
        # 2026-09-23; nothing computed it, so it had to be corrected by hand.
        ws.freeze_panes = "B3"
        ws.auto_filter.ref = f"A2:{get_column_letter(len(REVIEW_COLUMNS))}{max(3 + len(data) - 1, 2)}"
        wb.save(tmp)

    report: dict[str, object] = {
        "source": str(source),
        "target": str(target),
        "rows": len(data),
        # A list, in BOTH branches. It was a list for --dry-run and a count for
        # the real run, so reading one and then the other meant reading two
        # different things under one name.
        "columns_carried": carried,
        "columns_added": added,
        "columns_dropped": dropped,
        # Which departing columns had their CONTENT moved somewhere, and where.
        # A dropped column absent from this map is one whose values are leaving.
        "columns_consumed": consumed,
        "notes_split": notes_split,
        "notes_merged": notes_merged,
        "status_translated": translated,
        "status_reinterpreted": reinterpreted,
        "unmapped_status": unknown,
    }

    if args.dry_run:
        report["dry_run"] = True
        if args.export_dropped and dropped:
            # Reported, not written: a dry run that leaves a file behind is not a
            # dry run. The counts are the same either way.
            report["would_export"] = {"dir": args.export_dropped, "rows": len(data), "columns": dropped}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    synced_fs.write_atomically(
        target,
        apply,
        allow_hydrate=args.allow_hydrate,
        backup_dir=d / "_machine" / "backups",
    )
    report["ok"] = True
    report["backup_dir"] = str(d / "_machine" / "backups")
    if exported:
        report["exported_dropped"] = exported
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_color(args: argparse.Namespace) -> int:
    """Install the CF rulesets on Review.xlsx. Idempotent. Never writes styles to
    any cell — only conditional-formatting rules on the sheet."""
    from openpyxl import load_workbook

    d = Path(args.dir)
    target = d / "Review.xlsx"
    if not target.exists():
        print(json.dumps({"ok": False, "error": f"{target} does not exist; run init-review first"}, ensure_ascii=False))
        return 2

    if args.dry_run:
        print(json.dumps({"dry_run": True, "target": str(target), "spec": COLOR_RULES_SPEC}, indent=2))
        return 0

    applied: list[str] = []

    def apply(tmp: Path) -> None:
        # rich_text=True so a first save does not flatten coloured cell text.
        wb = load_workbook(target, rich_text=True)
        ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
        header = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]
        applied.extend(_install_color_rules(ws, header))
        wb.save(tmp)

    synced_fs.write_atomically(
        target,
        apply,
        allow_hydrate=args.allow_hydrate,
        backup_dir=d / "_machine" / "backups",
    )
    print(json.dumps({"ok": True, "target": str(target), "spec": COLOR_RULES_SPEC, "rules": applied}, indent=2, ensure_ascii=False))
    return 0


def _review_as_canonical(ws) -> object:
    """View the open Review sheet as a Canonical so `match_company` can be reused
    verbatim. Same ladder, same ambiguity handling as everywhere else — a second
    implementation of "is this company already known" is how the readers drift
    apart again.

    Refuses a sheet whose header has drifted, BEFORE reading a single row, and
    this is the one place to put that: every reader of Review.xlsx goes through
    here, and `migrate-review` — the tool you run when a header needs rebuilding —
    deliberately does not.

    Why it has to be explicit: every column is located BY NAME, so a missing one
    does not raise, it reads as `""`. `CanonicalRow.get` swallows the ValueError
    for exactly that reason. Measured with only `Company / Outreach Account`
    renamed:

      * every company read as unknown, so a run re-proposes accounts it already
        has and `append` sees them all as new;
      * the row `append` then writes carries the role, the links, a `Not started`
        status and a fresh `Company ID` — and NO company name, because the writer
        resolves column names the same way the reader does.

    So it fails silently in both directions at once, and nothing downstream can
    tell any of it from normal operation.
    """
    from reconcile import Canonical, CanonicalRow

    header = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]
    missing = [c for c in REVIEW_COLUMNS if c not in header]
    if missing:
        shown = ", ".join(missing[:4]) + (" …" if len(missing) > 4 else "")
        raise StageError(
            f"Review.xlsx is missing {len(missing)} expected column(s): {shown}. "
            "Columns are read by name, so a missing one reads as empty rather than "
            "failing — for `Company / Outreach Account` that makes every company look "
            "new, and `append` would re-add the whole sheet. Run `migrate-review` to "
            "rebuild it onto the current columns, or restore the header."
        )
    rows = []
    for r in range(3, ws.max_row + 1):
        cells = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if not str(cells[0] or "").strip():
            continue
        rows.append(
            CanonicalRow(index=r, cells=[_cell_text(header[i], v) for i, v in enumerate(cells)], header=header)
        )
    return Canonical(header=header, rows=rows).finalize()


def _cell_text(column: str, value: object) -> str:
    """One workbook cell as the text a Canonical holds.

    Date columns go out as date-only ISO. `str()` of a date cell yields
    '2026-09-03 00:00:00', which `parse_date` did not read — so `export-history`
    wrote a CSV its own reader could not read back, and every date in it
    compared as a change. Both consumers of this view (the `append` matching
    ladder and the export) get the fix from one place, which is the point of
    having one view.

    `_sidecar_value` already states this convention for the guard-refusal sidecar;
    this is the same rule applied to the whole sheet.
    """
    if value is None:
        return ""
    if column in DATE_COLUMNS:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
    return str(value)


def _first_free_row(ws) -> int:
    """First row from 3 down whose company cell is empty. Scans rather than using
    max_row+1 so an emptied row is reused instead of leaving a hole.

    Call this ONCE PER COMPANY, never once and then `row_i += 1`. Incrementing
    walks past a gap straight into the occupied rows below it: with row 5 emptied
    and rows 6..7 still holding companies, `append` wrote the second new company
    over row 6's. Resolving again each time returns a row, or the bottom of the
    sheet, and can never return an occupied one.
    """
    for r in range(3, ws.max_row + 2):
        if not str(ws.cell(r, 1).value or "").strip():
            return r
    return ws.max_row + 1


def _cell_conflicts(cell, value: object) -> bool:
    """Would writing `value` here destroy something already in the cell?

    Dates are compared as dates: a cell holds a real datetime while the incoming
    value is the A4 string, so `str(datetime)` -- '2026-09-01 00:00:00' against
    '01/09/2026' -- would call every date a conflict.
    """
    current = cell.value
    if current in (None, ""):
        return False
    if isinstance(current, datetime):
        parsed = parse_date(str(value))
        return parsed is None or current.date() != parsed
    return str(current).strip() != str(value).strip()


_SCORE_IN_NOTES = re.compile(r"Match score:\s*(\d{1,3})\s*/\s*100\s*;?\s*")


def split_scores_from_notes(notes: str | None) -> tuple[str, str]:
    """(matching_score_cell, note_cell) from a note carrying scores inline.

    The historical machine form is

        [NEW COMPANY] 3 new role(s). 1. [pertinente] Match score: 92/100; <motivazione> 2. ...

    and the score now has its own column, so it is lifted out of the prose rather
    than left to say the same thing twice. The scores are numbered in the order
    they appear, which is the order the note already numbers its roles -- that is
    what makes the cell line up with `Matching Job Titles` / `Job Links`.

    Only used where the text genuinely predates the split: `init-review` seeding
    from a canonical history, and the one-off `migrate-review`. A live run
    supplies `Notes` and `Matching Score` as separate columns and never comes
    through here.
    """
    text = notes or ""
    scores = _SCORE_IN_NOTES.findall(text)
    score_cell = " | ".join(f"{i}. {s}" for i, s in enumerate(scores, 1))
    # Drop the clause AND the `;` that followed it, so removing the score does not
    # leave a dangling separator behind in the prose.
    cleaned = _SCORE_IN_NOTES.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return score_cell, cleaned


def _new_company_values(company: dict[str, str]) -> dict[str, object]:
    """Every value `append` writes for a genuinely-new company, keyed by REVIEW_COLUMNS.

    One function, because there were two writers and they disagreed. The workbook
    path built these values inline; the guard-refusal sidecar did
    `company.get(col_name)` over a dict shaped by A4_COLUMNS instead. Columns
    therefore came out empty on every row of every sidecar.

    THE ONE WRITE RULE. `Notes` is machine-seeded and colleague-owned, the only
    column that is both, and this function is the only place the machine writes
    it -- on a row being CREATED. `append` never touches an existing cell, so the
    rule holds; but it holds because of the current command set, not by
    construction, and losing it fuses machine text into somebody's note
    irreversibly. That already happened once (see the module comment above
    REVIEW_COLUMNS). A test asserts it.
    """
    out: dict[str, object] = {}
    for col in REVIEW_COLUMNS:
        if col == "Company ID":
            # A NEW company has no id yet, so propose one and store it -- otherwise
            # the next run can only match it by name. Stored, never recomputed.
            # Deterministic, so the id here is the id a later `append` would propose.
            out[col] = company.get("Company ID") or propose_company_id(company["Company / Outreach Account"])
        elif col == "Notes":
            # Seeded from the run's own `Notes`. This is THAT one write -- see the
            # docstring. The score does not come from here: a live run supplies
            # `Matching Score` as its own A4 column, so it falls through to the
            # generic branch below.
            out[col] = company.get(NOTES_SOURCE_COLUMN, "")
        elif col in HUMAN_COLS:
            out[col] = NEW_COMPANY_DEFAULTS.get(col, "")
        else:
            out[col] = company.get(col, "")
    return out


def _sidecar_value(column: str, value: object) -> str:
    """One cell of the guard-refusal sidecar.

    Dates go out as ISO. A CSV cannot hold a real date, so pasting this file back
    puts text in a date column either way -- but `2026-09-01` is the format
    `parse_date` reads without ambiguity and that Excel reads as a date in any
    locale, while `01/09/2026` is the one a permissive reader gets wrong.
    """
    if column in DATE_COLUMNS:
        parsed = parse_date(str(value))
        if parsed is not None:
            return parsed.isoformat()
    return "" if value is None else str(value)


def _read_machine_companies(d: Path, run_id: str | None) -> tuple[str, list[dict[str, str]]]:
    """Read the companies CSV that `stage` wrote for the run. Consuming the staged
    artifact rather than re-parsing the TSV means append cannot disagree with what
    stage already validated."""
    machine = d / "_machine"
    if run_id is None:
        manifest = machine / "last-run.json"
        if not manifest.exists():
            raise StageError("no last-run.json: run `stage` first, or pass --run-id")
        run_id = json.loads(manifest.read_text(encoding="utf-8"))["run_id"]
    path = machine / f"companies-{run_id}.csv"
    if not path.exists():
        raise StageError(f"missing {path}: run `stage` for run {run_id} first")
    text = path.read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    return run_id, rows


def cmd_append(args: argparse.Namespace) -> int:
    """Append genuinely-new companies to Review.xlsx.

    The only command that writes into the file colleagues edit, so it is the most
    constrained:

      * append-only — values go into EMPTY cells at the bottom; no existing cell
        is ever overwritten
      * values only, never styles — the machine cannot mark up the sheet, and the
        colours come from the CF rules installed once by `color`
      * backup first, then temp file + os.replace
      * on any guard failure it writes a sidecar CSV instead and exits 0, because
        a missed append costs one paste while a botched write costs a week
    """
    from openpyxl import load_workbook

    d = Path(args.dir)
    target = d / "Review.xlsx"
    if not target.exists():
        print(json.dumps({"ok": False, "error": f"{target} does not exist; run init-review first"}, ensure_ascii=False))
        return 2

    run_id, companies = _read_machine_companies(d, args.run_id)
    if not companies:
        print(json.dumps({"ok": True, "run_id": run_id, "appended": 0, "deferred": 0, "note": "no companies in run"}, ensure_ascii=False))
        return 0

    alias_table = load_aliases(d.parent / "company-aliases.csv")
    wb = load_workbook(target, rich_text=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    existing = _review_as_canonical(ws)
    header = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]

    to_add: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    # Counted, not derived by subtraction. `len(companies) - len(to_add) - len(deferred)`
    # also swept in rows skipped for an empty company name, so a malformed run
    # inflated "already present" — the one number an operator reads to decide
    # whether a run found anything new.
    already = 0
    for row in companies:
        name = (row.get("Company / Outreach Account") or "").strip()
        if not name:
            continue
        m = match_company(name, existing, aliases=alias_table.mapping)
        if m.kind == "matched":
            already += 1
            continue
        if m.kind in ("ambiguous", "needs_human"):
            # Never auto-append: a near-duplicate or an already-twice-present name
            # is how the 5 existing duplicate rows happened.
            deferred.append(
                {
                    "company": name,
                    "reason": m.reason,
                    "candidates": [c.company for c in m.candidates][:4],
                }
            )
            continue
        to_add.append(row)

    summary: dict = {
        "run_id": run_id,
        "target": str(target),
        "in_run": len(companies),
        "already_present": already,
        "to_append": len(to_add),
        # Always present, so callers never have to branch on whether anything was
        # written. Stays 0 on the dry-run and on every refusal path.
        "appended": 0,
        "deferred": len(deferred),
        # What the matching ladder actually had to work with. A missing or
        # header-only table means rung 3 could not fire, which is worth knowing
        # before reading `deferred` as "genuinely new companies".
        "aliases": alias_table.report(),
    }
    if deferred:
        summary["deferred_detail"] = deferred

    if args.dry_run:
        summary["dry_run"] = True
        summary["would_append"] = [r.get("Company / Outreach Account") for r in to_add]
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    if not to_add:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    def apply(tmp: Path) -> None:
        for company in to_add:
            # Resolved PER COMPANY. See _first_free_row: computing it once and
            # then incrementing walks past a gap into the occupied rows below.
            row_i = _first_free_row(ws)
            values = _new_company_values(company)
            for c, col_name in enumerate(header, start=1):
                # Ownership and date-ness are different axes -- `Last Checked` is
                # machine-owned (A4 MACHINE_LATEST_COLS) while `First Contact
                # Date`/`Recall` are human-owned, and all three are date columns.
                # `values` already resolves ownership; the date handling below is
                # the only place the two axes meet.
                value = values.get(col_name, "")
                if value in (None, ""):
                    continue
                cell = ws.cell(row_i, c)
                # Last line of defence: only empty cells are ever touched. If one
                # is not empty the append is REFUSED, `write_atomically` leaves the
                # file untouched, and the caller writes a sidecar -- the trade this
                # module makes everywhere. A missed append costs one paste; a silent
                # overwrite costs a colleague's work.
                if _cell_conflicts(cell, value):
                    raise synced_fs.GuardFailure(
                        "cell_occupied",
                        f"{col_name} at row {row_i} holds {str(cell.value)[:40]!r}, "
                        f"refusing to overwrite it with {str(value)[:40]!r}",
                    )
                # Values only. Not a style, not a validation rule.
                if col_name in DATE_COLUMNS:
                    parsed = parse_date(str(value))
                    if parsed is not None:
                        cell.value = parsed
                        cell.number_format = DATE_NUMBER_FORMAT
                        continue
                cell.value = value
        wb.save(tmp)

    try:
        synced_fs.write_atomically(
            target,
            apply,
            allow_hydrate=args.allow_hydrate,
            backup_dir=d / "_machine" / "backups",
        )
    except synced_fs.GuardFailure as exc:
        sidecar = d / f"Review-additions-{run_id}.csv"
        with sidecar.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(REVIEW_COLUMNS)
            for company in to_add:
                # The same values the workbook path would have written, from the
                # same function -- the two used to differ, and the sidecar silently
                # lost Matching Notes, Contact Search Status and Company ID.
                values = _new_company_values(company)
                w.writerow([_sidecar_value(c, values.get(c, "")) for c in REVIEW_COLUMNS])
        summary.update(
            {
                "appended": 0,
                "reason": exc.reason,
                "detail": exc.detail,
                "sidecar": str(sidecar),
                "note": (
                    f"nothing written to Review.xlsx; {len(to_add)} row(s) left in the sidecar "
                    "(dates as YYYY-MM-DD)"
                ),
            }
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    summary["appended"] = len(to_add)
    summary["backup_dir"] = str(d / "_machine" / "backups")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


# Review.xlsx column -> canonical CSV column, where the two names differ.
#
# EMPTY as of 2026-09-23, and kept as the seam rather than deleted. It held
# `{"Matching Notes": "Notes"}` because Review split A4's single `Notes` into a
# machine half and a human half; merging the halves removed the reason. A test
# asserts it is empty, so a future rename has to declare itself here rather than
# be assumed away.
REVIEW_TO_A4_COLUMN: dict[str, str] = {}


# Columns `harvest` compares between Review.xlsx and the export it is pointed at:
# the human-owned set. These were called PULL_* until `pull` was removed on
# 2026-09-18 -- the name said pull, but `harvest` is what reads them, which is
# how a rename can look safe and not be.
HARVEST_COLUMNS = list(HUMAN_COLS)

# Columns a comparison against an EXPORT must not count.
#
# EMPTY as of 2026-09-23, for the same reason as the mapping above: it held
# `["Reviewer Notes"]` because that column existed only in Review.xlsx, so on the
# exported side it always read empty and every row carrying a note reported as a
# change on every run, forever. Declared in the output rather than dropped,
# because a report that cannot see a column should say so instead of quietly
# ignoring it.
NOT_COMPARED: list[str] = []


def _harvest_review(d: Path, canon) -> dict:
    """Read Review.xlsx and report what changed since `canon`.

    Read-only: this is the audit path, not a sync.

    A DELTA, not a reconciliation. `canon` is expected to be an `export-history`
    output -- the same record as it stood at the previous run -- so a difference
    between the two IS the change being asked for. The older framing called that
    a "conflict", which only made sense while a second, separately maintained
    record existed to disagree with; calling it one now would label every
    colleague decision as a discrepancy.

    A company whose identity cannot be settled is neither: nothing about it can
    be compared, so it is reported apart from the changes rather than inside them.
    """
    from openpyxl import load_workbook

    alias_table = load_aliases(d.parent / "company-aliases.csv")
    wb = load_workbook(d / "Review.xlsx", read_only=True, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    header = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]

    changes: list[dict] = []
    new_rows: list[dict] = []
    unresolved: list[dict] = []

    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row or not row[0]:
            continue
        values = {header[i]: row[i] for i in range(min(len(header), len(row)))}
        name = str(values.get("Company / Outreach Account") or "").strip()
        cid = str(values.get("Company ID") or "").strip()
        m = match_company(name, canon, aliases=alias_table.mapping, company_id=cid)

        if m.kind == "matched":
            for col in HARVEST_COLUMNS:
                if col in NOT_COMPARED:
                    continue
                raw_incoming = values.get(col)
                if raw_incoming in (None, ""):
                    continue
                # Normalise at the boundary. openpyxl hands back a datetime for a
                # date cell, and str() on it yields '2026-09-03 00:00:00' -- which
                # parse_date cannot read, so every date would look like a change.
                if isinstance(raw_incoming, datetime):
                    incoming = raw_incoming.date().isoformat()
                elif isinstance(raw_incoming, date):
                    incoming = raw_incoming.isoformat()
                else:
                    incoming = str(raw_incoming).strip()
                if not incoming:
                    continue
                canonical_col = REVIEW_TO_A4_COLUMN.get(col, col)
                current = m.row.get(canonical_col).strip()
                # Compare as VALUES, not strings: a date written to the workbook
                # comes back as a real date against the CSV's text, and a string
                # compare flags every row.
                if same_value(col, current, incoming):
                    continue  # already in agreement -- nothing changed, nothing to report
                changes.append(
                    {"company": m.row.company, "column": col, "was": current[:90], "now": incoming[:90]}
                )
        elif m.kind == "unmatched":
            new_rows.append({"company": name, "values": values})
        else:
            unresolved.append(
                {
                    "company": name,
                    "reason": m.reason,
                    "candidates": [c.company for c in m.candidates][:3],
                }
            )
    wb.close()
    return {
        "changes": changes,
        "new_rows": new_rows,
        "unresolved": unresolved,
        "aliases": alias_table.report(),
    }


def cmd_harvest(args: argparse.Namespace) -> int:
    """Report what colleagues decided since the export at `--history`. Never writes.

    Point `--history` at the previous run's `export-history` output. The two files
    are then one record at two moments, and every difference is a decision somebody
    made -- which is what this command exists to surface. `export-history` is
    read-only, so the previous run's CSV can be kept beside the run that produced
    it without either command writing to the other's file.
    """
    d = Path(args.dir)
    if not (d / "Review.xlsx").exists():
        print(json.dumps({"ok": False, "error": f"{d / 'Review.xlsx'} does not exist"}, ensure_ascii=False))
        return 2
    canon = load_canonical(args.history)
    h = _harvest_review(d, canon)
    out = {
        "review": str(d / "Review.xlsx"),
        "compared_against": str(args.history),
        "changes": len(h["changes"]),
        "changed_companies": len({c["company"] for c in h["changes"]}),
        "new_companies": len(h["new_rows"]),
        "unresolved": len(h["unresolved"]),
        # Columns the export cannot carry, so this comparison cannot see them.
        "not_compared": NOT_COMPARED,
        "aliases": h["aliases"],
    }
    # The detail IS the report: "3 changes" does not say what a colleague did, and
    # that is the question this command exists to answer. Capped by default so a
    # long delta stays readable, uncapped with --verbose.
    def capped(items: list) -> list:
        return items if args.verbose else items[:40]

    out["change_detail"] = capped(h["changes"])
    out["new_detail"] = capped([r["company"] for r in h["new_rows"]])
    if h["unresolved"]:
        out["unresolved_detail"] = capped(h["unresolved"])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="sync_export.py", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="verify the target dir before any run")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("stage", help="publish a run to Roles.xlsx (never touches Review.xlsx)")
    p.add_argument("--dir", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--tsv", help="path to the A4 TSV; omit to read stdin")
    p.add_argument(
        "--evidence",
        help="per-role sidecar (url;posted;alternate_urls;search_query) supplying the columns"
        " A4's 22-column TSV cannot carry",
    )
    p.add_argument("--run-id")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-hydrate", action="store_true")
    p.add_argument(
        "--lenient",
        action="store_true",
        help="stage rows whose values do not fit their column, recording the problems in the manifest",
    )
    p.set_defaults(func=cmd_stage)

    for name, fn, helptext, needs_history in [
        ("init-review", cmd_init_review, "create Review.xlsx seeded from canonical history", True),
        ("color", cmd_color, "install the conditional-formatting status rules on Review.xlsx", False),
        ("append", cmd_append, "append genuinely-new companies to Review.xlsx (guarded, append-only)", False),
        ("harvest", cmd_harvest, "report what colleagues decided (read-only)", True),
        (
            "export-history",
            cmd_export_history,
            "write Review.xlsx as a CSV the search run can dedup against",
            False,
        ),
        (
            "migrate-review",
            cmd_migrate_review,
            "rebuild Review.xlsx onto the current REVIEW_COLUMNS, carrying every cell by column name",
            False,
        ),
    ]:
        q = sub.add_parser(name, help=helptext)
        q.add_argument("--dir", required=True)
        # Declared exactly once per command: argparse raises on a duplicate
        # option string, so there is no "add it here and prune it later".
        q.add_argument("--history", required=needs_history)
        q.add_argument("--dry-run", action="store_true")
        q.add_argument("--allow-hydrate", action="store_true")
        if name == "init-review":
            q.add_argument("--force", action="store_true", help="overwrite an existing Review.xlsx")
        if name == "append":
            q.add_argument("--run-id", help="defaults to the latest run in _machine/last-run.json")
        if name == "export-history":
            q.add_argument("--out", help="where to write the CSV (default: <dir>/_machine/review-history.csv)")
        if name == "migrate-review":
            q.add_argument("--from", dest="source", help="read the old sheet from here instead (e.g. a backup)")
            q.add_argument(
                "--to",
                metavar="FILENAME",
                help="write the rebuilt sheet under this name in --dir instead of Review.xlsx, so the "
                "live file is left untouched while somebody is still editing it. A bare filename, not "
                "a path: the sheet has to land in the folder the other commands read.",
            )
            q.add_argument("--force", action="store_true", help="migrate even if some status values are unmapped")
            q.add_argument(
                "--export-dropped",
                metavar="DIR",
                help="write every column that leaves the schema to a CSV in DIR, before rebuilding. "
                "Dropped columns are otherwise carried NOWHERE -- they survive only inside "
                "_machine/backups -- so this is the safety net for a schema change that removes real data.",
            )
            q.add_argument(
                "--reinterpret",
                action="append",
                default=[],
                metavar="OLD=NEW",
                help="re-read a status value that is STILL in the vocabulary (repeatable), e.g. "
                "'Not started=New job found'. LEGACY_CONTACT_STATUS cannot express this: the census "
                "skips any value already in the vocabulary, so a live value never reaches the "
                "translation branch. Requires --dry-run to be read first.",
            )
        if name == "harvest":
            q.add_argument("--verbose", action="store_true")
        q.set_defaults(func=fn)

    args = ap.parse_args()
    try:
        return args.func(args)
    except (StageError, synced_fs.GuardFailure) as exc:
        reason = getattr(exc, "reason", "stage_error")
        print(json.dumps({"ok": False, "reason": reason, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
