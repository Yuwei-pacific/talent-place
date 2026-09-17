#!/usr/bin/env python3
"""Filesystem guards for writing into a macOS OneDrive / SharePoint sync folder.

The target is a macOS File Provider domain, not a network mount. Three facts
about it drive everything here (all measured on this machine, not assumed):

1. A dataless (online-only) file reports its FULL st_size while st_blocks == 0,
   with UF_DATALESS set. So ``st_size > 0`` does NOT mean the bytes are local,
   and ``load_workbook()`` on such a file blocks on hydration — or raises if
   OneDrive is signed out, paused, or offline.
2. Recursive traversal is pathological (a plain ``find`` over the mount was
   killed after 120s because enumeration forces hydration). Nothing here may
   walk a tree; only exact paths are stat'd, plus a single non-recursive
   listing of the one target directory.
3. Writes are ordinary filesystem writes with no auth. OneDrive uploads them.
   That is the whole integration.

This module is deliberately free of any openpyxl or project import so it can be
unit-tested without a real sync folder and without a workbook.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat as stat_mod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

# macOS: set on a file whose content is not present locally.
UF_DATALESS = 0x40000000

# Excel creates a "~$Name.xlsx" owner file next to a workbook it has open.
EXCEL_LOCK_PREFIX = "~$"

# Keep this many pre-write backups.
BACKUP_KEEP = 10


class GuardFailure(Exception):
    """A write was refused. Refusing is safe; a half-write is not."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Fingerprint:
    """Cheap change detector. Uses lstat, never the workbook's internal
    docProps/core.xml modified time — openpyxl overwrites that on every save,
    so it can never be used for change detection."""

    mtime_ns: int
    size: int

    @classmethod
    def of(cls, path: str | Path) -> "Fingerprint | None":
        try:
            st = os.stat(path)
        except OSError:
            return None
        return cls(st.st_mtime_ns, st.st_size)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Fingerprint) and (self.mtime_ns, self.size) == (
            other.mtime_ns,
            other.size,
        )


def is_dataless(path: str | Path) -> bool:
    """True if the file exists but its content is not on this machine.

    Refuse to open such a file rather than block on hydration or raise an
    opaque error when OneDrive is not running.
    """
    try:
        st = os.stat(path)
    except OSError:
        return False
    if not stat_mod.S_ISREG(st.st_mode):
        return False
    if getattr(st, "st_flags", 0) & UF_DATALESS:
        return True
    # Belt and braces: a regular non-empty file with no allocated blocks is
    # online-only on this mount.
    return st.st_size > 0 and st.st_blocks == 0


def excel_lock_present(path: str | Path) -> Path | None:
    """Return the Excel owner file blocking `path`, if any.

    This is a HEURISTIC for a colleague editing on THIS machine. It cannot see
    a colleague editing on Windows in Excel for the web, and OneDrive does not
    sync ``~$`` files, so a remote lock is invisible until it becomes a
    conflicted copy. It is paired with a pre-write backup and a caller-side
    sidecar fallback precisely because it can be wrong in both directions.
    """
    p = Path(path)
    candidate = p.parent / f"{EXCEL_LOCK_PREFIX}{p.name}"
    if candidate.exists():
        return candidate
    # Excel may truncate the owner name; one non-recursive listing of the
    # single target directory is cheap and does not force content hydration.
    try:
        stem = p.stem[:8]
        for entry in os.listdir(p.parent):
            if entry.startswith(EXCEL_LOCK_PREFIX) and stem and stem in entry:
                return p.parent / entry
    except OSError:
        pass
    return None


def assert_writable(path: str | Path, allow_hydrate: bool = False) -> None:
    """Raise GuardFailure if writing `path` is unsafe right now."""
    p = Path(path)
    if not p.parent.exists():
        raise GuardFailure("missing_dir", str(p.parent))
    if not os.access(p.parent, os.W_OK):
        raise GuardFailure("dir_not_writable", str(p.parent))
    if p.exists():
        lock = excel_lock_present(p)
        if lock is not None:
            raise GuardFailure("excel_lock", str(lock))
        if is_dataless(p) and not allow_hydrate:
            raise GuardFailure("dataless", f"{p} content is not local")


def backup(path: str | Path, backup_dir: str | Path) -> Path | None:
    """Copy `path` into `backup_dir` before it is replaced.

    The single most valuable safety net in the design: openpyxl has no
    incremental append, so every save rebuilds the whole container and silently
    drops archive parts it does not model (customXml/, metadata.xml, persons/,
    threadedComments/). No amount of care prevents that; a backup makes it
    recoverable.
    """
    p = Path(path)
    if not p.exists():
        return None
    bdir = Path(backup_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"{p.stem}-{stamp}{p.suffix}"
    n = 1
    while dest.exists():
        dest = bdir / f"{p.stem}-{stamp}-{n}{p.suffix}"
        n += 1
    shutil.copy2(p, dest)
    _rotate(bdir, p.stem, p.suffix)
    return dest


def _rotate(backup_dir: Path, stem: str, suffix: str) -> None:
    try:
        items = sorted(
            (f for f in backup_dir.iterdir() if f.name.startswith(f"{stem}-") and f.suffix == suffix),
            key=lambda f: f.stat().st_mtime,
        )
    except OSError:
        return
    for old in items[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def write_atomically(
    target: str | Path,
    write_fn: Callable[[Path], None],
    allow_hydrate: bool = False,
    backup_dir: str | Path | None = None,
    guard: bool = True,
) -> Fingerprint | None:
    """Write `target` via a temp file in the same directory + os.replace.

    Writing the temp file in the SAME directory is required for the rename to
    be atomic (same filesystem). A reader never sees a half-written workbook.

    Returns the new fingerprint, or None when the target was skipped because it
    did not exist beforehand (nothing to compare).
    """
    t = Path(target)
    if guard:
        assert_writable(t, allow_hydrate=allow_hydrate)

    before = Fingerprint.of(t)
    if backup_dir is not None and t.exists():
        backup(t, backup_dir)

    tmp = t.parent / f".{t.name}.tmp-{os.getpid()}"
    try:
        write_fn(tmp)
        # Re-check immediately before the rename: narrows the window in which a
        # colleague could have opened or edited the file to milliseconds rather
        # than the seconds a load+save takes.
        if guard and t.exists() and Fingerprint.of(t) != before:
            raise GuardFailure("changed_concurrently", str(t))
        os.replace(tmp, t)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return Fingerprint.of(t)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno not in (errno.EEXIST,):
            raise
    return p


def describe(path: str | Path) -> dict:
    """One-path health report. Never walks a tree."""
    p = Path(path)
    out: dict = {"path": str(p), "exists": p.exists()}
    if not out["exists"]:
        return out
    st = os.stat(p)
    out.update(
        {
            "size": st.st_size,
            "blocks": st.st_blocks,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "dataless": is_dataless(p),
        }
    )
    lock = excel_lock_present(p)
    out["excel_lock"] = str(lock) if lock else None
    return out
