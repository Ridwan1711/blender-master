#!/usr/bin/env python3
"""End-to-end automated production: spec -> .blend -> QA -> previews -> render -> export -> report.

    python pipeline.py spec.json --out OUTDIR [--tier hero] [--strict] [--no-render] [--overwrite]

Every stage runs in its own Blender process (clean state, crash isolation). A failing
stage stops the pipeline (validation errors included) and the report says where and why.
Writes OUTDIR/<name>.blend, preview sheet, render, exports, and OUTDIR/report.json + report.md.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bk import HERE, run_blender  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tier", default="hero")
    ap.add_argument("--strict", action="store_true", help="warnings also stop the pipeline")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args()
    spec_path = os.path.abspath(a.spec)
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    name = spec.get("name", os.path.splitext(os.path.basename(spec_path))[0])
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    blend = os.path.join(out, name + ".blend")
    report = {"name": name, "spec": spec_path, "stages": [], "ok": False}
    common = dict(timeout=a.timeout, log_lines=0, json_only=True)

    def stage(label, **kw):
        t0 = time.time()
        print("[pipeline] %s ..." % label, flush=True)
        code, res = run_blender(tag=label, **kw, **common)
        st = {"stage": label, "ok": code == 0, "seconds": round(time.time() - t0, 1),
              "result": {k: v for k, v in (res or {}).items() if k not in ("blender",)}}
        report["stages"].append(st)
        return st

    s = stage("build", script=os.path.join(HERE, "build_from_spec.py"), args=[spec_path], save=blend,
              overwrite=a.overwrite)
    if s["ok"]:
        args = ["--tier", a.tier] + (["--strict"] if a.strict else [])
        s = stage("validate", script=os.path.join(HERE, "validate_blend.py"), blend=blend, args=args)
    if s["ok"]:
        s = stage("preview", script=os.path.join(HERE, "preview_blend.py"), blend=blend,
                  args=["--out", os.path.join(out, "preview"), "--views", "camera,persp,front,top",
                        "--mode", "material"])
    if s["ok"] and not a.no_render:
        s = stage("render", script=os.path.join(HERE, "render_blend.py"), blend=blend,
                  args=["--out", os.path.join(out, name + ".png")])
    for fmt_path in (spec.get("export") or {}).values():
        if not s["ok"]:
            break
        target = fmt_path if os.path.isabs(fmt_path) else os.path.join(out, fmt_path)
        s = stage("export:" + os.path.splitext(target)[1], script=os.path.join(HERE, "export_blend.py"),
                  blend=blend, args=["--out", target, "--subjects"])
    report["ok"] = all(x["ok"] for x in report["stages"])
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    lines = ["# Pipeline report: %s" % name, "", "Result: **%s**" % ("PASS" if report["ok"] else "FAIL"), "",
             "| stage | ok | seconds | notes |", "|---|---|---|---|"]
    for x in report["stages"]:
        r = x["result"]
        note = ""
        if x["stage"] == "validate":
            v = r.get("validation", {})
            note = "score %s, %s" % (v.get("score"), v.get("counts"))
        elif x["stage"] == "render":
            note = "%ss, exposure %s" % (r.get("seconds"), (r.get("check") or {}).get("verdict"))
        elif x["stage"].startswith("export"):
            e = r.get("export", {})
            note = "%s bytes, reimport tris match=%s" % (e.get("bytes"), e.get("tris_match"))
        elif x["stage"] == "build":
            note = "objects %s, metering %s" % (r.get("objects"), r.get("metering"))
        if not x["ok"]:
            note = "ERROR: %s" % ((r.get("error") or {}).get("message", "see log")[:200])
        lines.append("| %s | %s | %s | %s |" % (x["stage"], "yes" if x["ok"] else "**no**", x["seconds"], note))
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("report: %s" % os.path.join(out, "report.md"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
