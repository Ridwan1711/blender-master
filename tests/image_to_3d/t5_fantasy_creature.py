"""T5 - Stylized fantasy creature from ONE painted image.

Selector: style=stylized (shaded painting), single view, organic -> Mode 3 (local AI, CPU) with the
hybrid plan "mode3 base -> cleanup + decimate -> mode2 compare -> mode1 crisp details".

--variant ai        Mode 3 + hybrid. TripoSR ran OUTSIDE Blender (scripts/ai3d/run_model.py: own
                    process, low priority, offline) -> import -> align_to_reference (24 orientations,
                    front/back tie settled by colour) -> cleanup (AI debris) -> decimate -> bake the
                    vertex colours to a texture -> Mode 1 detail: procedural glossy eyes placed by
                    ray-casting the eye centres measured in the image (AI eyes are blurry paint).
--variant fallback  Mode 2 single-image fallback for machines where Mode 3 is unavailable:
                    recon.inflate_from_image (balloon depth from the silhouette) + the same eyes.
The size is not given: height ASSUMED 1.0 m (reported). Comparison is scale-free (shape IoU).
"""
import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from bkit import emit
from bkit import gameprep as GP
from bkit import imageref as IR
from bkit import materials as MT
from bkit import mesh as M
from bkit import recon as RC
from bkit import scene as S
import common

a = common.args()
ap = argparse.ArgumentParser()
ap.add_argument("--variant", choices=("ai", "fallback"), default="ai")
ap.add_argument("--glb", default=None)
ap.add_argument("--target-tris", type=int, default=8000)
v_args, _ = ap.parse_known_args(sys.argv[1:])
t = common.Timer()
S.new_scene()
REF = os.path.join(a.refs, "fantasy_creature", "front.png")
views = {"front": REF}
H = 1.0                                        # assumed height (not given by the brief)
info = {}

if v_args.variant == "ai":
    glb = v_args.glb or os.path.join(os.path.dirname(a.out), "creature_triposr.glb")
    ob = RC.import_mesh(glb, name="GEO_Creature", height_m=H)
    info["imported"] = M.stats(ob)
    t.lap("import_s")
    info["align"] = RC.align_to_reference(ob, views, os.path.join(a.out, "align"))
    t.lap("align_s")
    info["cleanup"] = GP.cleanup(ob, min_part_ratio=0.01)
    info["decimate"] = GP.decimate(ob, target_tris=v_args.target_tris)
    GP.normalize(ob, height_m=H)
    t.lap("cleanup_decimate_s")
    info["bake"] = GP.bake_materials(ob, size=1024, maps=("Base Color",), normal=False,
                                     out_dir=os.path.join(a.out, "textures"))
    t.lap("bake_s")
else:
    ob, info["inflate"] = RC.inflate_from_image(REF, H, thickness=0.75, res=128, name="GEO_Creature")
    info["decimate"] = GP.decimate(ob, target_tris=v_args.target_tris)
    GP.normalize(ob, height_m=H)
    t.lap("inflate_s")

# ---------------------------------------------------------------- Mode 1 detail: eyes
# Where are the eyes ON THE MESH? Best source: the model's own colours (the AI painted them, the
# fallback projected the image) - found in a flat front render. Fallback: the reference image
# registered onto the silhouette (register_view). Sizes always come from what was found.
white_m = MT.principled("MAT_EyeWhite", (0.9, 0.9, 0.9, 1), roughness=0.08)
pupil_m = MT.principled("MAT_Pupil", (0.012, 0.012, 0.015, 1), roughness=0.05)


def eye_blobs(img, mask, white_thr, dark_thr):
    """Eyes = near-neutral light ellipses WITH a dark pupil inside (a cream belly is not an eye)."""
    rgb = img[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    white = mask & (mn > white_thr) & (mx - mn < 0.08)
    dark = mask & (mx < dark_thr)
    out = []
    for b in IR.blobs(IR.opening(white, 1), int(0.003 * mask.sum())):
        if len(out) == 2:
            break
        bx0, by0, bx1, by1 = b["bbox_px"]
        fill = (white | dark)[by0:by1, bx0:bx1].mean()   # white + pupil = a filled ellipse (pi/4 ~ 0.79)
        if fill < 0.6:
            continue
        pup = IR.blobs(dark[by0:by1, bx0:bx1], 6)
        if not pup:
            continue
        px0, py0, px1, py1 = pup[0]["bbox_px"]
        pb = (bx0 + (px0 + px1) / 2, by0 + (py0 + py1) / 2, (px1 - px0) / 2, (py1 - py0) / 2)
        out.append({"c": ((bx0 + bx1) / 2, (by0 + by1) / 2), "r": ((bx1 - bx0) / 2, (by1 - by0) / 2), "pupil": pb})
    return out


RES = 512
img_m, mpp = RC.render_colour([ob], "front", os.path.join(a.out, "front_colour.png"), RES, "TEXTURE",
                              return_scale=True)
_, _, _, cb = M.world_bounds([ob])
found = eye_blobs(img_m, img_m[..., 3] > 0.5, 0.75, 0.45)     # AI/projected paint is softer
V = RC.load_views(views)
ref_eyes = eye_blobs(V["front"]["img"], V["front"]["mask"], 0.9, 0.2)
# positions from the model's paint, PROPORTIONS from the sharp drawing (blurry AI paint shrinks
# the dark pupil core - found by inspection: pupils came out 35% too small)
pupil_ratio = (float(np.mean([e["pupil"][2] / e["r"][0] for e in ref_eyes])),
               float(np.mean([e["pupil"][3] / e["r"][1] for e in ref_eyes]))) if ref_eyes else None
if len(found) == 2:
    source = "model texture (front render)"

    def to_world(px, py):
        return cb.x + (px - RES / 2) * mpp, cb.z - (py - RES / 2) * mpp
    scale = mpp
else:
    reg = RC.register_view([ob], REF, "front")
    found = ref_eyes
    source = "reference image registered on the silhouette"
    to_world, scale = reg["to_world"], reg["m_per_ref_px"]
eyes = []
for i, e_ in enumerate(found):
    ex, ez = to_world(*e_["c"])
    rx, rz = e_["r"][0] * scale, e_["r"][1] * scale
    ok, loc, nrm, _ = ob.ray_cast(Vector((ex, -10.0, ez)), Vector((0, 1, 0)))
    if not ok:
        continue
    ry = 0.6 * rx
    e = M.sphere("GEO_Eye%d" % i, 1.0, segments=24, rings=12, coll="Reconstruction")
    e.data.transform(Matrix.Diagonal((rx, ry, rz, 1)))
    cy = loc.y + 0.45 * ry                      # 55% of the eye stands proud of the surface
    e.location = (ex, cy, ez)
    MT.assign(e, white_m)
    pinfo = None
    if e_["pupil"]:
        px_, pz_ = to_world(e_["pupil"][0], e_["pupil"][1])
        prx, prz = (pupil_ratio[0] * rx, pupil_ratio[1] * rz) if pupil_ratio else             (e_["pupil"][2] * scale, e_["pupil"][3] * scale)
        u = max(0.0, 1 - ((px_ - ex) / rx) ** 2 - ((pz_ - ez) / rz) ** 2)
        surf_y = cy - ry * math.sqrt(u)          # front surface of the eye at the pupil centre
        p = M.sphere("GEO_Pupil%d" % i, 1.0, segments=16, rings=8, coll="Reconstruction")
        p.data.transform(Matrix.Diagonal((prx, 0.35 * prx, prz, 1)))
        p.location = (px_, surf_y + 0.2 * prx, pz_)
        MT.assign(p, pupil_m)
        pinfo = [round(px_, 4), round(pz_, 4), round(prx, 4)]
    eyes.append({"centre_m": [round(ex, 4), round(cy, 4), round(ez, 4)], "radii_m": [round(rx, 4), round(ry, 4),
                 round(rz, 4)], "surface_hit_y": round(loc.y, 4), "pupil": pinfo})
t.lap("eyes_s")
if eyes:
    for o in [o for o in bpy.data.objects if o.name.startswith(("GEO_Eye", "GEO_Pupil"))]:
        M.apply_transform(o, location=True)
    ob = M.join([ob] + [o for o in bpy.data.objects if o.name.startswith(("GEO_Eye", "GEO_Pupil"))], "GEO_Creature")
res = common.finish(ob, views, a.out, "creature_" + v_args.variant, t, height_m=H, bake=False,
                    preview_mode="texture")
emit(case="fantasy_creature", variant=v_args.variant,
     mode="3 local AI (TripoSR CPU) + 1 detail" if v_args.variant == "ai" else "2 single-image fallback (inflate) + 1 detail",
     assumed_height_m=H, steps=info, eyes=eyes,
     eye_source=source,
     inferred=["entire back and all depth (single view)", "size (assumed 1.0 m)",
               "eye depth / protrusion"], **res)
