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

Commands implemented so far: `doctor`, `stage` (Step A). The rest of the CLI
surface is declared but refuses with a clear message until its step lands.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synced_fs  # noqa: E402
from reconcile import (  # noqa: E402
    MACHINE_LATEST_COLS,
    MACHINE_UNION_COLS,
    DATE_COLUMNS,
    HUMAN_COLS,
    detect_date_format,
    load_aliases,
    load_canonical,
    match_company,
    norm_company,
    parse_date,
    propose_company_id,
    same_value,
    split_column,
)

# --------------------------------------------------------------------------
# A4 column contract
# --------------------------------------------------------------------------

A4_COLUMNS = [
    "Company / Outreach Account",
    "Brands / Business Units",
    "In Italy?",
    "Locations",
    "Master-fit Themes",
    "Matching Job Titles",
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

# Per-role sheet. Restores io.py's original `Role Evidence` design, which the
# flat 22-column projection had destroyed.
ROLE_COLUMNS = [
    "Company / Outreach Account",
    "Brand / Business Unit",
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

COMPANY_SUMMARY_COLUMNS = A4_COLUMNS + ["Company ID", "Role Count (peak)"]

# --------------------------------------------------------------------------
# The human-facing workbook.
#
# 24 columns: the 22 A4 columns with `Notes` SPLIT into `Matching Notes`
# (machine) and `Reviewer Notes` (human), plus `Company ID`.
#
# The split is the point. `Notes` was the one column both sides wrote --
# add_verified.py appended machine text to whatever a colleague had typed,
# joined with ' | ', irreversibly. Latent today (0 of 49 non-empty Notes cells
# contain the marker) but unrecoverable the moment it fires, so it is split
# before the machine ever appends to this file.
#
# Built programmatically rather than from a checked-in .xlsx template: the
# column set, number formats and validation live in code, so they appear in a
# diff instead of inside an opaque binary.
# --------------------------------------------------------------------------

REVIEW_COLUMNS = [
    "Company / Outreach Account",
    "Brands / Business Units",
    "In Italy?",
    "Locations",
    "Master-fit Themes",
    "Matching Job Titles",
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
    "Matching Notes",  # machine
    "Reviewer Notes",  # human
    "Verification Status",
    "Last Checked",
    "First Contact Date",
    "Recall",
    "Company ID",
]

REVIEW_BANNER = (
    "Review file — this one is YOURS. Columns A-R are filled by the machine; "
    "edit only Outreach Decision, Reviewer Notes, Contact * and the dates. "
    "Per-role evidence is in Roles.xlsx. Do not use modern Comments here: "
    "Excel's threaded comments are lost when the machine appends new rows."
)

# Historical `Notes` in the canonical CSV is machine text (every non-empty cell
# carries the [NEW COMPANY]/[pertinente]/Match-score form). It seeds
# `Matching Notes`; `Reviewer Notes` starts empty.
NOTES_SOURCE_COLUMN = "Notes"

# DATE_COLUMNS is defined in reconcile.py (it is column metadata, and
# reconcile.same_value needs it). This is only the display format.
DATE_NUMBER_FORMAT = "DD/MM/YYYY"

# Dropdowns, so colleagues pick a value instead of typing one.
VALIDATION = {
    "Outreach Decision": ["Review", "Yes", "No"],
    "Contact Search Status": ["Not started", "Contacted", "No suitable contact"],
    "Previously Contacted?": ["No", "Yes", "To verify"],
}

# Columns that exist per-role now but had NO home in the flat TSV, so no value
# can be recovered for a historical run. They are present so that future runs
# (once the search output carries them) do not lose them again.
NOT_RECOVERABLE_FROM_FLAT_TSV = {"Alternate / Portal URLs", "Posted / Result Age", "Search Query"}


class StageError(Exception):
    pass


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


def read_tsv_source(tsv_path: str | None) -> str:
    """--tsv PATH, raw TSV on stdin, or {"tsv": "..."} on stdin.

    All three work. The JSON form is kept because it is the contract
    add_verified.py already uses, but `cat run.tsv | sync_export.py stage ...`
    is the natural invocation and must not fail with a JSON parse error.
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
DECISION_VALUES = {"Review", "Yes", "No"}
CONTACT_STATUS_VALUES = {"Not started", "Contacted", "No suitable contact"}


def validate_rows(header: list[str], rows: list[list[str]]) -> list[str]:
    """Check each row's values against the closed sets and types A4 defines for
    those columns.

    Motivated by a real case: `outputs/output-2026-09-11.tsv` has all six rows
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


def _role_values(cells: list[str], index: int, count: int) -> dict[str, str]:
    """Pick the index-th value of the columns that are per-role in the flat TSV.

    `Matching Job Titles`, `Job Links` and `Locations` share one positional
    index (A4: "mantenendo lo stesso indice"). Where a shorter list cannot
    supply the index, fall back to the first entry rather than inventing a
    value — and never fabricate a URL.
    """
    def at(column: str) -> list[str]:
        return split_column(cells[A4_COLUMNS.index(column)], column)

    def pick(column: str) -> str:
        items = at(column)
        if not items:
            return ""
        return items[index] if index < len(items) else (items[0] if count else "")

    return {
        "Job Title": pick("Matching Job Titles"),
        "Location": pick("Locations"),
        "Primary Job URL": pick("Job Links"),
    }


def explode_roles(rows: list[list[str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (role_rows, company_rows)."""
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
            role_rows.append(
                {
                    "Company / Outreach Account": company,
                    "Brand / Business Unit": col("Brands / Business Units"),
                    "Job Title": rv["Job Title"],
                    "Location": rv["Location"],
                    "In Italy?": col("In Italy?"),
                    "Why It Fits": col("Master-fit Themes"),
                    "Primary Job URL": rv["Primary Job URL"],
                    # Present but necessarily empty for a historical run.
                    "Alternate / Portal URLs": "",
                    "Source / Portal": col("Sources / Portals"),
                    "Work Mode": col("Work Modes"),
                    "Curricular Status": col("Curricular Evidence"),
                    "Previously Contacted?": col("Previously Contacted?"),
                    "Verification Status": col("Verification Status"),
                    "Posted / Result Age": "",
                    "Search Query": "",
                    "Date Checked": col("Last Checked"),
                }
            )
    return role_rows, company_rows


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
    check("dir writable", __import__("os").access(d, __import__("os").W_OK))

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

    # A CF formula like `$W2<=TODAY()` compares STRINGS against "03/09/2026" and
    # silently returns the wrong answer while the cell still looks right. Assert
    # the date columns really hold dates.
    review = d / "Review.xlsx"
    if review.exists() and not synced_fs.is_dataless(review):
        try:
            from openpyxl import load_workbook

            wb = load_workbook(review, read_only=True, data_only=True)
            ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
            header = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]
            for col in DATE_COLUMNS:
                if col not in header:
                    continue
                ci = header.index(col)
                bad = []
                for row in ws.iter_rows(min_row=3):
                    v = row[ci].value if ci < len(row) else None
                    if v not in (None, "") and not isinstance(v, datetime):
                        bad.append(str(row[0].value)[:28])
                check(f"Review.xlsx '{col}' holds dates", not bad, f"non-date in: {bad[:4]}" if bad else "")
            wb.close()
        except Exception as exc:  # noqa: BLE001
            check("Review.xlsx date columns readable", False, str(exc)[:120])

    report["dirs"] = {"_machine": str(d / "_machine"), "backups": str(d / "_machine" / "backups")}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_stage(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    synced_fs.ensure_dir(d)
    machine = synced_fs.ensure_dir(d / "_machine")

    text = read_tsv_source(args.tsv)
    header, rows = parse_tsv(text)
    role_rows, company_rows = explode_roles(rows)

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
                if hc in ("Reviewer Notes",):
                    continue
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

    summary = {
        "run_id": run_id,
        "tsv": args.tsv or "<stdin>",
        "validation_problems": problems,
        "companies_in": len(rows),
        "roles_out": len(role_rows),
        "companies_out": len(company_rows),
        "role_columns": len(ROLE_COLUMNS),
        "columns_without_source": sorted(NOT_RECOVERABLE_FROM_FLAT_TSV),
        "target": str(roles_xlsx),
        "never_touched": str(d / "Review.xlsx"),
    }

    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    _write_csv(roles_csv, ROLE_COLUMNS, role_rows)
    _write_csv(companies_csv, A4_COLUMNS, company_rows)
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


def cmd_backfill_ids(args: argparse.Namespace) -> int:
    """Add a `Company ID` column to the canonical CSV.

    Placed immediately after `Recall` so every positional reader that slices
    `hdr[:22]` is unaffected (add_verified.py:79, io.py COMPANY_HEADERS).

    PROPOSE-ONLY for duplicate names. The canonical CSV has 5 names on two rows
    each, and merging them would force a choice between two sets of human-owned
    contact fields. They share a proposed id and are reported for a human to
    resolve; nothing is merged here.
    """
    path = Path(args.history)
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"missing {path}"}, ensure_ascii=False))
        return 2

    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rows:
        print(json.dumps({"ok": False, "error": "empty CSV"}, ensure_ascii=False))
        return 2
    header, data = rows[0], rows[1:]

    if "Company ID" in header:
        idx = header.index("Company ID")
        placement = "existing"
    else:
        anchor = header.index("Recall") + 1 if "Recall" in header else len(header)
        # Only safe to occupy the slot when nothing lives there; otherwise insert.
        if anchor < len(header) and header[anchor].strip():
            header.insert(anchor, "Company ID")
            for r in data:
                r.insert(anchor, "")
            placement = "inserted"
        else:
            while len(header) <= anchor:
                header.append("")
            header[anchor] = "Company ID"
            placement = "appended"
        idx = anchor

    # Keep every row the same width as the header. Rows we do not touch (the
    # stray row, blank filler) must not end up narrower than the header, or the
    # file is internally inconsistent and column-count checks trip on it.
    for r in data:
        while len(r) < len(header):
            r.append("")

    # Group by normalised name so a duplicate pair shares one proposed id.
    groups: dict[str, list[int]] = {}
    strays: list[dict] = []
    for i, r in enumerate(data):
        if not r:
            continue
        name = (r[0] or "").strip()
        if name == "Company / Outreach Account":
            continue
        if not name:
            # A row with content but no company name. The canonical CSV has one
            # of these: an orphan `First Contact Date = 03/09/2026` between
            # Logotel and Doctolib. That is real human data whose owner is lost.
            # Report it; do NOT guess which company it belongs to, and do NOT
            # let it disappear.
            filled = {header[j]: c.strip() for j, c in enumerate(r) if j < len(header) and c.strip()}
            if filled:
                strays.append({"row_index": i, "cells": filled})
            continue
        groups.setdefault(norm_company(name), []).append(i)

    dupes = {k: v for k, v in groups.items() if len(v) > 1}
    assigned = 0
    for key, idxs in groups.items():
        cid = propose_company_id(data[idxs[0]][0])
        for i in idxs:
            while len(data[i]) <= idx:
                data[i].append("")
            if not data[i][idx].strip():
                data[i][idx] = cid
                assigned += 1

    report_path = Path(args.report) if args.report else path.parent / "duplicate-names-report.csv"
    summary = {
        "history": str(path),
        "placement": placement,
        "column_index": idx,
        "rows": len(data),
        "companies": len(groups),
        "ids_assigned": assigned,
        "duplicate_names": len(dupes),
        "duplicate_report": str(report_path),
        "stray_rows": len(strays),
        "trailing_empty_columns_preserved": max(0, len(header) - 23),
    }
    if strays:
        summary["stray_detail"] = strays

    if args.dry_run:
        summary["dry_run"] = True
        summary["duplicate_detail"] = [
            {"name": data[v[0]][0], "rows": v, "shared_id": propose_company_id(data[v[0]][0])}
            for v in dupes.values()
        ]
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    if dupes or strays:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["kind", "company_or_cells", "row_indexes", "shared_proposed_id", "note"])
            for v in dupes.values():
                w.writerow(
                    [
                        "duplicate_name",
                        data[v[0]][0],
                        "|".join(str(i) for i in v),
                        propose_company_id(data[v[0]][0]),
                        "two rows share a name; NOT merged - resolve by hand",
                    ]
                )
            for s in strays:
                w.writerow(
                    [
                        "stray_row",
                        "; ".join(f"{k}={val}" for k, val in s["cells"].items()),
                        s["row_index"],
                        "",
                        "content with no company name; NOT assigned an id - attribute by hand",
                    ]
                )

    backup_dir = path.parent / "_backups"
    synced_fs.write_atomically(
        path,
        lambda tmp: _write_csv_rows(tmp, header, data),
        guard=False,  # a repo CSV, not a live synced workbook
        backup_dir=backup_dir,
    )
    summary["backup_dir"] = str(backup_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _write_csv_rows(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


COLOR_RULES_SPEC = "A4-status-vocabulary v1 (see config/A4-status-vocabulary.proposed.md)"

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

    # 1. Outreach Decision — the primary colour.
    rng = clear("Outreach Decision")
    q = ref("Outreach Decision", 2)
    ws.conditional_formatting.add(
        rng,
        FormulaRule(
            formula=[f'{q}="No"'],
            fill=PatternFill("solid", bgColor="D9D9D9"),
            font=Font(strike=True, color="808080"),
            stopIfTrue=False,
        ),
    )
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[f'{q}="Yes"'], fill=PatternFill("solid", bgColor="C6EFCE"), stopIfTrue=False),
    )
    applied.append(f"Outreach Decision: Yes=green, No=grey+strikethrough  [{rng}]")

    # 2. Recall — due vs scheduled.
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

    # 3. Contact Search Status — the INCONSISTENT worklist.
    # 48 of 118 canonical rows currently contradict themselves (a status of
    # "Not started" alongside a contact date). Colouring it amber turns an
    # existing data-quality problem into a list that shortens itself as
    # colleagues clean it up, at zero cost to the machine.
    rng = clear("Contact Search Status")
    m = ref("Contact Search Status", 2)
    v = ref("First Contact Date", 2)
    inconsistent = (
        f'OR(AND({m}="Not started",{v}<>""),'
        f'AND({m}="No suitable contact",{v}<>""),'
        f'AND({m}="Contacted",{v}=""))'
    )
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[inconsistent], fill=PatternFill("solid", bgColor="FFE699"), stopIfTrue=False),
    )
    applied.append(f"Contact Search Status: inconsistent-with-date=amber  [{rng}]")

    return applied


def _build_review_workbook(path: Path, canon) -> int:
    """Create Review.xlsx, seeded from canonical history. Returns rows written."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Review"

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

    row = 3
    for cr in canon.rows:
        for c, name in enumerate(REVIEW_COLUMNS, start=1):
            if name == "Matching Notes":
                value: object = cr.get(NOTES_SOURCE_COLUMN)
            elif name == "Reviewer Notes":
                value = ""
            elif name in DATE_COLUMNS:
                # Real dates, not text — see DATE_NUMBER_FORMAT's comment.
                parsed = parse_date(cr.get(name))
                value = parsed if parsed is not None else cr.get(name)
                if parsed is not None:
                    ws.cell(row, c).number_format = DATE_NUMBER_FORMAT
            else:
                value = cr.get(name)
            ws.cell(row, c, value if value not in (None, "") else None)
        row += 1

    for col_name, options in VALIDATION.items():
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(options) + '"',
            allow_blank=True,
            showDropDown=False,
        )
        ws.add_data_validation(dv)
        letter = get_column_letter(REVIEW_COLUMNS.index(col_name) + 1)
        dv.add(f"{letter}3:{letter}{CF_RANGE_ROWS}")

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
    apart again."""
    from reconcile import Canonical, CanonicalRow

    header = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]
    rows = []
    for r in range(3, ws.max_row + 1):
        cells = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if not str(cells[0] or "").strip():
            continue
        rows.append(
            CanonicalRow(index=r, cells=["" if v is None else str(v) for v in cells], header=header)
        )
    return Canonical(header=header, rows=rows).finalize()


def _first_free_row(ws) -> int:
    """First row from 3 down whose company cell is empty. Scans rather than using
    max_row+1 so a deleted or gapped row is reused instead of leaving a hole."""
    for r in range(3, ws.max_row + 2):
        if not str(ws.cell(r, 1).value or "").strip():
            return r
    return ws.max_row + 1


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

    aliases = load_aliases(d.parent / "company-aliases.csv")
    wb = load_workbook(target, rich_text=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    existing = _review_as_canonical(ws)
    header = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]

    to_add: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    for row in companies:
        name = (row.get("Company / Outreach Account") or "").strip()
        if not name:
            continue
        m = match_company(name, existing, aliases=aliases)
        if m.kind == "matched":
            continue  # already present
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
        "already_present": len(companies) - len(to_add) - len(deferred),
        "to_append": len(to_add),
        # Always present, so callers never have to branch on whether anything was
        # written. Stays 0 on the dry-run and on every refusal path.
        "appended": 0,
        "deferred": len(deferred),
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
        row_i = _first_free_row(ws)
        for company in to_add:
            for c, col_name in enumerate(header, start=1):
                # Ownership decides the value. NOTE: ownership and date-ness are
                # different axes -- `Last Checked` is machine-owned (A4
                # MACHINE_LATEST_COLS) while `First Contact Date`/`Recall` are
                # human-owned, and all three are date columns. Blanking every
                # DATE_COLUMNS cell would wrongly drop the run date.
                if col_name == "Matching Notes":
                    value: object = company.get(NOTES_SOURCE_COLUMN, "")
                elif col_name == "Reviewer Notes":
                    value = ""  # the colleague's column; the machine never writes it
                elif col_name == "Company ID":
                    # A NEW company has no id yet, so propose one and store it --
                    # otherwise the next run can only match it by name, and `pull`
                    # has no key to write back to. Stored, never recomputed.
                    value = company.get("Company ID") or propose_company_id(company["Company / Outreach Account"])
                elif col_name in HUMAN_COLS:
                    # A4's defaults: no invented contact, no invented prior contact,
                    # no guessed date, and the decision stays with a human.
                    value = {
                        "Contact Search Status": "Not started",
                        "Outreach Decision": "Review",
                        "Previously Contacted?": "To verify",
                    }.get(col_name, "")
                else:
                    value = company.get(col_name, "")

                cell = ws.cell(row_i, c)
                if value in (None, ""):
                    continue
                # Values only. Not a style, not a validation rule.
                if col_name in DATE_COLUMNS:
                    parsed = parse_date(str(value))
                    if parsed is not None:
                        cell.value = parsed
                        cell.number_format = DATE_NUMBER_FORMAT
                        continue
                cell.value = value
            row_i += 1
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
                w.writerow([company.get(c, "") for c in REVIEW_COLUMNS])
        summary.update(
            {
                "appended": 0,
                "reason": exc.reason,
                "detail": exc.detail,
                "sidecar": str(sidecar),
                "note": f"nothing written to Review.xlsx; {len(to_add)} row(s) left in the sidecar",
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
# The canonical CSV still calls the machine prose column `Notes`; Review.xlsx
# calls it `Matching Notes` because it sits beside `Reviewer Notes` there. The
# A4 proposal renames it in the canonical file too, but that is another
# whole-column migration like the Themes rename and has not been approved, so
# the mapping is explicit here instead of assumed.
PULL_COLUMN_MAP = {"Matching Notes": "Notes"}

# Columns `pull` writes back. Human-owned only -- machine columns reach the
# canonical file through add_verified.py / the TSV path, not through Review.xlsx.
# `Reviewer Notes` is included because it has no other home.
PULL_COLUMNS = [c for c in HUMAN_COLS if c != "Reviewer Notes"] + ["Reviewer Notes"]

# Appended to the canonical CSV by `pull` if absent, so a colleague's note has
# somewhere to land without fusing into the machine prose.
REVIEWER_NOTES_COLUMN = "Reviewer Notes"


def _ensure_column(header: list[str], data: list[list[str]], name: str) -> int:
    """Append `name` to the header (never insert) and pad rows to match.

    Appending keeps every positional reader that slices `hdr[:22]` intact --
    same reasoning as `Company ID`.
    """
    if name in header:
        return header.index(name)
    idx = len(header)
    header.append(name)
    for r in data:
        while len(r) < len(header):
            r.append("")
    return idx


def _harvest_review(d: Path, canon) -> dict:
    """Read Review.xlsx and match its rows to canonical history.

    Read-only: this is the audit path, and `pull` reuses it. Returns matched
    updates, rows with no canonical counterpart, and conflicts -- where the
    colleague's value differs from a NON-EMPTY canonical value, which is
    reported rather than silently resolved.
    """
    from openpyxl import load_workbook

    aliases = load_aliases(d.parent / "company-aliases.csv")
    wb = load_workbook(d / "Review.xlsx", read_only=True, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    header = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]

    updates: list[dict] = []
    new_rows: list[dict] = []
    conflicts: list[dict] = []

    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row or not row[0]:
            continue
        values = {header[i]: row[i] for i in range(min(len(header), len(row)))}
        name = str(values.get("Company / Outreach Account") or "").strip()
        cid = str(values.get("Company ID") or "").strip()
        m = match_company(name, canon, aliases=aliases, company_id=cid)

        if m.kind == "matched":
            for col in PULL_COLUMNS:
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
                canonical_col = PULL_COLUMN_MAP.get(col, col)
                current = m.row.get(canonical_col).strip()
                # Compare as VALUES, not strings: a date written to the workbook
                # comes back as '2026-09-03 00:00:00' against the CSV's
                # '03/09/2026', and a string compare flags every row.
                if same_value(col, current, incoming):
                    continue  # already in agreement -- nothing to write, nothing to report
                if current:
                    conflicts.append(
                        {"company": m.row.company, "column": col, "canonical": current[:90], "review": incoming[:90]}
                    )
                updates.append(
                    {"row_index": m.row.index, "company": m.row.company, "column": col, "value": incoming,
                     "existing": current}
                )
        elif m.kind == "unmatched":
            new_rows.append({"company": name, "values": values})
        else:
            conflicts.append(
                {"company": name, "column": "(identity)", "canonical": m.reason, "review": f"candidates: {[c.company for c in m.candidates][:3]}"}
            )
    wb.close()
    return {"updates": updates, "new_rows": new_rows, "conflicts": conflicts}


def cmd_harvest(args: argparse.Namespace) -> int:
    """Report what colleagues decided. Never writes. This is the audit command."""
    d = Path(args.dir)
    if not (d / "Review.xlsx").exists():
        print(json.dumps({"ok": False, "error": f"{d / 'Review.xlsx'} does not exist"}, ensure_ascii=False))
        return 2
    canon = load_canonical(args.history)
    h = _harvest_review(d, canon)
    out = {
        "review": str(d / "Review.xlsx"),
        "canonical": str(args.history),
        "updates": len(h["updates"]),
        "companies_updated": len({u["row_index"] for u in h["updates"]}),
        "new_companies": len(h["new_rows"]),
        "conflicts": len(h["conflicts"]),
    }
    if args.verbose:
        out["update_detail"] = h["updates"]
        out["new_detail"] = [r["company"] for r in h["new_rows"]]
    if h["conflicts"]:
        out["conflict_detail"] = h["conflicts"][:40]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """Write colleagues' decisions from Review.xlsx into the canonical CSV.

    Human values win, but overwriting a NON-EMPTY canonical value is recorded in
    the report, never silent. Uses the same matcher and splitter as everything
    else, which is what finally makes the readers agree.
    """
    d = Path(args.dir)
    if not (d / "Review.xlsx").exists():
        print(json.dumps({"ok": False, "error": f"{d / 'Review.xlsx'} does not exist"}, ensure_ascii=False))
        return 2

    path = Path(args.history)
    raw = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"))
    header, data = raw[0], raw[1:]
    _ensure_column(header, data, REVIEWER_NOTES_COLUMN)

    canon = load_canonical(path)
    h = _harvest_review(d, canon)

    # Apply updates. `CanonicalRow.index` is the raw data-row index, so it maps
    # straight back onto `data`.
    applied = 0
    for u in h["updates"]:
        target_col = PULL_COLUMN_MAP.get(u["column"], u["column"])
        if target_col not in header:
            continue
        r = data[u["row_index"]]
        while len(r) < len(header):
            r.append("")
        ci = header.index(target_col)
        if same_value(u["column"], r[ci], u["value"]):
            continue
        newval = u["value"]
        if u["column"] in DATE_COLUMNS:
            parsed = parse_date(newval) or parse_date(newval.split(" ")[0])
            if parsed is not None:
                # Keep the convention already in the cell, so a column does not
                # end up holding ISO and DD/MM/YYYY side by side.
                fmt = detect_date_format(r[ci]) or detect_date_format(u.get("existing", "")) or "%Y-%m-%d"
                newval = parsed.strftime(fmt)
        r[ci] = newval
        applied += 1

    # Companies in Review but not in canonical are new history: append them whole.
    added = 0
    for entry in h["new_rows"]:
        values = entry["values"]
        row_out = [""] * len(header)
        for col in header:
            v = values.get(col)
            if v in (None, ""):
                continue
            row_out[header.index(col)] = v.isoformat() if isinstance(v, date) else str(v)
        row_out[0] = entry["company"]
        data.append(row_out)
        added += 1

    summary = {
        "review": str(d / "Review.xlsx"),
        "canonical": str(path),
        "cells_updated": applied,
        "companies_appended": added,
        "conflicts": len(h["conflicts"]),
    }
    if h["conflicts"]:
        summary["conflict_detail"] = h["conflicts"][:40]

    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    if not applied and not added:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    backup_dir = path.parent / "_backups"
    synced_fs.write_atomically(
        path,
        lambda tmp: _write_csv_rows(tmp, header, data),
        guard=False,  # a repo CSV, not a live synced workbook
        backup_dir=backup_dir,
    )
    summary["backup_dir"] = str(backup_dir)

    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with rp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["kind", "company", "column", "canonical_value", "review_value"])
            for c in h["conflicts"]:
                w.writerow(["conflict", c["company"], c["column"], c["canonical"], c["review"]])
        summary["report"] = str(rp)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _not_implemented(step: str):
    def run(_args: argparse.Namespace) -> int:
        print(json.dumps({"ok": False, "error": f"not implemented yet ({step})"}, ensure_ascii=False))
        return 2

    return run


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
        ("pull", cmd_pull, "write colleagues' decisions back into the canonical CSV", True),
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
        if name == "harvest":
            q.add_argument("--verbose", action="store_true")
        if name == "pull":
            q.add_argument("--report", help="where to write the conflict report")
        q.set_defaults(func=fn)

    q = sub.add_parser("backfill-ids", help="add a Company ID column to the canonical CSV (propose-only for duplicates)")
    q.add_argument("--history", required=True)
    q.add_argument("--report", help="where to write duplicate-names-report.csv")
    q.add_argument("--dry-run", action="store_true")
    q.set_defaults(func=cmd_backfill_ids)

    args = ap.parse_args()
    try:
        return args.func(args)
    except (StageError, synced_fs.GuardFailure) as exc:
        reason = getattr(exc, "reason", "stage_error")
        print(json.dumps({"ok": False, "reason": reason, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
