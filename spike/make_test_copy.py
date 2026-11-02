#!/usr/bin/env python3
"""python3 spike/make_test_copy.py --from <Master>/Review.xlsx --to <TEST folder>

A copy of a real Review.xlsx with the contact columns and the notes emptied, so the
probe can test a real workbook without a second copy of anybody's contact details
sitting in a test folder. The source is only read.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

BLANKED = ("Contact Name", "Contact Role", "Contact Email / LinkedIn", "Notes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("--to", required=True)
    args = parser.parse_args()

    target = Path(args.to)
    if not target.is_dir() or "TEST" not in target.resolve().name:
        print(f"REFUSED: {target} is not a test folder (its name must contain TEST)", file=sys.stderr)
        return 2

    workbook = load_workbook(args.source)
    sheet = workbook.worksheets[0]
    columns = {cell.value: cell.column for cell in sheet[2]}
    missing = [name for name in BLANKED if name not in columns]
    if missing:
        print(f"REFUSED: {args.source} has no column {missing}: nothing was copied", file=sys.stderr)
        return 1
    for name in BLANKED:
        for row in range(3, sheet.max_row + 1):
            sheet.cell(row=row, column=columns[name]).value = None
    workbook.save(target / "Review.xlsx")
    print(target / "Review.xlsx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
