#!/usr/bin/env python3
"""Package the skill as a ZIP for upload to claude.ai / Claude Desktop (Customize > Skills).

    python scripts/package_skill.py            ->  dist/blender-master.zip

The archive's top-level entry is the folder `blender-master/` (claude.ai looks for
<folder>/SKILL.md and requires the folder name to match the skill name). Generated test output,
caches, docs images and VCS files are excluded. Standard library only.
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {".git", "__pycache__", "dist", "output", "images"}
EXCLUDE_EXT = (".pyc", ".blend", ".blend1", ".zip")


def main():
    skill_md = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
    name = re.search(r"^name:\s*(\S+)", skill_md, re.M).group(1)
    desc = re.search(r'^description:\s*"?(.*?)"?\s*$', skill_md, re.M).group(1)
    if len(desc) > 200:
        print("WARNING: description is %d chars; claude.ai accepts at most 200" % len(desc))
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name + ".zip")
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in EXCLUDE_DIRS]
            for f in files:
                if f.endswith(EXCLUDE_EXT):
                    continue
                full = os.path.join(d, f)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                z.write(full, name + "/" + rel)
                n += 1
    print("%s  (%d files, %.0f KB)" % (out, n, os.path.getsize(out) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
