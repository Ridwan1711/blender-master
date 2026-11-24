#!/usr/bin/env python3
"""bk.py - headless Blender driver for the blender-master skill.

Standard library only (Python 3.8+). Runs Blender as a subprocess, injects the
`bkit` helper library, captures errors as structured JSON and keeps full logs.

    python bk.py probe [--bench]
    python bk.py run   build.py [--blend in.blend] [--save out.blend] [--overwrite] [-- script args]
    python bk.py exec  "import bpy; ..." [--blend in.blend] [--save out.blend]
    python bk.py inspect  scene.blend [--health] [--objects]
    python bk.py validate scene.blend [--tier film|hero|game|mobile] [--strict]
    python bk.py preview  scene.blend --out DIR [--views persp,front,right,top,camera] [--mode clay|material|random|wire]
    python bk.py render   scene.blend --out PATH [--quality preview|draft|final] [--engine cycles|eevee|workbench]
    python bk.py imgcheck image.png

Common options: --blender PATH (or env BLENDER_PATH), --timeout SEC, --user-prefs,
--json (print only the result JSON), --log-lines N.
Exit codes: 0 ok, 1 script/Blender error, 2 timeout, 3 Blender not found / bad usage.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "@@BKIT_RESULT@@"
LOG_DIR = os.path.join(tempfile.gettempdir(), "bkit_logs")

# Lines worth surfacing from Blender's (very chatty) output.
_KEEP = re.compile(
    r"(Error|ERROR|Warning|WARN|Traceback|Exception|^\s+File \"|^\w+Error:|"
    r"not found|failed|Failed|cannot|Cannot|unable|Unable|out of memory|"
    r"^BKIT|^\[bkit\]|Saved:|Info:)"
)
_DROP = re.compile(r"^(Fra:\d+|Blender \d|Read prefs|Read blend|\s*$|Time: \d|"
                   r"Color management:|Warning: Unable to open font|Info: Saved)")


def _version_key(path):
    nums = re.findall(r"(\d+)\.(\d+)", path)
    return tuple(int(x) for x in nums[-1]) if nums else (0, 0)


def find_blender(explicit=None):
    """Locate a Blender executable. Highest installed version wins unless explicit."""
    cands = []
    for c in (explicit, os.environ.get("BLENDER_PATH"), os.environ.get("BLENDER"),
              shutil.which("blender")):
        if c:
            cands.append(c)
    if sys.platform == "win32":
        pats = [r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe"),
                r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
                r"C:\Program Files\Steam\steamapps\common\Blender\blender.exe"]
    elif sys.platform == "darwin":
        pats = ["/Applications/Blender*.app/Contents/MacOS/Blender",
                os.path.expanduser("~/Applications/Blender*.app/Contents/MacOS/Blender")]
    else:
        pats = ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
                "/opt/blender*/blender", os.path.expanduser("~/blender*/blender"),
                os.path.expanduser("~/.local/share/Steam/steamapps/common/Blender/blender")]
    found = []
    for p in pats:
        found += glob.glob(p)
    found.sort(key=_version_key, reverse=True)
    cands += found
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def run_blender(script=None, expr=None, blend=None, args=None, save=None, overwrite=False,
                factory=True, timeout=900, blender=None, log_lines=40, json_only=False,
                tag="run"):
    exe = find_blender(blender)
    if not exe:
        print("ERROR: Blender not found. Set BLENDER_PATH or pass --blender PATH.", file=sys.stderr)
        return 3, None
    if blend and not os.path.isfile(blend):
        print("ERROR: blend file not found: %s" % blend, file=sys.stderr)
        return 3, None
    if script and not os.path.isfile(script):
        print("ERROR: script not found: %s" % script, file=sys.stderr)
        return 3, None

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cfg = {
        "script": os.path.abspath(script) if script else None,
        "expr": expr,
        "args": list(args or []),
        "save": os.path.abspath(save) if save else None,
        "overwrite": bool(overwrite),
        "lib": HERE,
        "blend": os.path.abspath(blend) if blend else None,
    }
    fd, cfg_path = tempfile.mkstemp(prefix="bkit_cfg_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    cmd = [exe, "-b"]
    if factory:
        cmd.append("--factory-startup")
    if blend:
        cmd.append(os.path.abspath(blend))
    cmd += ["--python-exit-code", "1", "--python", os.path.join(HERE, "_bootstrap.py"),
            "--", cfg_path]

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_path = os.path.join(LOG_DIR, "%s-%s-%d.log" % (tag, stamp, os.getpid()))
    t0 = time.time()
    timed_out = False
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            timed_out = True
        text = out.decode("utf-8", errors="replace")
        logf.write(" ".join('"%s"' % c if " " in c else c for c in cmd) + "\n\n")
        logf.write(text)
    elapsed = time.time() - t0
    try:
        os.remove(cfg_path)
    except OSError:
        pass

    result = None
    for line in text.splitlines():
        if line.startswith(MARK):
            try:
                result = json.loads(line[len(MARK):].strip())
            except ValueError:
                result = {"status": "error", "error": {"message": "unparseable result line"}}
    if timed_out:
        code = 2
    elif proc.returncode != 0 or result is None or result.get("status") != "ok":
        code = 1
    else:
        code = 0

    if json_only:
        print(json.dumps(result if result is not None else {"status": "error", "exit": proc.returncode},
                         indent=1, default=str))
        return code, result

    status = {0: "OK", 1: "FAILED", 2: "TIMEOUT (%ss)" % timeout}[code]
    ver = (result or {}).get("blender", "?")
    print("== bk %s: %s  (%.1fs, exit=%s, blender %s)" % (tag, status, elapsed, proc.returncode, ver))
    if result is not None:
        shown = {k: v for k, v in result.items() if k not in ("blender",)}
        if isinstance(shown.get("error"), dict) and shown["error"].get("traceback"):
            tb = shown["error"]["traceback"]
            # Keep the tail (innermost frames); the full traceback is in the log file.
            shown["error"] = dict(shown["error"], traceback="..." + tb[-900:] if len(tb) > 900 else tb)
        print("-- result --")
        print(json.dumps(shown, indent=1, default=str))
    else:
        print("-- no result marker: Blender crashed or the bootstrap never ran --")
    kept = [l for l in text.splitlines()
            if not l.startswith(MARK) and _KEEP.search(l) and not _DROP.search(l)]
    if kept and log_lines:
        print("-- log (filtered, last %d of %d) --" % (min(log_lines, len(kept)), len(kept)))
        for l in kept[-log_lines:]:
            print("  " + l[:300])
    print("full log: %s" % log_path)
    return code, result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    passthru = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthru = argv[:i], argv[i + 1:]

    p = argparse.ArgumentParser(prog="bk.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["probe", "run", "exec", "inspect", "validate", "preview",
                                       "render", "imgcheck", "which"])
    p.add_argument("target", nargs="?", help="script, code string, .blend or image depending on command")
    p.add_argument("--blend", help="open this .blend before running (run/exec)")
    p.add_argument("--save", help="save the resulting scene here (refuses to overwrite)")
    p.add_argument("--overwrite", action="store_true", help="allow --save to replace an existing file")
    p.add_argument("--blender", help="path to blender executable")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--user-prefs", action="store_true", help="load user prefs/add-ons (default: factory)")
    p.add_argument("--json", action="store_true", help="print only the result JSON")
    p.add_argument("--log-lines", type=int, default=40)
    known, extra = p.parse_known_args(argv)
    extra += passthru
    c = known.command
    common = dict(blender=known.blender, timeout=known.timeout, factory=not known.user_prefs,
                  log_lines=known.log_lines, json_only=known.json, tag=c)

    if c == "which":
        exe = find_blender(known.blender)
        print(exe or "not found")
        return 0 if exe else 3
    if c == "probe":
        code, _ = run_blender(os.path.join(HERE, "probe_env.py"), args=extra, **common)
        return code
    if c == "run":
        if not known.target:
            p.error("run needs a script path")
        code, _ = run_blender(known.target, blend=known.blend, args=extra, save=known.save,
                              overwrite=known.overwrite, **common)
        return code
    if c == "exec":
        if not known.target:
            p.error("exec needs a code string")
        code, _ = run_blender(expr=known.target, blend=known.blend, args=extra, save=known.save,
                              overwrite=known.overwrite, **common)
        return code
    if c == "imgcheck":
        if not known.target:
            p.error("imgcheck needs an image path")
        code, _ = run_blender(os.path.join(HERE, "imgcheck.py"),
                              args=[os.path.abspath(known.target)] + extra, **common)
        return code
    # commands that operate on a .blend
    if not known.target:
        p.error("%s needs a .blend path" % c)
    script = {"inspect": "inspect_blend.py", "validate": "validate_blend.py",
              "preview": "preview_blend.py", "render": "render_blend.py"}[c]
    code, _ = run_blender(os.path.join(HERE, script), blend=known.target, args=extra,
                          save=known.save, overwrite=known.overwrite, **common)
    return code


if __name__ == "__main__":
    sys.exit(main())
