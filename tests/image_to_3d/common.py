"""Shared post-reconstruction pipeline for the image-to-3D test cases (runs inside Blender).

Every case, whatever the mode: compare_views (silhouette IoU + diff sheet) -> asset report
(health, pivot, scale, engine-safe materials) -> bake if needed -> export Godot GLB + Unity FBX
(re-imported and verified) -> inspection sheet + beauty render. Timings per stage.
"""
import argparse
import os
import sys
import time

import bpy
from bkit import camera as C
from bkit import gameprep as GP
from bkit import lighting as L
from bkit import mesh as M
from bkit import preview as P
from bkit import recon as RC
from bkit import render as R
from bkit import scene as S

HERE = os.path.dirname(os.path.abspath(__file__))


def args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", default=os.path.join(HERE, "refs"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--beauty-res", type=int, default=640)
    a, _ = ap.parse_known_args(sys.argv[1:])
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    return a


class Timer:
    def __init__(self):
        self.t = {}
        self._t0 = time.time()
        self._last = self._t0

    def lap(self, name):
        now = time.time()
        self.t[name] = round(now - self._last, 2)
        self._last = now

    def total(self):
        return round(time.time() - self._t0, 2)


def finish(ob, views, out, name, timer, height_m, flip_side=False, bake=None, preview_mode="material",
           ref_m_per_px=None):
    """Run the common QA/export pipeline on one asset object. Returns a metrics dict.
    ref_m_per_px: known drawing scale -> silhouettes compared at true scale (see compare_views)."""
    res = {}
    # engine pivot convention: origin at the bottom centre, transforms applied (joined parts keep
    # the FIRST part's origin otherwise - found in T2: pivot sat on the antenna ball)
    res["normalize"] = GP.normalize(ob, origin="BOTTOM")
    res["compare"] = RC.compare_views([ob], views, os.path.join(out, "compare"), flip_side=flip_side,
                                      ref_m_per_px=ref_m_per_px)
    timer.lap("compare_s")
    if bake or (bake is None and any(GP.needs_bake(m) for m in ob.data.materials if m)):
        res["bake"] = GP.bake_materials(ob, size=1024, normal=False, out_dir=os.path.join(out, "textures"))
        timer.lap("bake_s")
    res["asset"] = GP.asset_report(ob)
    res["export_godot"] = GP.export(ob, os.path.join(out, name + ".glb"), engine="godot")
    res["export_unity"] = GP.export(ob, os.path.join(out, name + ".fbx"), engine="unity")
    timer.lap("export_s")
    # inspection sheet + a lit beauty shot
    ob["bk_subject"] = True
    if "bake" in res and preview_mode == "material":
        preview_mode = "texture"          # Workbench 'material' shows a baked image material as flat grey
    res["sheet"] = P.views(os.path.join(out, "views"), objs=[ob], views=("persp", "front", "right", "persp2", "top"),
                           res=400, mode=preview_mode)["sheet"]
    cam = C.add("CAM_Beauty", lens=50)
    C.frame(cam, [ob], azimuth=-30, elevation=15, margin=1.2)
    L.studio_backdrop(cam, [ob], color=(0.35, 0.36, 0.38))
    L.three_point([ob], style="soft")
    L.world_color((0.1, 0.1, 0.11), 1.0)
    R.configure(engine="CYCLES", quality="preview", resolution=(640, 480), device="CPU", samples=48)
    res["beauty"] = os.path.join(out, name + "_beauty.png")
    R.still(bpy.context.scene, res["beauty"])
    timer.lap("render_s")
    res["timings"] = dict(timer.t, total_s=timer.total())
    # trim heavy fields for the result JSON
    for k in ("export_godot", "export_unity"):
        res[k] = {"bytes": res[k]["bytes"], "verify": res[k].get("verify"), "warning": res[k].get("warning")}
    return res
