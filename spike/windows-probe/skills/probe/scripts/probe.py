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
import re
import shutil
import stat as stat_mod
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PACKED_ENGINE = SCRIPTS.parent / "engine"
REPO_ENGINE = SCRIPTS.parents[4] / "engine" if len(SCRIPTS.parents) > 4 else PACKED_ENGINE
MIN_PYTHON = (3, 10)
LABELS = ("normal", "excel-open", "online-only")

# The same request the engine sends: engine/src/discovery/http.ts.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}
# http.ts's BLOCKED_MARKERS, unwidened: "captcha" alone matches legitimate pages.
CHALLENGE_MARKERS = (
    "cf-challenge",
    "challenge-platform",
    "unusual traffic",
    "access denied",
    "request blocked",
    "just a moment...",
    "verifying you are human",
)
DEFAULT_LINKEDIN = "https://www.linkedin.com"
# A page the engine verified on the 2026-11-02 run (its employer-checks.csv).
DEFAULT_EMPLOYER = "https://www.re-lab.it/career-archive/career-single?career=service-design-intern-157064"
SEARCH_PATH = "/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=design+internship&location=Milan&start=0"
RETRY_AFTER_MINUTES = 20


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


def classify_response(status: int | None, body: str, error: str | None) -> str:
    """Why a page came back as it did. A 403 from the sandbox's own proxy and a 403
    from the site are different problems with different owners, so they stay apart."""
    if error is not None or status is None:
        return "network_error"
    if status == 429:
        return "rate_limited"
    if status == 403:
        return "allowlist_blocked" if "blocked-by-allowlist" in body else "forbidden"
    head = body[:20000].lower()
    if any(marker in head for marker in CHALLENGE_MARKERS):
        return "challenge"
    return "ok" if 200 <= status < 300 else "http_error"


def fetch(url: str) -> tuple[str, str]:
    """(classification, body). Never raises for anything the network can do."""
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            body = res.read().decode("utf-8", "replace")
            return classify_response(res.status, body, None), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return classify_response(exc.code, body, None), body
    except (OSError, ValueError) as exc:
        return classify_response(None, "", f"{type(exc).__name__}: {exc}"), ""


def cmd_net(args: argparse.Namespace) -> None:
    master = require_test_folder(args.master)
    base = args.linkedin_base.rstrip("/")
    detail: dict = {"posting": "skipped"}

    # At most two requests to LinkedIn, and none after it has said 429.
    search, page = fetch(base + SEARCH_PATH)
    job_id = re.search(r"urn:li:jobPosting:(\d+)", page) if search == "ok" else None
    detail["search"] = "no_cards" if search == "ok" and not job_id else search
    if job_id:
        time.sleep(args.pause)
        posting, page = fetch(f"{base}/jobs-guest/jobs/api/jobPosting/{job_id.group(1)}")
        has_text = "show-more-less-html__markup" in page
        detail["posting"] = "no_description" if posting == "ok" and not has_text else posting

    detail["employer"] = fetch(args.employer_url)[0]

    if "rate_limited" in (detail["search"], detail["posting"]):
        detail["retry_after_minutes"] = RETRY_AFTER_MINUTES
        status = "INCONCLUSIVE"
    elif all(detail[key] == "ok" for key in ("search", "posting", "employer")):
        status = "PASS"
    else:
        status = "FAIL"
    record(master, "T3", status, detail)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    env = sub.add_parser("env", help="T2: what can run here")
    env.add_argument("--master", required=True)
    env.set_defaults(func=cmd_env)

    net = sub.add_parser("net", help="T3: can this sandbox reach LinkedIn and an employer page")
    net.add_argument("--master", required=True)
    net.add_argument("--linkedin-base", default=DEFAULT_LINKEDIN)
    net.add_argument("--employer-url", default=DEFAULT_EMPLOYER)
    net.add_argument("--pause", type=float, default=10.0)
    net.set_defaults(func=cmd_net)

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
