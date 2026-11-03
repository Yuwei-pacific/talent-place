#!/usr/bin/env python3
"""python3 spike/build.py -> spike/dist/talent-placement-probe.zip, the file to upload."""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
NAME = "talent-placement-probe"
JUNK = shutil.ignore_patterns("test_*", "__pycache__", "*.pyc", ".DS_Store")


def main() -> int:
    npm = shutil.which("npm") or "npm"
    subprocess.run([npm, "run", "build"], cwd=ENGINE, check=True, capture_output=True)

    # Imported here so a missing openpyxl stops the build, not the colleague's test.
    import et_xmlfile
    import openpyxl

    dist = HERE / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    plugin = dist / NAME
    shutil.copytree(HERE / "windows-probe", plugin, ignore=JUNK)

    engine = plugin / "skills" / "probe" / "engine"
    for part in ("lib", "data", "python"):
        shutil.copytree(ENGINE / part, engine / part, ignore=JUNK)
    # lib/ is ESM only because package.json says so.
    shutil.copy(ENGINE / "package.json", engine / "package.json")
    # Pure Python, so it works even where the sandbox cannot reach PyPI.
    for module in (openpyxl, et_xmlfile):
        source = Path(module.__file__).parent
        shutil.copytree(source, engine / "python" / "vendor" / source.name, ignore=JUNK)

    target = dist / f"{NAME}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(plugin.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(dist))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
