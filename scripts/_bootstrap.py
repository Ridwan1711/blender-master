"""Runs inside Blender (launched by bk.py). Do not run directly.

Responsibilities: make `bkit` importable, run the target script or expression,
turn exceptions into a structured error, optionally save safely, and print one
`@@BKIT_RESULT@@ {json}` line that bk.py parses.
"""
import json
import os
import runpy
import sys
import time
import traceback

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

_argv = sys.argv
_cfg_path = _argv[_argv.index("--") + 1]
with open(_cfg_path, encoding="utf-8") as _f:
    CFG = json.load(_f)

if CFG["lib"] not in sys.path:
    sys.path.insert(0, CFG["lib"])

import bpy  # noqa: E402
from bkit import runtime  # noqa: E402

runtime.init(CFG)
_t0 = time.time()
_status, _err = "ok", None


def _error_info(exc):
    tb = traceback.extract_tb(exc.__traceback__)
    where = None
    target = CFG.get("script") or "<bk-exec>"
    for fr in reversed(tb):
        if os.path.normcase(fr.filename) == os.path.normcase(target) or fr.filename == "<bk-exec>":
            where = {"file": fr.filename, "line": fr.lineno, "code": fr.line}
            break
    if where is None and tb:
        fr = tb[-1]
        where = {"file": fr.filename, "line": fr.lineno, "code": fr.line}
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
        "where": where,
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:],
    }


try:
    if CFG.get("expr"):
        sys.argv = ["<bk-exec>"] + CFG.get("args", [])
        g = {"__name__": "__main__", "bpy": bpy}
        exec(compile(CFG["expr"], "<bk-exec>", "exec"), g)
    elif CFG.get("script"):
        sys.argv = [CFG["script"]] + CFG.get("args", [])
        sd = os.path.dirname(CFG["script"])
        if sd not in sys.path:
            sys.path.insert(1, sd)
        runpy.run_path(CFG["script"], run_name="__main__")
    if CFG.get("save"):
        runtime.safe_save(CFG["save"], overwrite=CFG.get("overwrite", False))
except SystemExit as e:
    if e.code not in (None, 0):
        _status = "error"
        _err = {"type": "SystemExit", "message": "script exited with %r" % (e.code,), "where": None}
except BaseException as e:  # noqa: BLE001 - we report everything
    _status = "error"
    _err = _error_info(e)
    print("[bkit] ERROR %s: %s" % (_err["type"], _err["message"]))

runtime.finish(_status, _err, time.time() - _t0)
sys.stdout.flush()
if _status != "ok":
    # Force a non-zero exit even though the exception was caught.
    os._exit(1)
