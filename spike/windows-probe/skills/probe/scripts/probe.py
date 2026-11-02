#!/usr/bin/env python3
"""Measure what the plugin plan needs to know about this computer. Throwaway.

Every result is appended to <master>/probe-report.jsonl and printed as one line:
`T5-write PASS {...}`. Exit 0 means "recorded", even when the result is FAIL;
exit 2 means the probe refused to run. It only ever writes inside a folder whose
own name contains TEST, and it never reads or prints a cell of Review.xlsx.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat as stat_mod
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PACKED_ENGINE = SCRIPTS.parent / "engine"
REPO_ENGINE = SCRIPTS.parents[4] / "engine" if len(SCRIPTS.parents) > 4 else PACKED_ENGINE
MIN_PYTHON = (3, 10)
LABELS = ("normal", "excel-open", "online-only")


def engine_dir() -> Path:
    """The copy packed into the plugin, or the repo's own when run from a checkout."""
    return PACKED_ENGINE if PACKED_ENGINE.exists() else REPO_ENGINE


def engine_python_dir() -> Path:
    """Puts the engine's Python, and its packed dependencies if any, on sys.path."""
    python_dir = engine_dir() / "python"
    for path in (python_dir / "vendor", python_dir):
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return python_dir


def require_test_folder(path: str) -> Path:
    """A folder's OWN name must say TEST: a real Master folder is never written to."""
    folder = Path(path)
    if not folder.is_dir():
        print(f"REFUSED: {folder} is not a folder", file=sys.stderr)
        raise SystemExit(2)
    if "TEST" not in folder.resolve().name:
        print(f"REFUSED: {folder.name} is not a test folder (its name must contain TEST)", file=sys.stderr)
        raise SystemExit(2)
    return folder


def record(master: Path, test_id: str, status: str, detail: dict) -> None:
    row = {
        "test": test_id,
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "detail": detail,
    }
    with open(master / "probe-report.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{test_id} {status} {json.dumps(detail, ensure_ascii=False)}", flush=True)


def run_tool(cmd: list[str], env: dict | None = None) -> tuple[int | None, str]:
    """(exit code, stdout + stderr). A missing program is an answer, not a crash."""
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=env
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return res.returncode, res.stdout + res.stderr


def openpyxl_source() -> tuple[str | None, str | None]:
    """(where openpyxl came from, its version), or (None, None) if it cannot be imported."""
    engine_python_dir()
    try:
        import openpyxl
    except ImportError:
        return None, None
    origin = "vendor" if "vendor" in Path(openpyxl.__file__).parts else "system"
    return origin, openpyxl.__version__


def is_writable(folder: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def cmd_env(args: argparse.Namespace) -> None:
    master = require_test_folder(args.master)
    missing: list[str] = []

    if sys.version_info[:2] < MIN_PYTHON:
        missing.append("python>=3.10")

    node = shutil.which("node")
    node_version = run_tool([node, "--version"])[1].strip() if node else None
    if not node:
        missing.append("node")

    source, version = openpyxl_source()
    if source is None:
        missing.append("openpyxl")

    engine = engine_dir()
    if node:
        code, output = run_tool([node, str(engine / "lib" / "cli.js")])
        if code is None or "discover" not in output:
            missing.append("engine cli.js")
    python_env = {**os.environ, "PYTHONPATH": str(engine / "python" / "vendor")}
    code, output = run_tool([sys.executable, str(engine / "python" / "sync_export.py"), "--help"], python_env)
    if code != 0:
        missing.append("engine sync_export.py")

    detail = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "node_version": node_version,
        "openpyxl_source": source,
        "openpyxl_version": version,
        "skill_dir_writable": is_writable(SCRIPTS),
        "missing": missing,
    }
    record(master, "T2", "FAIL" if missing else "PASS", detail)


def check_folders(master: Path, config: Path) -> None:
    unreadable = []
    for name in ("A1-regole-ricerca.md", "A4-regole-registrazione.md"):
        try:
            (config / name).read_text(encoding="utf-8")
        except OSError as exc:
            unreadable.append(f"{name}: {type(exc).__name__}")
    marker = master / f"probe-marker-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.txt"
    write_error = None
    try:
        marker.write_text("Check that this file appears on OneDrive.\n", encoding="utf-8")
    except OSError as exc:
        write_error = f"{type(exc).__name__}: {exc}"
    detail = {"config_unreadable": unreadable, "marker": marker.name, "write_error": write_error}
    record(master, "T4", "FAIL" if unreadable or write_error else "PASS", detail)


def check_writes(master: Path) -> None:
    engine_python_dir()
    import synced_fs

    detail: dict = {}
    try:
        synced_fs.write_atomically(
            master / "probe-atomic.txt", lambda tmp: tmp.write_text("atomic\n", encoding="utf-8")
        )
        detail["atomic_write"] = "ok"
    except Exception as exc:  # the type is the finding, whatever it is
        detail["atomic_write"] = f"{type(exc).__name__}: {exc}"

    review = master / "Review.xlsx"
    if not review.exists():
        detail["roundtrip"] = "Review.xlsx test copy is missing"
    elif synced_fs.is_dataless(review):
        detail["roundtrip"] = "Review.xlsx is online-only: make it available offline first"
    elif openpyxl_source()[0] is None:
        detail["roundtrip"] = "openpyxl unavailable"
    else:
        from openpyxl import load_workbook

        try:
            workbook = load_workbook(review)
            synced_fs.write_atomically(master / "probe-roundtrip.xlsx", lambda tmp: workbook.save(tmp))
            detail["roundtrip"] = "ok"
        except Exception as exc:
            detail["roundtrip"] = f"{type(exc).__name__}: {exc}"

    passed = detail["atomic_write"] == "ok" and detail["roundtrip"] == "ok"
    record(master, "T5-write", "PASS" if passed else "FAIL", detail)


def cmd_fs(args: argparse.Namespace) -> None:
    master = require_test_folder(args.master)
    check_folders(master, Path(args.config))
    check_writes(master)


def raw_stat(path: Path) -> dict:
    st = os.stat(path)
    fields = ("st_size", "st_blocks", "st_flags", "st_file_attributes", "st_reparse_tag")
    out = {name: getattr(st, name) for name in fields if hasattr(st, name)}
    out["regular_file"] = stat_mod.S_ISREG(st.st_mode)
    return out


def cmd_state(args: argparse.Namespace) -> None:
    master = require_test_folder(args.master)
    engine_python_dir()
    import synced_fs

    test_id = f"T5-{args.label}"
    review = master / "Review.xlsx"
    if not review.exists():
        record(master, test_id, "FAIL", {"reason": "Review.xlsx test copy is missing"})
        return

    # One non-recursive listing: walking this mount is what makes it slow.
    locks = [name for name in os.listdir(master) if name.startswith(synced_fs.EXCEL_LOCK_PREFIX)]
    detail: dict = {"label": args.label, "stat": raw_stat(review), "lock_files": locks}
    try:
        synced_fs.assert_writable(review)
        detail["guard"] = "allowed"
    except synced_fs.GuardFailure as exc:
        detail["guard"] = f"refused:{exc.reason}"
    except Exception as exc:
        detail["guard"] = f"crashed:{type(exc).__name__}"

    if args.label == "excel-open":
        # If the guard ever misses the lock, does the operating system stop the write
        # anyway? This is the test copy, and the bytes written back are its own.
        try:
            data = review.read_bytes()
            synced_fs.write_atomically(review, lambda tmp: tmp.write_bytes(data), guard=False)
            detail["replace_while_open"] = "ok"
        except Exception as exc:
            detail["replace_while_open"] = type(exc).__name__

    if args.label == "normal":
        passed = detail["guard"] == "allowed"
    else:
        passed = detail["guard"].startswith("refused:")
    record(master, test_id, "PASS" if passed else "FAIL", detail)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    env = sub.add_parser("env", help="T2: what can run here")
    env.add_argument("--master", required=True)
    env.set_defaults(func=cmd_env)

    fs = sub.add_parser("fs", help="T4 and T5-write: the attached folders")
    fs.add_argument("--master", required=True)
    fs.add_argument("--config", required=True)
    fs.set_defaults(func=cmd_fs)

    state = sub.add_parser("state", help="T5-<label>: the guards against Review.xlsx in this state")
    state.add_argument("--master", required=True)
    state.add_argument("--label", required=True, choices=LABELS)
    state.set_defaults(func=cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    # A Windows console is not UTF-8, and one unencodable character must not end a test.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
