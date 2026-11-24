"""Result protocol and safe saving. Used by _bootstrap.py and by build scripts.

    from bkit import emit, warn, save
    emit(tris=1234, render="C:/out/a.png")   # appears in bk.py's result JSON
    warn("cutter left visible")               # collected under "warnings"
    save("C:/proj/scene.blend")               # refuses to overwrite; see save(version=True)
"""
import json
import os
import re
import sys

import bpy

MARK = "@@BKIT_RESULT@@"
CFG = {}
RESULT = {}
WARNINGS = []
SAVED = []


def init(cfg):
    CFG.clear()
    CFG.update(cfg)


def emit(**kw):
    """Attach values to the result JSON printed at the end of the run."""
    RESULT.update(kw)


def warn(msg):
    WARNINGS.append(str(msg))
    print("[bkit] WARNING " + str(msg))


def args():
    """Arguments after `--` given to bk.py run (also in sys.argv[1:])."""
    return list(CFG.get("args", []))


def next_version_path(path):
    """scene.blend -> scene_v001.blend (first free); scene_v004.blend -> scene_v005.blend."""
    root, ext = os.path.splitext(path)
    m = re.match(r"^(.*)_v(\d+)$", root)
    base, n = (m.group(1), int(m.group(2))) if m else (root, 0)
    while True:
        n += 1
        cand = "%s_v%03d%s" % (base, n, ext or ".blend")
        if not os.path.exists(cand):
            return cand


def safe_save(path, overwrite=False, version=False, compress=False):
    """Save the current file without ever silently replacing an existing one.

    overwrite=True  replace an existing file (Blender keeps a .blend1 backup).
    version=True    write to the next free name_v###.blend instead.
    Returns the path written.
    """
    path = os.path.abspath(path)
    if version:
        path = next_version_path(path)
    elif os.path.exists(path) and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite %s. Use overwrite=True (bk.py --overwrite) or version=True." % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False, compress=compress,
                                relative_remap=True)
    SAVED.append(path)
    print("[bkit] saved " + path)
    return path


save = safe_save


def finish(status, err, elapsed):
    out = {"status": status, "blender": bpy.app.version_string, "seconds": round(elapsed, 2)}
    if CFG.get("blend"):
        out["opened"] = CFG["blend"]
    if SAVED:
        out["saved"] = SAVED
    if WARNINGS:
        out["warnings"] = WARNINGS
    out.update(RESULT)
    if err:
        out["error"] = err
    sys.stdout.write("\n" + MARK + " " + json.dumps(out, default=str) + "\n")
    sys.stdout.flush()
