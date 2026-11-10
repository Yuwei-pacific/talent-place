#!/usr/bin/env python3
"""python3 plugin/build.py -> plugin/dist/talent-placement.zip, the file to upload.

The engine is packed inside the cerca-stage skill, because the skill's own folder is
the one path a skill can rely on. config/ is deliberately not packed: A1-A4 stay where
colleagues edit them, and the engine finds them from the folder the session opens in.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
NAME = "talent-placement"
JUNK = shutil.ignore_patterns("test_*", "__pycache__", "*.pyc", ".DS_Store", "vendor")


def main() -> int:
    npm = shutil.which("npm") or "npm"
    built = subprocess.run([npm, "run", "build"], cwd=ENGINE, capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stdout + built.stderr)
        return built.returncode

    # Imported here so a missing openpyxl stops the build, not a colleague's search.
    import et_xmlfile
    import openpyxl

    dist = HERE / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    plugin = dist / NAME
    shutil.copytree(HERE / NAME, plugin, ignore=JUNK)

    engine = plugin / "skills" / "cerca-stage" / "engine"
    for part in ("lib", "data", "python"):
        shutil.copytree(ENGINE / part, engine / part, ignore=JUNK)
    # lib/ is ESM only because package.json says so.
    shutil.copy(ENGINE / "package.json", engine / "package.json")
    # Pure Python, so a computer with Python and nothing else installed can run it.
    for module in (openpyxl, et_xmlfile):
        source = Path(module.__file__).parent
        shutil.copytree(source, engine / "python" / "vendor" / source.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    target = dist / f"{NAME}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(plugin.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(dist))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
