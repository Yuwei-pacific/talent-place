#!/usr/bin/env python3
"""Canonical-history reading, column ownership, and company matching.

This module is the Python half of a contract that also exists in TypeScript
(``engine/src/normalize.ts``). Two things must stay byte-for-byte equivalent
between the two, because both read the same canonical CSV and disagreeing
readers is the bug class this module exists to prevent:

  * ``MULTI_VALUE_SPEC`` / ``split_multi`` — how a multi-value cell is split.
  * ``norm_company`` — how a company name is normalised for matching.

``engine/python/test_sync_export.py`` asserts parity against the TS side.

Why a per-column separator policy rather than one universal splitter:
``Work Modes`` legitimately holds ';' INSIDE a single value
("Physical location shown; onsite/hybrid status to verify", 50 rows carry that
default). Treating ';' as a universal separator shreds one value into two.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Multi-value cells
# --------------------------------------------------------------------------

MULTI_VALUE_SPEC: dict[str, dict[str, bool]] = {
    "Matching Job Titles": {"semicolon": False, "numbered": True},
    # alt_marker: seen once in the canonical CSV (Cefriel), where a primary
    # employer URL and its LinkedIn mirror share one line. That alternate is a
    # real dedup target, so it splits out rather than riding inside the primary.
    "Job Links": {"semicolon": False, "numbered": True, "alt_marker": True},
    "Locations": {"semicolon": False, "numbered": True},
    "Master-fit Themes": {"semicolon": True, "numbered": False},
    # semicolon=False is load-bearing — see the module docstring.
    "Work Modes": {"semicolon": False, "numbered": False},
    "Sources / Portals": {"semicolon": True, "numbered": False},
}

# Columns that are free text and must never be split.
FREE_TEXT_COLS = {"Notes", "Curricular Evidence", "Reviewer Notes", "Matching Notes"}

_NUMBERED_SPLIT = re.compile(r"(?:^|\n|\|)\s*(\d+)\.\s+")
_ALT_SPLIT = re.compile(r"(?:^|\s)alt\.\s+", re.IGNORECASE)
_LEADING_NUM = re.compile(r"^\d+\.\s*")


def _split_numbered(raw: str) -> list[str] | None:
    """Split on the numbering, or None if the cell is not a genuine 1..N list.

    The numbering only counts as a separator at a real item boundary (cell
    start, after a newline, or after a pipe) AND when the captured numbers form
    a contiguous 1..N run. Both conditions matter: a title like
    "1. Intern - Level 2. Design" contains " 2. " mid-sentence, and splitting
    there mints bogus items, each of which becomes a WRONG dedup key.
    """
    if not re.match(r"^\s*1\.\s", raw):
        return None
    parts = _NUMBERED_SPLIT.split(raw)
    nums = parts[1::2]
    texts = parts[2::2]
    if not nums:
        return None
    if nums != [str(i + 1) for i in range(len(nums))]:
        return None
    return texts


def split_multi(value: str | None, spec: dict[str, bool]) -> list[str]:
    """Split a canonical multi-value cell into its items."""
    raw = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []

    parts = None
    if spec.get("numbered"):
        parts = _split_numbered(raw)
    if parts is None:
        parts = raw.split("\n")

    if spec.get("alt_marker"):
        expanded: list[str] = []
        for p in parts:
            expanded.extend(_ALT_SPLIT.split(p))
        parts = [p for p in expanded if p]

    out: list[str] = []
    for part in parts:
        if spec.get("semicolon"):
            subs = re.split(r"\s*\|\s*|\s*;\s*", part)
        else:
            subs = re.split(r"\s*\|\s*", part)
        for sub in subs:
            item = _LEADING_NUM.sub("", sub).strip()
            if item:
                out.append(item)
    return out


def split_column(value: str | None, column: str) -> list[str]:
    """Split a named canonical column. Free-text columns have no spec."""
    if column in FREE_TEXT_COLS:
        raise KeyError(f"column is free text and must not be split: {column}")
    spec = MULTI_VALUE_SPEC.get(column)
    if spec is None:
        raise KeyError(f"no multi-value spec for column: {column}")
    return split_multi(value, spec)


# --------------------------------------------------------------------------
# Company normalisation + identity
# --------------------------------------------------------------------------

_LEGAL_SUFFIX = re.compile(
    r"\b(s\.?p\.?a\.?|s\.?r\.?l\.?|s\.?a\.?s\.?|ltd|limited|gmbh|sas|sarl|bv|nv|sl|sa|inc|llc|spa|srl)\b",
    re.IGNORECASE,
)


def norm_company(value: str) -> str:
    """Mirror of normCompany() in engine/src/normalize.ts."""
    s = (value or "").lower()
    s = unicodedata.normalize("NFKD", s)
    # Explicit range (not unicodedata.combining) to match the TS regex exactly.
    s = re.sub(r"[̀-ͯ]", "", s)
    s = _LEGAL_SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def propose_company_id(name: str) -> str:
    """Propose an id for a company name. ONLY ever a proposal — see below.

    The id is assigned once and STORED; it is never recomputed. A content hash
    survives "Loro Piana" -> "Loro Piana S.p.A." (the suffix is stripped) but
    NOT "Moncler" -> "Moncler Group". Recomputing it on every run would
    reintroduce exactly the identity bug it exists to fix.
    """
    digest = hashlib.sha1(norm_company(name).encode("utf-8")).hexdigest()[:8]
    return f"polids-{digest}"


# --------------------------------------------------------------------------
# Column ownership — as data, not as a trailing comment
# --------------------------------------------------------------------------

# Columns a colleague owns. The machine reads them and never invents them.
HUMAN_COLS = [
    "Previously Contacted?",
    "Contact Search Status",
    "Contact Name",
    "Contact Role",
    "Contact Email / LinkedIn",
    "Outreach Decision",
    "Reviewer Notes",
    "First Contact Date",
    "Recall",
]

# Machine-owned, merged by union (append what is new, keep what is there).
MACHINE_UNION_COLS = [
    "Matching Job Titles",
    "Job Links",
    "Locations",
    "Sources / Portals",
    "Master-fit Themes",
    "Work Modes",
]

# Machine-owned, latest value wins.
MACHINE_LATEST_COLS = ["Verification Status", "Last Checked"]

# Machine-authored prose. Split out of the legacy single `Notes` column so
# machine text and colleague notes can never fuse irreversibly.
MACHINE_TEXT_COLS = ["Matching Notes"]

# Columns holding dates. Written as real datetime values, never as text: a
# conditional-formatting formula like `$W2<=TODAY()` compares STRINGS against
# "03/09/2026" and silently returns the wrong answer while the cell still looks
# correct.
#
# NOTE: this set spans both owners -- `Last Checked` is machine-owned
# (MACHINE_LATEST_COLS) while `First Contact Date` and `Recall` are
# human-owned. Ownership and date-ness are different axes; do not blank every
# member of this list when appending.
DATE_COLUMNS = ["Last Checked", "First Contact Date", "Recall"]


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

# Explicit, ordered, day-first. Never infer: `Last Checked` is 79 ISO + 37
# DD/MM/YYYY and `First Contact Date` is 60 D/M/YYYY, so a permissive parser
# (pandas) reads 03/09/2026 as 9 March instead of 3 September.
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y")


def parse_date(value: str | None) -> date | None:
    """Parse a canonical-CSV date, or None. Day-first is explicit in the format
    list, so there is no ambiguity to resolve heuristically.

    A trailing time component is discarded. `export-history` stringified a date
    cell as `str(datetime)`, which yields '2026-09-03 00:00:00' — a form this
    function returned None for, so every date in the exported CSV compared as a
    change. Tolerating it here reads files already on disk; the writer is fixed
    separately so new exports do not produce it.

    DATE_FORMATS deliberately stays the list of formats a value may be WRITTEN
    in — `detect_date_format` answers "which convention does this cell use", and
    a datetime is not one of the conventions.
    """
    s = (value or "").strip()
    if not s:
        return None
    s = re.split(r"[ T]\d{1,2}:\d{2}", s, maxsplit=1)[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value: date | None, iso: bool = False) -> str:
    if value is None:
        return ""
    return value.isoformat() if iso else value.strftime("%d/%m/%Y")


def detect_date_format(reference: str | None) -> str | None:
    """Which of DATE_FORMATS does `reference` match, if any?

    Lets a rewrite keep the convention already in the cell. `Last Checked` is
    mostly ISO while `First Contact Date` is uniformly DD/MM/YYYY; writing the
    other style into one cell would introduce a second convention inside a
    single column.
    """
    s = (reference or "").strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(s, fmt)
            return fmt
        except ValueError:
            continue
    return None


def same_value(column: str, current: str | None, incoming: str | None) -> bool:
    """Compare two cell values semantically.

    Date columns are compared as DATES: the canonical CSV holds '03/09/2026'
    where the workbook holds a real date, and comparing those as strings makes
    every single row look like a conflict.
    """
    a = (current or "").strip()
    b = (incoming or "").strip()
    if a == b:
        return True
    if column in DATE_COLUMNS:
        da, db = parse_date(a), parse_date(b)
        if da is not None and db is not None:
            return da == db
    return False


# --------------------------------------------------------------------------
# Canonical history
# --------------------------------------------------------------------------


@dataclass
class CanonicalRow:
    index: int
    cells: list[str]
    header: list[str]

    def get(self, column: str) -> str:
        try:
            return self.cells[self.header.index(column)]
        except ValueError:
            return ""

    @property
    def company(self) -> str:
        return self.get("Company / Outreach Account").strip()

    @property
    def company_id(self) -> str:
        return self.get("Company ID").strip()

    @property
    def norm_name(self) -> str:
        return norm_company(self.company)


@dataclass
class Canonical:
    header: list[str]
    rows: list[CanonicalRow]
    by_id: dict[str, CanonicalRow] = field(default_factory=dict)
    by_norm_name: dict[str, list[CanonicalRow]] = field(default_factory=dict)
    # Companies whose stored id is shared by more than one row. The canonical CSV
    # has 5 such names (JAKALA, KPMG, NTT DATA, PwC, TeamViewer) whose two rows
    # were given the same proposed id when the column was added. Collapsing them to one row
    # would silently route every update to the first row and leave the second
    # permanently unreachable -- the same failure the deleted add_verified.py had
    # when it let the last row win, just via a different key.
    id_groups: dict[str, list[CanonicalRow]] = field(default_factory=dict)
    ambiguous_ids: set[str] = field(default_factory=set)

    def finalize(self) -> "Canonical":
        for r in self.rows:
            if r.company_id:
                self.id_groups.setdefault(r.company_id, []).append(r)
            if r.norm_name:
                self.by_norm_name.setdefault(r.norm_name, []).append(r)
        for cid, group in self.id_groups.items():
            if len(group) == 1:
                self.by_id[cid] = group[0]
            else:
                self.ambiguous_ids.add(cid)
        return self

    def rows_for_id(self, company_id: str) -> list[CanonicalRow]:
        return self.id_groups.get(company_id, [])


def load_canonical(path: str | Path) -> Canonical:
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rows:
        return Canonical(header=[], rows=[]).finalize()
    header = rows[0]
    out: list[CanonicalRow] = []
    for i, cells in enumerate(rows[1:]):
        # Skip blank rows and stray header repeats.
        if not cells or not (cells[0] or "").strip():
            continue
        if (cells[0] or "").strip() == "Company / Outreach Account":
            continue
        out.append(CanonicalRow(index=i, cells=cells, header=header))
    return Canonical(header=header, rows=out).finalize()


def find_duplicate_names(canon: Canonical) -> dict[str, list[CanonicalRow]]:
    """Company names appearing on more than one row.

    The two historical writers resolved them OPPOSITELY: `history.ts` merged them,
    the since-deleted `add_verified.py` let the last row win so the earlier row
    became unreachable. They are reported, never auto-merged — merging would force
    a choice between two sets of human-owned contact fields.

    Deliberately no count and no names here. Both change — one pair was resolved
    while this docstring still said "5" — and a number in a docstring is one more
    thing that has to stay true. Linear tracks which ones are outstanding.
    """
    return {k: v for k, v in canon.by_norm_name.items() if len(v) > 1}


@dataclass
class AliasTable:
    """The alias table, plus what it took to read it.

    One reader, one read: the mapping and the note about the file come from the
    same pass, so a report of the alias table can never disagree with the aliases
    actually in force.
    """

    mapping: dict[str, str] = field(default_factory=dict)
    path: str = ""
    note: str = ""

    def report(self) -> dict:
        out: dict = {"file": self.path, "loaded": len(self.mapping)}
        if self.note:
            out["note"] = self.note
        return out


def load_aliases(path: str | Path | None) -> AliasTable:
    """Human-maintained alias table: alias_norm;canonical_id;note.

    A missing or header-only file is REPORTED, never returned as an indistinguishable
    "no aliases needed". Rung 3 of the matching ladder is inert either way, so
    silence here hid the human escape hatch from an ambiguous name in exactly the
    case where someone needs to know it is not working.
    """
    if not path:
        return AliasTable(note="no alias table path configured")
    p = Path(path)
    if not p.exists():
        return AliasTable(path=str(p), note="file not found: rung 3 cannot fire")
    out: dict[str, str] = {}
    rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig")), delimiter=";"))
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip() and r[1].strip():
            out[r[0].strip()] = r[1].strip()
    if not out:
        return AliasTable(path=str(p), note="file holds no aliases: rung 3 cannot fire")
    return AliasTable(mapping=out, path=str(p))


# --------------------------------------------------------------------------
# Matching ladder
# --------------------------------------------------------------------------


@dataclass
class Match:
    """Result of matching one incoming company name against canonical history."""

    kind: str  # matched | ambiguous | needs_human | unmatched
    row: CanonicalRow | None = None
    candidates: list[CanonicalRow] = field(default_factory=list)
    reason: str = ""


def match_company(
    name: str,
    canon: Canonical,
    aliases: dict[str, str] | None = None,
    company_id: str | None = None,
    fuzzy_threshold: float = 0.86,
) -> Match:
    """Match an incoming company against canonical history.

    Auto-merges on rungs 1 and 2 only. Everything else is REPORTED, never
    merged: attaching a colleague's notes to the wrong company is worse than
    asking.
    """
    aliases = aliases or {}

    # Rung 1 — stored identity. Authoritative when present AND unique.
    cid = (company_id or "").strip()
    if cid:
        if cid in canon.ambiguous_ids:
            # Two canonical rows share this id. Picking one would send every
            # update to the first and strand the second.
            return Match("ambiguous", candidates=canon.rows_for_id(cid), reason="duplicate_id")
        if cid in canon.by_id:
            return Match("matched", row=canon.by_id[cid], reason="company id")
        return Match("unmatched", reason="id_not_in_history")

    key = norm_company(name)
    if not key:
        return Match("unmatched", reason="empty_name")

    # Rung 2 — exact normalised name, only when unambiguous.
    hits = canon.by_norm_name.get(key, [])
    if len(hits) == 1:
        return Match("matched", row=hits[0], reason="normalised name")
    if len(hits) > 1:
        return Match("ambiguous", candidates=hits, reason="duplicate_name")

    # Rung 3 — human-maintained alias table.
    if key in aliases:
        target = canon.by_id.get(aliases[key])
        if target is not None:
            return Match("matched", row=target, reason="alias")
        return Match("unmatched", reason="alias_target_missing")

    # Rung 4 — candidate generation ONLY. Never auto-merge.
    cands = [
        r
        for r in canon.rows
        if r.norm_name
        and (
            _token_ratio(key, r.norm_name) >= fuzzy_threshold
            or key.startswith(r.norm_name)
            or r.norm_name.startswith(key)
        )
    ]
    if cands:
        return Match("needs_human", candidates=cands, reason="similar_name")

    return Match("unmatched", reason="new")


def _token_ratio(a: str, b: str) -> float:
    """Dice coefficient over token sets. Deterministic, no dependency."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))
