#!/usr/bin/env python3
"""add-verified: append human-confirmed TSV rows into the canonical CSV.

Reads a UTF-8 TSV payload (A4 columns, Tab-separated, header + rows) from stdin
as JSON {"tsv": "..."}. Appends NEW companies as rows; merges UPDATE rows into
the existing company row (new titles/links/themes appended with next numbering).
Never touches columns 21-22 (First Contact Date, Recall) on existing rows.
Usage: python3 add_verified.py <history.csv> < payload.json
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path


def parse_semicolon_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    return rows[0], rows[1:]


def split_multi(cell: str) -> list[str]:
    """Split a multi-value cell. Canonical uses newline inside quoted fields;
    TSV input uses ' | '. Accept both. Themes use ';' as separator."""
    if not cell.strip():
        return []
    if "\n" in cell:
        return [p.strip() for p in cell.split("\n") if p.strip()]
    return [p.strip() for p in cell.split("|") if p.strip()]


split_numbered = split_multi  # backward-compat alias


def renumber(items: list[str]) -> str:
    import re

    out = []
    seen: set[str] = set()
    for item in items:
        plain = re.sub(r"^\d+\.\s*", "", item.strip())
        key = plain.lower()
        if not plain or key in seen:
            continue
        seen.add(key)
        out.append(f"{len(out) + 1}. {plain}")
    return " | ".join(out)


def main() -> None:
    if len(sys.argv) != 2:
        print(json.dumps({"ok": False, "error": "usage: add_verified.py <history.csv>"}))
        raise SystemExit(1)
    path = Path(sys.argv[1])
    payload = json.loads(sys.stdin.read() or "{}")
    tsv = payload.get("tsv", "")
    lines = [ln for ln in tsv.split("\n") if ln.strip()]
    if len(lines) < 2:
        print(json.dumps({"ok": True, "added": 0, "updated": 0}))
        return
    header = lines[0].split("\t")
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]
    hdr, existing = parse_semicolon_csv(path)
    idx = {name: hdr.index(name) for name in header if name in hdr}
    by_company = {}
    for r in existing:
        if r and r[0].strip():
            by_company[r[0].strip().lower()] = r
    added = updated = 0
    for row in rows:
        company = row.get("Company / Outreach Account", "").strip()
        if not company or company.startswith("["):
            continue  # skip blank lines and stray prefix-only lines
        notes = row.get("Notes", "")
        cells = [row.get(h, "") for h in hdr[: len(header)]]
        # pad to full width
        while len(cells) < len(hdr):
            cells.append("")
        key = company.lower()
        if key not in by_company:
            existing.append(cells)
            by_company[key] = cells
            added += 1
        else:
            # Company known (NEW or UPDATE prefix): merge new roles in
            target = by_company[key]
            merge_into(target, row, hdr)
            updated += 1
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(hdr)
        writer.writerows(existing)
    print(json.dumps({"ok": True, "added": added, "updated": updated}))


def merge_into(target: list[str], row: dict, hdr: list[str]) -> None:
    def col(name: str) -> int:
        return hdr.index(name)

    # Append titles/links/locations/themes/workmodes/sources with renumbering.
    # Titles+links+locations share one numbering index: the i-th title matches
    # the i-th link and i-th location. Titles drive the merge; links/locations
    # at the same position ride along so indices never desync.
    import re

    def plain(s: str) -> str:
        return re.sub(r"^\d+\.\s*", "", s.strip())

    new_titles = split_multi(row.get("Matching Job Titles", ""))
    new_links = split_multi(row.get("Job Links", ""))
    new_locs = split_multi(row.get("Locations", ""))
    cur_titles = split_multi(target[col("Matching Job Titles")])
    cur_links = split_multi(target[col("Job Links")])
    cur_locs = split_multi(target[col("Locations")])
    cur_set = {plain(c).lower() for c in cur_titles}
    for i, t in enumerate(new_titles):
        if plain(t).lower() in cur_set:
            continue
        cur_titles.append(t)
        if i < len(new_links):
            cur_links.append(new_links[i])
        if i < len(new_locs):
            cur_locs.append(new_locs[i])
        cur_set.add(plain(t).lower())
    target[col("Matching Job Titles")] = "\n".join(renumber(cur_titles).split(" | "))
    target[col("Job Links")] = "\n".join(renumber(cur_links).split(" | "))
    # Locations in canonical CSV are plain newline-separated, no numbering
    import re as _re

    target[col("Locations")] = "\n".join(_re.sub(r"^\d+\.\s*", "", c).strip() for c in cur_locs)
    for name in ["Strategic-fit Themes", "Work Modes", "Sources / Portals"]:
        if name not in row:
            continue
        sep = ";" if name == "Strategic-fit Themes" else "|"
        cur = [p.strip() for p in target[col(name)].replace("\n", "|").split(sep) if p.strip()]
        new = split_multi(row[name])
        for item in new:
            if plain(item).lower() not in {plain(c).lower() for c in cur}:
                cur.append(item)
        # themes use "; " (canonical), modes/sources use newline (canonical cells)
        joiner = "; " if name == "Strategic-fit Themes" else "\n"
        seen: set[str] = set()
        uniq = []
        for c in cur:
            k = plain(c).lower()
            if k and k not in seen:
                seen.add(k)
                uniq.append(plain(c))
        target[col(name)] = joiner.join(uniq)
    # Role Count = number of titles
    titles = split_multi(target[col("Matching Job Titles")])
    target[col("Role Count")] = str(len(titles))
    # Notes: append new notes
    if row.get("Notes"):
        target[col("Notes")] = (target[col("Notes")] + " | " + row["Notes"]).strip(" |")
    # Verification Status / Last Checked: latest wins
    if row.get("Verification Status"):
        target[col("Verification Status")] = row["Verification Status"]
    if row.get("Last Checked"):
        target[col("Last Checked")] = row["Last Checked"]
    # Curricular Evidence: union of markers (simple concat if different)
    if row.get("Curricular Evidence") and row["Curricular Evidence"] not in target[col("Curricular Evidence")]:
        target[col("Curricular Evidence")] = (target[col("Curricular Evidence")] + "; " + row["Curricular Evidence"]).strip("; ")
    # Never touch: Previously Contacted?, Contact Search Status, Contact Name/Role/Email,
    # Outreach Decision, First Contact Date, Recall — human-owned columns.


main()
