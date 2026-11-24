#!/usr/bin/env python3
"""Intelligent mode selector for image-to-3D. Standard library only.

    python scripts/ai3d/select_mode.py --analysis analysis.json --category robot
            [--style auto|voxel|lowpoly|stylized|realistic] [--fidelity draft|standard|high]
            [--needs rig,animation,game,print] [--json]

Inputs: the measured analysis (scripts/analyze_image.py), what the object is, what the result
must do, and the live hardware/model check (check.py). Output: the three modes scored with
REASONS, the recommended mode or hybrid plan, and what will be inferred rather than seen.
The scores support Claude's decision - they do not replace looking at the images.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check  # noqa: E402

GEOMETRIC = {"voxel", "robot", "building", "furniture", "weapon", "vehicle", "prop", "hard-surface",
             "equipment", "architecture", "environment-prop", "mechanical"}
ORGANIC = {"creature", "character", "animal", "organic", "plant", "food", "sculpture", "face"}


def select(analysis, category="other", style="auto", fidelity="standard", needs=(), hw_check=None):
    views = analysis.get("views", {})
    n = len(views)
    names = set(views)
    first = next(iter(views.values()), {})
    pixel_art = any(v.get("pixel_art") for v in views.values())
    flat = min((v.get("flatness", 0) for v in views.values()), default=0)
    sym = max((v.get("symmetry_lr", 0) for v in views.values()), default=0)
    hint = first.get("style_hint", "")
    if style == "auto":
        # flat colours describe the DRAWING (blueprint, elevation, concept), not the target style:
        # 'flat' is neutral; 'lowpoly' only when the user asks for low-poly output.
        style = "voxel" if pixel_art else "flat" if flat > 0.9 else             "stylized" if flat > 0.6 or hint.startswith("illustration") else "realistic"
    cat = category.lower()
    s1, s2, s3 = [], [], []          # (points, reason)
    # ---- Mode 1: procedural
    if style == "voxel":
        s1.append((5, "pixel-art grid detected - voxel reconstruction is exact at the native grid"))
    if style == "lowpoly":
        s1.append((2, "low-poly target - primitives and facets reproduce it faithfully"))
    if style in ("flat", "lowpoly"):
        s1.append((1, "flat artwork: clean regions measurable with imageref.segments"))
    if cat in GEOMETRIC:
        s1.append((2, "'%s' decomposes into geometric components" % cat))
    if sym > 0.9:
        s1.append((1, "left/right symmetric (%.2f) - mirror construction" % sym))
    if cat in ORGANIC and style in ("stylized", "realistic"):
        s1.append((-3, "organic %s shapes are poorly served by primitives" % cat))
    if fidelity == "high" and style == "realistic":
        s1.append((-2, "high-fidelity realistic target"))
    s1.append((1, "runs on any hardware, deterministic and editable"))
    # ---- Mode 2: reference-based
    ortho = names & {"front", "side", "top", "back"}
    if len(ortho) >= 2:
        s2.append((3 + (len(ortho) >= 3), "%d orthographic views (%s) constrain proportions" % (len(ortho), ", ".join(sorted(ortho)))))
    elif n == 1:
        s2.append((-1, "single view - depth must be estimated conservatively"))
        if cat in ORGANIC or style in ("stylized", "realistic"):
            s2.append((1, "single-view organic fallback: recon.inflate_from_image (faithful front, "
                          "depth guessed, plain back) - works on any machine"))
    if cat in GEOMETRIC - {"voxel"}:
        s2.append((2, "accurate proportions/clean hard edges matter for '%s'" % cat))
    if set(needs) & {"rig", "animation"}:
        s2.append((3, "rigging/animation needs controlled topology"))
    if fidelity == "high":
        s2.append((1, "high fidelity requested"))
    if style == "flat":
        s2.append((1, "clean blueprint/elevation edges - precise reference planes"))
    if analysis.get("consistency", {}).get("same_object_likely") is False:
        s2.append((-1, "views disagree in scale/palette - align or ask for consistent views"))
    if style == "voxel":
        s2.append((-2, "voxel art is reproduced exactly by Mode 1"))
    # ---- Mode 3: local AI
    usable = (hw_check or {}).get("usable_with_skill", [])
    installed = [k for k in usable if hw_check["models"][k]["installed"]]
    m3_possible = bool(usable)
    if not m3_possible:
        s3.append((-100, "no local AI model can run on this hardware: %s" % hw_check.get("recommendation") if hw_check else "hardware not checked"))
    else:
        if not installed:
            s3.append((-3, "compatible model(s) %s not installed (needs user-approved download)" % usable))
        on = {k: hw_check["models"][k]["run_on"] for k in usable}
        if all(v == "cpu" for v in on.values()):
            s3.append((-1, "CPU-only inference (minutes per image)"))
        if cat in ORGANIC:
            s3.append((4, "organic '%s' - AI captures soft volumes primitives cannot" % cat))
        if n == 1 and style in ("stylized", "realistic"):
            s3.append((2, "single %s image - AI hallucinates a plausible back side" % style))
        if style == "voxel":
            s3.append((-5, "AI reconstruction smooths away voxel/pixel structure"))
        if style in ("lowpoly", "flat"):
            s3.append((-2, "AI output is a dense smooth mesh - loses crisp facets/edges of flat artwork"))
        if cat in GEOMETRIC - {"voxel"}:
            s3.append((-2, "hard edges/straight lines come out soft and wobbly"))
        if len(ortho) >= 2:
            s3.append((-1, "supported models use ONE image; extra views only help validation"))
        if set(needs) & {"rig", "animation", "game"}:
            s3.append((-1, "output needs cleanup/decimation/retopology before rigging or engines"))
        if fidelity == "draft":
            s3.append((1, "fast first draft"))
    score = lambda L: sum(p for p, _ in L)  # noqa: E731
    modes = {"mode1_procedural": {"score": score(s1), "reasons": [r for _, r in s1]},
             "mode2_reference": {"score": score(s2), "reasons": [r for _, r in s2]},
             "mode3_local_ai": {"score": score(s3) if m3_possible else None, "reasons": [r for _, r in s3],
                                "models": usable, "installed": installed}}
    ranked = sorted(((k, v["score"]) for k, v in modes.items() if v["score"] is not None), key=lambda kv: -kv[1])
    best = ranked[0][0]
    plan = [best]
    if best == "mode3_local_ai":
        plan = ["mode3_local_ai: base mesh", "gameprep.cleanup + decimate", "mode2_reference: fix proportions vs compare_views",
                "mode1_procedural: crisp details (eyes, horns, accessories) where AI blurred them"]
    elif best == "mode2_reference" and cat in ORGANIC and m3_possible and installed:
        plan = ["mode3_local_ai: blockout volume", "mode2_reference: rebuild clean topology over it"]
    elif best == "mode2_reference" and n == 1:
        plan = ["mode2_reference: inflate_from_image + project_views(infer='plain')",
                "mode1_procedural: crisp details (eyes, horns, accessories)",
                "mode2_reference: compare_views; tell the user the depth/back are guessed - a side view "
                "or a capable GPU (Mode 3) would improve it"]
    elif best == "mode1_procedural" and style != "voxel" and len(ortho) >= 2:
        plan = ["mode1_procedural: components from measured segments", "mode2_reference: compare_views and adjust"]
    inferred = []
    if n == 1:
        inferred.append("everything not visible in the single view (back, sides' depth, underside)")
    elif "top" not in names:
        inferred.append("top-down outline (only front/side silhouettes constrain it)")
    if "back" not in names and n > 0:
        inferred.append("back surface details/colours (plain or mirrored from front - choose per subject)")
    return {"style": style, "category": cat, "n_views": n, "modes": modes, "ranking": ranked,
            "recommended": best, "plan": plan, "inferred": inferred}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--category", default="other")
    ap.add_argument("--style", default="auto")
    ap.add_argument("--fidelity", default="standard")
    ap.add_argument("--needs", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with open(a.analysis, encoding="utf-8") as f:
        analysis = json.load(f)
    hw = check.check()
    res = select(analysis, a.category, a.style, a.fidelity, [x for x in a.needs.split(",") if x], hw)
    res["hardware"] = {"recommendation": hw["recommendation"], "usable": hw["usable_with_skill"]}
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print("style=%s category=%s views=%d" % (res["style"], res["category"], res["n_views"]))
    for k, v in res["modes"].items():
        print("  %-17s score %s" % (k, v["score"] if v["score"] is not None else "n/a (cannot run)"))
        for r in v["reasons"]:
            print("      - " + r)
    print("=> recommended:", res["recommended"])
    print("   plan:", " -> ".join(res["plan"]))
    if res["inferred"]:
        print("   will be INFERRED (state this to the user):", "; ".join(res["inferred"]))
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
