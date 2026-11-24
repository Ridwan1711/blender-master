#!/usr/bin/env python3
"""Blender Master skill - test suite.

    python tests/run_tests.py [--quick] [--only s01,s04] [--out tests/output/run]

For every scenario: build (fresh Blender process) -> validate -> scenario assertions (numeric) ->
render (quick: 480 px, 16 spp; full: the scenario's own settings) -> imgcheck. Writes
<out>/RESULTS.md, <out>/results.json and <out>/overview.png (all renders tiled) - LOOK at the
overview: numbers cannot judge appearance.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from bk import run_blender  # noqa: E402

SCN = os.path.join(ROOT, "tests", "scenarios")


def check(cond, label, failures):
    if not cond:
        failures.append(label)
    return cond


SCENARIOS = [
    # id, script, needs (blend from earlier scenario), validate tier, assertion fn(result) -> failures
    ("s01", "s01_basic_object.py", None, "hero",
     lambda r, v, f: [check(v["score"] >= 95, "score>=95", f), check(r["tris"] > 5000, "tris>5000", f)]),
    ("s02", "s02_hard_surface.py", None, "hero",
     lambda r, v, f: [check(v["score"] == 100, "score==100 (no doubles/degenerate/intersections)", f)]),
    ("s03", "s03_procedural_environment.py", None, "film",
     lambda r, v, f: [check(r["instances"] > 5000, "instances>5000", f),
                      check(v["counts"]["error"] == 0, "no errors", f)]),
    ("s04", "s04_material_showcase.py", None, "hero",
     lambda r, v, f: [check(abs(r["metering"]["measured"] - r["metering"]["target"]) < 0.03,
                            "grey card within 0.03 of target", f), check(v["score"] >= 95, "score>=95", f)]),
    ("s05", "s05_cinematic_animation.py", "s02", "hero",
     lambda r, v, f: [check(not r["camera_motion"]["pops_at_frames"], "no camera pops", f),
                      check(r["engine"].startswith("BLENDER_EEVEE"), "EEVEE engine", f)]),
    ("s06", "s06_photoreal_interior.py", "s01", "hero",
     lambda r, v, f: [check(v["score"] == 100, "score==100", f),
                      check(abs(r["metering"]["measured"] - r["metering"]["target"]) < 0.03, "metered", f)]),
    ("s08", "s08_rigging.py", None, "hero",
     lambda r, v, f: [check(max(r["ik_reach_error_m"]) < 0.01, "IK reaches target (<1 cm)", f),
                      check(r["weights"]["unweighted_vertices"] == 0, "all vertices weighted", f),
                      check(not r["weights"]["bones_without_weights"], "all bones weighted", f)]),
    ("s09", "s09_physics.py", None, "hero",
     lambda r, v, f: [check(r["tower_fell"], "tower fell", f), check(r["no_tunnelling"], "no tunnelling", f),
                      check(r["cloth_on_sphere"], "cloth rests on sphere", f),
                      check(r["cloth_stable"], "no cloth spikes", f)]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="small renders (480 px, 16 spp)")
    ap.add_argument("--only")
    ap.add_argument("--out", default=os.path.join(ROOT, "tests", "output", "run"))
    ap.add_argument("--no-pipeline", action="store_true")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    common = dict(log_lines=0, json_only=True, timeout=3600)
    results, renders = [], []
    blends = {}
    t_all = time.time()

    def quiet(**kw):
        devnull = open(os.devnull, "w")
        old = sys.stdout
        sys.stdout = devnull
        try:
            return run_blender(**kw, **common)
        finally:
            sys.stdout = old
            devnull.close()

    if not only or "s00" in only:
        print("[test] s00 API smoke ...", flush=True)
        t0 = time.time()
        code, res = quiet(script=os.path.join(SCN, "s00_api_smoke.py"), tag="s00")
        row = {"id": "s00", "script": "s00_api_smoke.py", "build_s": round(time.time() - t0, 1),
               "failures": ["%s: %s" % kv for kv in ((res or {}).get("failed") or {}).items()] or
                           ([] if code == 0 else ["run failed"]),
               "score": "%s/%s" % ((res or {}).get("n_checked"), (res or {}).get("n_checked", 0) + (res or {}).get("n_failed", 0))}
        row["passed"] = not row["failures"]
        results.append(row)
        print("       %s %s" % ("PASS" if row["passed"] else "FAIL", row["score"]), flush=True)

    for sid, script, needs, tier, assert_fn in SCENARIOS:
        if only and sid not in only:
            continue
        print("[test] %s %s ..." % (sid, script), flush=True)
        row = {"id": sid, "script": script, "failures": []}
        blend = os.path.join(out, sid + ".blend")
        args = []
        kw = {}
        if needs:
            if needs not in blends:
                row["failures"].append("needs %s blend (run it too)" % needs)
                results.append(row)
                continue
            if sid == "s05":
                kw["blend"] = blends[needs]
            else:
                args = ["--mug", blends[needs]]
        t0 = time.time()
        code, res = quiet(script=os.path.join(SCN, script), save=blend, overwrite=True, args=args, tag=sid, **kw)
        row["build_s"] = round(time.time() - t0, 1)
        if code != 0:
            row["failures"].append("build failed: %s" % ((res or {}).get("error") or {}).get("message", "?")[:200])
            results.append(row)
            continue
        blends[sid] = blend
        code, vres = quiet(script=os.path.join(ROOT, "scripts", "validate_blend.py"), blend=blend,
                           args=["--tier", tier], tag="validate")
        v = (vres or {}).get("validation", {})
        row["score"], row["counts"] = v.get("score"), v.get("counts")
        row["issues"] = ["%s %s %s" % (i["sev"], i["code"], i["obj"]) for i in v.get("issues", [])][:8]
        try:
            assert_fn(res, v, row["failures"])
        except Exception as e:  # noqa: BLE001
            row["failures"].append("assertion error: %r" % e)
        png = os.path.join(out, sid + ".png")
        rargs = ["--out", png] + (["--res", "480x300" if sid != "s04" else "480x300", "--samples", "16"] if a.quick else [])
        if sid == "s05":
            rargs += ["--frame", "36"]
        if sid in ("s08", "s09"):
            rargs += ["--frame", "24" if sid == "s08" else "90"]
        t0 = time.time()
        code, rres = quiet(script=os.path.join(ROOT, "scripts", "render_blend.py"), blend=blend, args=rargs, tag="render")
        row["render_s"] = round(time.time() - t0, 1)
        if code == 0:
            row["render"] = png
            row["imgcheck"] = (rres.get("check") or {}).get("verdict")
            renders.append(png)
        else:
            row["failures"].append("render failed")
        row["passed"] = not row["failures"]
        results.append(row)
        print("       %s  score=%s  build=%ss render=%ss %s" % ("PASS" if row["passed"] else "FAIL", row.get("score"),
              row["build_s"], row.get("render_s"), row["failures"] or ""), flush=True)

    if not a.no_pipeline and (not only or "s07" in only):
        print("[test] s07 pipeline ...", flush=True)
        import subprocess
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "pipeline.py"),
                            os.path.join(ROOT, "examples", "spec_desk.json"), "--out", os.path.join(out, "s07"),
                            "--overwrite"] + (["--no-render"] if a.quick else []), capture_output=True, text=True)
        rep = json.load(open(os.path.join(out, "s07", "report.json"), encoding="utf-8"))
        row = {"id": "s07", "script": "pipeline.py examples/spec_desk.json", "build_s": round(time.time() - t0, 1),
               "failures": [] if rep["ok"] else ["pipeline stage failed"], "passed": rep["ok"],
               "stages": [(s["stage"], s["ok"], s["seconds"]) for s in rep["stages"]]}
        exp = [s for s in rep["stages"] if s["stage"].startswith("export")]
        if exp and not exp[0]["result"].get("export", {}).get("tris_match"):
            row["failures"].append("GLB re-import tris mismatch")
            row["passed"] = False
        sheet = os.path.join(out, "s07", "preview", "view_camera.png")
        if os.path.isfile(sheet):
            renders.append(sheet)
        results.append(row)
        print("       %s %s" % ("PASS" if row["passed"] else "FAIL", row["stages"]), flush=True)

    if renders:
        code, sres = quiet(expr="from bkit import preview as P, emit\nimport sys\n"
                                "emit(sheet=P.contact_sheet(sys.argv[1:-1], sys.argv[-1], cols=3))",
                           args=renders + [os.path.join(out, "overview.png")], tag="overview")
    total = round(time.time() - t_all, 1)
    passed = sum(1 for r in results if r.get("passed"))
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, default=str)
    lines = ["# Test results", "", "Mode: %s | %d/%d passed | %.0f s total" % ("quick" if a.quick else "full",
             passed, len(results), total), "", "| id | scenario | pass | score | build s | render s | imgcheck | failures |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["script"], "PASS" if r.get("passed") else "**FAIL**", r.get("score", "-"), r.get("build_s", "-"),
            r.get("render_s", "-"), ",".join(r.get("imgcheck") or []) or "-", "; ".join(r["failures"]) or "-"))
    lines += ["", "Overview image: overview.png (inspect it - appearance is part of the test)."]
    with open(os.path.join(out, "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
