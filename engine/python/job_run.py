#!/usr/bin/env python3
"""One entry point for a search run, so that nobody has to know the command order.

    python3 python/job_run.py masters
    python3 python/job_run.py prepare --master "Strategic design ED.28"
    python3 python/job_run.py cards     --master "..." --run <name>
    python3 python/job_run.py shortlist --master "..." --run <name> --ids <id> ...
    python3 python/job_run.py read    --master "..." --run <name> [--shortlist file]
    python3 python/job_run.py publish --master "..." --run <name> [--confirm]

Between `read` and `publish` the agent judges each description and writes verdicts.json;
that judgement is the one step this deliberately does not do. `publish` stops before
touching Review.xlsx until it is called again with --confirm.

A stop prints {"stop": <code>, "detail": ...} and exits 3. The code is for whoever
explains it to a colleague; the words belong to them.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The plugin packs openpyxl beside the engine, for a computer that has none installed.
VENDOR = HERE / "vendor"
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
ENGINE = HERE.parent
CONFIG_ROOT = ENGINE.parent / "config"
CLI = ENGINE / "lib" / "cli.js"
SYNC = HERE / "sync_export.py"
A1_NAME = "A1-regole-ricerca.md"

import build_tsv  # noqa: E402  (after the vendor path)

INTERNSHIP_TERMS = ["stage", "internship"]
COOLDOWN_MINUTES = 20
MAX_COOLDOWNS = 12
TOP_K = 200
# A posting dated the day of the last run may have appeared after it searched.
RECENCY_OVERLAP_DAYS = 3
AUTO = object()


class Stop(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class Master:
    name: str
    folder: Path
    a2: Path
    a2_text: str
    a3_text: str
    master_id: str
    edition: str
    dir: Path


def _field(text: str, name: str) -> str | None:
    m = re.search(rf'^\W*{name}\W*:\W*?([^\s"*`]+[^"*`\n]*)', text, re.M)
    return m.group(1).strip() if m else None


def _yaml_list(text: str, name: str) -> list[str]:
    m = re.search(rf"^(\s*){name}:\s*\n((?:\1\s+- .*\n?)+)", text, re.M)
    return [line.split("- ", 1)[1].strip() for line in m.group(2).splitlines()] if m else []


def find_config_root(start: Path) -> Path:
    """config/ stays where colleagues edit it, and the packed engine is not beside it,
    so it is looked for from the folder the session was opened in: that folder, the
    ones above it, and a `talent-place` beside any of them. A1 is what makes a folder
    the config: one merely called config is not taken."""
    start = Path(start).resolve()
    for folder in (start, *start.parents):
        for candidate in (folder / "config", folder / "talent-place" / "config"):
            if (candidate / A1_NAME).is_file():
                return candidate
    raise Stop("config_not_found", f"no config/{A1_NAME} at or above {start}")


def default_config_root() -> Path:
    return CONFIG_ROOT if (CONFIG_ROOT / A1_NAME).is_file() else find_config_root(Path.cwd())


def masters(*, config_root=None) -> dict:
    """Every Master that can be asked for, and whether a run could start for it."""
    config_root = Path(config_root or default_config_root())
    rows = []
    for folder in sorted(p for p in config_root.iterdir() if (p / "A3-cohort.yaml").exists()):
        try:
            m = resolve_master(folder.name, config_root)
            rows.append({"master": folder.name, "ready": True, "folder": str(m.dir), "problem": ""})
        except Stop as stop:
            rows.append({"master": folder.name, "ready": False, "folder": "", "problem": f"{stop.code}: {stop.detail}"})
    return {"config_root": str(config_root), "masters": rows}


def resolve_master(name: str, config_root: Path = CONFIG_ROOT) -> Master:
    config_root = Path(config_root)
    known = sorted(p.name for p in config_root.iterdir() if (p / "A3-cohort.yaml").exists())
    if name not in known:
        raise Stop("master_unknown", f"{name!r}; available: {', '.join(known)}")
    folder = config_root / name
    a2s = sorted(folder.glob("A2-profilo-*.md"))
    if len(a2s) != 1:
        raise Stop("a2_missing", f"{folder}: expected one A2, found {len(a2s)}")
    a2_text = a2s[0].read_text(encoding="utf-8")
    a3_text = (folder / "A3-cohort.yaml").read_text(encoding="utf-8")
    a2_id, a3_id = _field(a2_text, "master_id"), _field(a3_text, "master_id")
    if not a2_id or a2_id != a3_id:
        raise Stop("master_id_mismatch", f"A2 says {a2_id!r}, A3 says {a3_id!r}")
    history_file = _field(a3_text, "history_file")
    if not history_file:
        raise Stop("history_file_missing", str(folder / "A3-cohort.yaml"))
    target = (folder / history_file).parent
    if not target.is_dir():
        raise Stop("master_dir_missing", str(target))
    return Master(name, folder, a2s[0], a2_text, a3_text, a3_id, _field(a3_text, "edition") or "", target)


def run_config(m: Master, recency_days: int | None, locations: list[str] | None = None) -> dict:
    areas = {
        area: v["terms"]
        for area, v in build_tsv.parse_a2(m.a2_text).items()
        if v["terms"] and not v["presence"].lower().startswith("non prevista")
    }
    false_friends: list[str] = []
    for line in re.findall(r"`termini:`\s*(.+)", m.a2_text):
        false_friends += [t.strip() for t in line.split(";") if t.strip()]
    cfg = {
        "masterId": m.master_id,
        "edition": m.edition,
        "areas": areas,
        "internshipTerms": INTERNSHIP_TERMS,
        "locations": locations or _yaml_list(m.a3_text, "geography_priority"),
        "falseFriends": false_friends,
        "admittedLanguages": _yaml_list(m.a3_text, "job_languages"),
        "topK": TOP_K,
        "cooldownMinutes": COOLDOWN_MINUTES,
        "maxCooldowns": MAX_COOLDOWNS,
    }
    if recency_days is not None:
        cfg["recencyDays"] = recency_days
    return cfg


def _runs(m: Master) -> Path:
    return m.dir / "_machine" / "runs"


def _source_failed(run: Path) -> bool:
    report = json.loads((run / "run-report.json").read_text(encoding="utf-8"))
    return any(s.get("status") != "ok" for s in report.get("sources", []))


def recency_days(m: Master, today: str) -> int | None:
    """Days back to the last run that finished its search, with some overlap. A fixed
    window would quietly miss postings whenever the gap was longer, and A1 does not
    limit a search to recent postings: with no finished run there is no window."""
    runs = _runs(m)
    if not runs.is_dir():
        return None
    for run in sorted(runs.iterdir(), reverse=True):
        date = run.name[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or date >= today:
            continue
        if not (run / "run-report.json").exists() or _source_failed(run):
            continue
        gap = dt.date.fromisoformat(today) - dt.date.fromisoformat(date)
        return gap.days + RECENCY_OVERLAP_DAYS
    return None


def _linkedin_place(location: str) -> str:
    # Mirrors linkedinLocation in linkedin-guest.ts, which builds the checkpoint key.
    return "European Union" if re.fullmatch(r"e\.?u\.?", location.strip(), re.I) else location


def coverage(run: Path, cfg: dict) -> dict:
    """What was searched and what was not, which are different from finding nothing."""
    done: dict[str, int] = {}
    path = Path(run) / "checkpoint.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            done[entry["key"]] = len(entry.get("cards", []))
    places = list(dict.fromkeys(_linkedin_place(l) for l in cfg["locations"]))
    window = cfg.get("recencyDays", "")
    per_area, missing, planned, searched = {}, [], 0, 0
    for area, terms in cfg["areas"].items():
        row = {"searched": 0, "planned": 0, "cards": 0}
        for term in terms:
            for suffix in cfg["internshipTerms"]:
                query = f"{term} {suffix}".strip()
                for place in places:
                    row["planned"] += 1
                    key = f"{query} — {place} — {window}"
                    if key in done:
                        row["searched"] += 1
                        row["cards"] += done[key]
                    else:
                        missing.append(f"{query} — {place}")
        per_area[area] = row
        planned += row["planned"]
        searched += row["searched"]
    return {"planned": planned, "searched": searched, "not_searched": missing, "per_area": per_area}


def run_step(cmd: list, **kw) -> subprocess.CompletedProcess:
    # UTF-8 both ways: a Windows console's own encoding cannot print every company name,
    # and a child that fails to print its JSON looks like a child that failed.
    env = {**os.environ, "PYTHONUTF8": "1"}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(VENDOR), os.environ.get("PYTHONPATH", "")]))
    return subprocess.run(
        [str(c) for c in cmd], cwd=ENGINE, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, **kw
    )


def _kernel32():
    import ctypes

    return ctypes.windll.kernel32


@contextlib.contextmanager
def keep_awake():
    """Windows' half of `_awake`: ask the system not to sleep while a step runs. Asking
    can fail and the run still has `--resume`, so a failure here never stops it. It does
    not hold a laptop awake with its lid closed."""
    kernel = None
    if sys.platform == "win32":
        try:
            kernel = _kernel32()
            kernel.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except Exception:  # noqa: BLE001
            kernel = None
    try:
        yield
    finally:
        if kernel is not None:
            kernel.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS


def _awake(cmd: list) -> list:
    """A sleeping machine stops the run. This is macOS's half; `keep_awake` is Windows'."""
    return (["caffeinate", "-i"] + cmd) if shutil.which("caffeinate") else cmd


def _json_of(proc: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {}


def _tail(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "")[-600:]


def run_name(m: Master, today: str) -> str:
    return f"{today}-{m.master_id}-{m.edition.replace('.', '')}"


def prepare(name: str, *, config_root=CONFIG_ROOT, today: str | None = None, days=AUTO, locations=None) -> dict:
    today = today or dt.date.today().isoformat()
    m = resolve_master(name, config_root)
    run = _runs(m) / run_name(m, today)
    run.mkdir(parents=True, exist_ok=True)

    doctor = _json_of(run_step([sys.executable, SYNC, "doctor", "--dir", m.dir]))
    history = run / "history.csv"
    proc = run_step([sys.executable, SYNC, "export-history", "--dir", m.dir, "--out", history])
    if proc.returncode != 0:
        raise Stop("history_failed", _tail(proc))

    config = run / "run.json"
    # A resumed run keeps its config, because the checkpoint's keys include the window.
    if config.exists():
        cfg = json.loads(config.read_text(encoding="utf-8"))
    else:
        window = recency_days(m, today) if days is AUTO else days
        cfg = run_config(m, window, locations)
        config.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

    cmd = _awake(["node", CLI, "discover", "--config", config, "--out", run, "--history", history])
    if (run / "checkpoint.jsonl").exists():
        cmd.append("--resume")
    proc = run_step(cmd)
    report_path = run / "run-report.json"
    if not report_path.exists():
        raise Stop("discover_failed", _tail(proc))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cov = coverage(run, cfg)
    sources = [
        {"id": s.get("id"), "status": s.get("status"), "reason": s.get("reason", ""), "cards": s.get("cards"), "health": s.get("health")}
        for s in report.get("sources", [])
    ]
    return {
        "run_dir": str(run),
        "run": run.name,
        "window_days": cfg.get("recencyDays"),
        "locations": cfg["locations"],
        "counters": report.get("counters"),
        "sources": sources,
        "coverage": cov,
        "complete": not cov["not_searched"] and all(s["status"] == "ok" for s in sources),
        "doctor_problems": [c for c in doctor.get("checks", []) if not c.get("ok")],
    }


def _run_dir(m: Master, name: str) -> Path:
    run = _runs(m) / name
    if Path(name).name != name or not run.is_dir():
        raise Stop("run_unknown", name)
    return run


def _cards(run: Path) -> list[dict]:
    path = run / "cards.json"
    if not path.exists():
        raise Stop("cards_missing", str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def cards(name: str, run_name_: str, *, config_root=CONFIG_ROOT) -> dict:
    """What a choice of what to read needs, and no URL: those are copied, never retyped."""
    run = _run_dir(resolve_master(name, config_root), run_name_)
    rows = [
        {
            "id": c.get("sourceJobId"),
            "title": c.get("title"),
            "company": c.get("company"),
            "location": c.get("location"),
            "posted": c.get("posted"),
            "areas": c.get("areas", []),
            "snippet": (c.get("snippet") or "")[:200],
        }
        for c in _cards(run)
    ]
    return {"run": run.name, "count": len(rows), "cards": rows}


def shortlist(name: str, run_name_: str, ids: list[str], *, config_root=CONFIG_ROOT) -> dict:
    """Write shortlist.json by copying whole cards. A card typed out again is how a URL
    gets changed on the way."""
    run = _run_dir(resolve_master(name, config_root), run_name_)
    by_id = {str(c.get("sourceJobId")): c for c in _cards(run)}
    wanted = list(dict.fromkeys(str(i) for i in ids))
    unknown = [i for i in wanted if i not in by_id]
    if unknown:
        raise Stop("card_unknown", ", ".join(unknown))
    (run / "shortlist.json").write_text(json.dumps([by_id[i] for i in wanted], ensure_ascii=False, indent=1), encoding="utf-8")
    return {"run": run.name, "shortlisted": len(wanted), "of": len(by_id)}


def read(name: str, run_name_: str, *, config_root=CONFIG_ROOT, shortlist=None) -> dict:
    m = resolve_master(name, config_root)
    run = _run_dir(m, run_name_)
    cards = Path(shortlist) if shortlist else run / "shortlist.json"
    if not cards.exists():
        raise Stop("shortlist_missing", str(cards))
    proc = run_step(_awake(["node", CLI, "read", "--cards", cards, "--out", run, "--cooldown-minutes", COOLDOWN_MINUTES]))
    report = run / "read-report.json"
    if not report.exists():
        raise Stop("read_failed", _tail(proc))
    return json.loads(report.read_text(encoding="utf-8"))


def _previous_tsv(m: Master, run: Path) -> Path | None:
    for other in sorted(_runs(m).iterdir(), reverse=True):
        if other.name < run.name and (other / "final" / "run.tsv").exists():
            return other / "final" / "run.tsv"
    return None


def publish(name: str, run_name_: str, *, config_root=CONFIG_ROOT, today: str | None = None, confirm: bool = False) -> dict:
    today = today or dt.date.today().isoformat()
    m = resolve_master(name, config_root)
    run = _run_dir(m, run_name_)
    history = run / "history.csv"
    if not (run / "verdicts.json").exists():
        raise Stop("verdicts_missing", str(run))

    declared = build_tsv.write_declared(run, _yaml_list(m.a3_text, "job_languages"))
    proc = run_step(["node", CLI, "admit", "--fields", declared, "--out", run / "final"])
    if proc.returncode != 0:
        raise Stop("admit_refused", _tail(proc))
    try:
        summary = build_tsv.build(run, a2_path=m.a2, history=history, date=today, carry=_previous_tsv(m, run))
    except build_tsv.BuildError as exc:
        raise Stop("verdicts_refused", str(exc)) from exc

    final = run / "final"
    proc = run_step([sys.executable, SYNC, "stage", "--dir", m.dir, "--history", history, "--tsv", final / "run.tsv", "--evidence", final])
    staged = _json_of(proc)
    if proc.returncode != 0 or staged.get("validation_problems"):
        raise Stop("stage_refused", _tail(proc))
    if staged.get("roles_out") != summary["roles_out"]:
        raise Stop("role_count_mismatch", f"built {summary['roles_out']}, staged {staged.get('roles_out')}")
    for column in ("Posted / Result Age", "Search Query"):
        filled = staged["evidence_join"]["filled"][column]
        if filled != f"{summary['roles_out']}/{summary['roles_out']}":
            raise Stop("evidence_incomplete", f"{column}: {filled}")

    append = [sys.executable, SYNC, "append", "--dir", m.dir, "--history", history]
    proc = run_step(append + ["--dry-run"])
    planned = _json_of(proc)
    if proc.returncode != 0:
        raise Stop("append_refused", _tail(proc))
    result = {
        **summary,
        "run": run.name,
        "would_append": planned.get("would_append", []),
        "deferred": planned.get("deferred_detail", []),
        "state": "awaiting_confirmation",
    }
    if confirm:
        proc = run_step(append)
        done = _json_of(proc)
        if proc.returncode != 0:
            raise Stop("append_refused", _tail(proc))
        result["appended"] = done.get("appended", 0)
        result["sidecar"] = done.get("sidecar")
        # A guard that refused has written a sidecar instead: nothing reached the file.
        result["state"] = "refused_to_sidecar" if done.get("sidecar") else "written"
    (final / "publish.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config-root", help="the config/ folder; found from the current folder when omitted")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("masters", help="the Masters a run can be started for")
    p = sub.add_parser("cards", help="the cards a run found, compactly, to choose what to read")
    p.add_argument("--master", required=True)
    p.add_argument("--run", required=True)
    p = sub.add_parser("shortlist", help="write shortlist.json from card ids")
    p.add_argument("--master", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--ids", nargs="+", required=True)
    p = sub.add_parser("prepare", help="doctor, export-history, run.json and discover")
    p.add_argument("--master", required=True)
    p.add_argument("--recency-days", type=int, help="overrides the computed window (record the reason in the report)")
    p.add_argument("--locations", nargs="+", help="overrides A3 for this run (record the reason in the report)")
    p = sub.add_parser("read", help="read the descriptions of a shortlist")
    p.add_argument("--master", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--shortlist")
    p = sub.add_parser("publish", help="admit, build-tsv, stage and append --dry-run; --confirm writes")
    p.add_argument("--master", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        root = Path(args.config_root) if args.config_root else default_config_root()
        if args.config_root and not (root / A1_NAME).is_file():
            raise Stop("config_not_found", f"no {A1_NAME} in {root}")
        if args.command == "masters":
            out = masters(config_root=root)
        elif args.command == "cards":
            out = cards(args.master, args.run, config_root=root)
        elif args.command == "shortlist":
            out = shortlist(args.master, args.run, args.ids, config_root=root)
        elif args.command == "prepare":
            days = AUTO if args.recency_days is None else args.recency_days
            with keep_awake():
                out = prepare(args.master, config_root=root, days=days, locations=args.locations)
        elif args.command == "read":
            with keep_awake():
                out = read(args.master, args.run, config_root=root, shortlist=args.shortlist)
        else:
            out = publish(args.master, args.run, config_root=root, confirm=args.confirm)
    except Stop as stop:
        print(json.dumps({"stop": stop.code, "detail": stop.detail}, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
