#!/usr/bin/env python3
"""Image-to-3D test campaign: 5 reference sets x (analysis -> mode selection -> reconstruction ->
QA/export) with acceptance thresholds, a summary table and an overview sheet to LOOK at.

    python tests/image_to_3d/run_i3d_tests.py [--only t1,t3] [--skip-ai] [--out DIR]

Mode 3 (T5 ai) runs only if the hardware/model check says a local model is usable; otherwise the
case is reported SKIPPED with the reason and the Mode 2 fallback still runs (graceful degradation).
A case passes on MEASURED results (silhouette IoU, mesh health, re-imported exports, counts),
never on "the script ran" - and the overview sheet is there to be inspected anyway.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from bk import run_blender  # noqa: E402

REFS = os.path.join(HERE, "refs")
CASES = [  # id, script, ref set, views, selector args, extra script args
    ("t1", "t1_voxel_knight.py", "voxel_knight", ("front", "side"), ["--category", "character"], []),
    ("t2", "t2_lowpoly_robot.py", "lowpoly_robot", ("front", "side"), ["--category", "robot", "--style", "lowpoly"], []),
    ("t3", "t3_medieval_house.py", "medieval_house", ("front", "side"), ["--category", "building"], []),
    ("t4", "t4_walkie_talkie.py", "walkie_talkie", ("front", "side", "top"), ["--category", "equipment"], []),
    ("t5_ai", "t5_fantasy_creature.py", "fantasy_creature", ("front",), ["--category", "creature"], ["--variant", "ai"]),
    ("t5_fallback", "t5_fantasy_creature.py", "fantasy_creature", ("front",), ["--category", "creature"],
     ["--variant", "fallback"]),
]


def iou(res, view):
    v = (res.get("compare") or {}).get(view) or {}
    return v.get("iou", 0.0)


def verified(res):
    out = []
    for k in ("export_godot", "export_unity"):
        v = (res.get(k) or {}).get("verify") or {}
        out.append(bool(v.get("tris_match")) and bool(v.get("dims_match")) and bool(v.get("textured_materials") or
                                                                                    v.get("materials")))
    return all(out)


def accept(cid, r):
    """Acceptance checks per case -> list of failures (empty = pass)."""
    f = []
    h = (r.get("asset") or {}).get("health") or {}

    def need(cond, label):
        if not cond:
            f.append(label)
    need(verified(r), "GLB/FBX re-import verification")
    need((r.get("asset") or {}).get("pivot_at_bottom_centre"), "pivot at bottom centre")
    need((r.get("asset") or {}).get("engine_safe_materials"), "engine-safe materials")
    if cid == "t1":
        need(iou(r, "front") >= 0.95 and iou(r, "side") >= 0.95, "IoU >= 0.95 front+side")
        need(h.get("closed"), "closed mesh")
    elif cid == "t2":
        need(r["compare"].get("mean_iou", 0) >= 0.90, "mean IoU >= 0.90")
        need(h.get("closed"), "closed parts")
    elif cid == "t3":
        need(iou(r, "front") >= 0.93 and iou(r, "side") >= 0.97, "metric IoU front >= 0.93, side >= 0.97")
        need((r.get("consistency") or {}).get("scale_consistent"), "elevations agree on scale")
        need((r.get("openings") or {}).get("door"), "door found")
    elif cid == "t4":
        need(all(iou(r, v) >= 0.97 for v in ("front", "side", "top")), "metric IoU >= 0.97 in 3 views")
        m = r.get("measurements") or {}
        need(m.get("grille_holes") == 25 and m.get("buttons") == 3, "25 grille holes + 3 buttons")
        need(h.get("closed"), "closed mesh")
    elif cid == "t5_ai":
        need(iou(r, "front") >= 0.80, "IoU >= 0.80")
        need(len(r.get("eyes") or []) == 2, "2 procedural eyes placed")
    elif cid == "t5_fallback":
        need(iou(r, "front") >= 0.88, "IoU >= 0.88")
        need(len(r.get("eyes") or []) == 2, "2 procedural eyes placed")
        need(h.get("closed"), "closed mesh")
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--skip-ai", action="store_true", help="do not run local AI inference (Mode 3)")
    ap.add_argument("--out", default=os.path.join(ROOT, "tests", "output", "i3d"))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    kw = dict(log_lines=0, json_only=True, timeout=3600)
    rows = []
    t_all = time.time()
    for cid, script, ref, vnames, sel_args, extra in CASES:
        if only and cid not in only and cid.split("_")[0] not in only:
            continue
        print("[i3d] %s %s ..." % (cid, script), flush=True)
        row = {"id": cid, "case": ref, "failures": [], "status": "FAIL"}
        cdir = os.path.join(out, cid)
        os.makedirs(cdir, exist_ok=True)
        # 1. analysis + mode selection (what the selector would recommend for these images)
        ana = os.path.join(out, ref + "_analysis.json")
        vargs = ["%s=%s" % (v, os.path.join(REFS, ref, v + ".png")) for v in vnames]
        devnull = open(os.devnull, "w")
        old, sys.stdout = sys.stdout, devnull
        try:
            run_blender(script=os.path.join(ROOT, "scripts", "analyze_image.py"), args=vargs + ["--out", ana],
                        tag="i3d_ana", **kw)
        finally:
            sys.stdout = old
            devnull.close()
        sel = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ai3d", "select_mode.py"), "--analysis", ana,
                              "--json"] + sel_args, capture_output=True, text=True)
        try:
            mode = json.loads(sel.stdout)
            row["selector"] = {"style": mode.get("style"), "recommended": mode.get("recommended"),
                               "ranking": mode.get("ranking"),
                               "plan": mode.get("plan")}
        except ValueError:
            row["selector"] = {"error": sel.stderr[-300:]}
        # 2. Mode 3 inference outside Blender (only if the check allows it)
        if cid == "t5_ai":
            glb = os.path.join(cdir, "creature_triposr.glb")
            chk = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ai3d", "check.py"), "--json"],
                                 capture_output=True, text=True)
            try:
                usable = json.loads(chk.stdout).get("usable_with_skill") or []
            except ValueError:
                usable = []
            if not usable or a.skip_ai:
                row.update(status="SKIPPED", reason="--skip-ai" if a.skip_ai else
                           "no local AI model usable on this hardware (check.py) - Mode 2 fallback covers it")
                rows.append(row)
                print("       SKIPPED (%s)" % row["reason"], flush=True)
                continue
            if not os.path.exists(glb):
                t0 = time.time()
                rm = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ai3d", "run_model.py"), "triposr",
                                     "--image", os.path.join(REFS, ref, "front.png"), "--out", glb, "--mc-res", "256"],
                                    capture_output=True, text=True)
                row["ai_inference"] = {"exit": rm.returncode, "wall_s": round(time.time() - t0, 1)}
                if rm.returncode != 0:
                    row["failures"].append("AI inference failed: " + rm.stdout[-300:] + rm.stderr[-300:])
                    rows.append(row)
                    continue
            try:
                row["ai_inference"] = json.load(open(glb[:-4] + "_ai3d.json"))
                row["ai_inference"] = {k: row["ai_inference"].get(k) for k in ("model", "run_on", "total_s", "timings",
                                                                                 "peak_ram_mb", "cpu_seconds", "verts")}
            except (OSError, ValueError):
                pass
            extra = extra + ["--glb", glb]
        # 3. reconstruction + common QA/export pipeline
        t0 = time.time()
        devnull = open(os.devnull, "w")
        old, sys.stdout = sys.stdout, devnull
        try:
            code, res = run_blender(script=os.path.join(HERE, script), args=["--out", cdir] + extra,
                                    save=os.path.join(cdir, ref + ".blend"), overwrite=True, tag="i3d_" + cid, **kw)
        finally:
            sys.stdout = old
            devnull.close()
        row["wall_s"] = round(time.time() - t0, 1)
        if code != 0 or not res or res.get("status") not in (None, "ok"):
            row["failures"].append("run failed: %s" % ((res or {}).get("error") or code))
            rows.append(row)
            print("       FAIL (run)", flush=True)
            continue
        json.dump(res, open(os.path.join(cdir, "result.json"), "w"), indent=1, default=str)
        row["metrics"] = {
            "mode": res.get("mode"),
            "iou": {k: v.get("iou") for k, v in (res.get("compare") or {}).items() if isinstance(v, dict)},
            "tris": (res.get("asset") or {}).get("tris"),
            "dims_m": (res.get("asset") or {}).get("dims_m"),
            "closed": ((res.get("asset") or {}).get("health") or {}).get("closed"),
            "non_manifold_edges": ((res.get("asset") or {}).get("health") or {}).get("multi_face_edges"),
            "exports_verified": verified(res),
            "timings": res.get("timings"),
            "process": res.get("process"),
            "inferred": res.get("inferred"),
        }
        row["images"] = {"beauty": res.get("beauty"), "compare": (res.get("compare") or {}).get("sheet"),
                         "sheet": res.get("sheet")}
        row["failures"] += accept(cid, res)
        row["status"] = "PASS" if not row["failures"] else "FAIL"
        rows.append(row)
        print("       %s  IoU %s  tris %s  %ss" % (row["status"], row["metrics"]["iou"], row["metrics"]["tris"],
                                                   row["wall_s"]), flush=True)
    summary = {"cases": rows, "passed": sum(r["status"] == "PASS" for r in rows),
               "failed": sum(r["status"] == "FAIL" for r in rows), "skipped": sum(r["status"] == "SKIPPED" for r in rows),
               "wall_s": round(time.time() - t_all, 1)}
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1, default=str)
    overview(rows, os.path.join(out, "overview.png"))
    print("[i3d] %d passed, %d failed, %d skipped  (%.0fs)  -> %s" % (summary["passed"], summary["failed"],
          summary["skipped"], summary["wall_s"], os.path.join(out, "summary.json")))
    return 0 if summary["failed"] == 0 else 1


def overview(rows, path):
    """One row per case: reference | beauty | silhouette diff sheet (needs Pillow; skipped otherwise)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    H = 260
    strips = []
    for r in rows:
        if r["status"] == "SKIPPED" or "images" not in r:
            continue
        ims = [Image.open(os.path.join(REFS, r["case"], "front.png")).convert("RGB")]
        for k in ("beauty", "compare"):
            p = r["images"].get(k)
            if p and os.path.exists(p):
                ims.append(Image.open(p).convert("RGB"))
        ims = [i.resize((max(1, int(i.width * H / i.height)), H)) for i in ims]
        s = Image.new("RGB", (sum(i.width for i in ims) + 8 * len(ims), H + 22), (30, 30, 32))
        x = 0
        for i in ims:
            s.paste(i, (x, 22))
            x += i.width + 8
        ImageDraw.Draw(s).text((6, 4), "%s  %s  %s  IoU %s" % (r["id"], r["status"], r["metrics"]["mode"],
                                                               r["metrics"]["iou"]), fill=(235, 235, 235))
        strips.append(s)
    if not strips:
        return None
    W = max(s.width for s in strips)
    sheet = Image.new("RGB", (W, sum(s.height for s in strips)), (30, 30, 32))
    y = 0
    for s in strips:
        sheet.paste(s, (0, y))
        y += s.height
    sheet.save(path)
    return path


if __name__ == "__main__":
    sys.exit(main())
