"""T2 - Low-poly robot from flat concept art (front + side). Mode 1 (measured components) with a
Mode 2 check (compare_views).

Selector: style=lowpoly, category=robot -> Mode 1 (7) > Mode 2 (5); plan: components then compare.
components_from_views measures every part (colour family + touching regions) in both views,
detects round parts (empty bbox corners) and taper (robust fit of row extents), places decals as
thin panels on their container, and FLAGS ambiguous depths. Judgement after looking at the side
view: arms/hands are drawn over the torso there, so their depth = their own width (overrides).
"""
import os

from bkit import compat, emit
from bkit import mesh as M
from bkit import recon as RC
from bkit import scene as S
import common

a = common.args()
t = common.Timer()
S.new_scene()
R = os.path.join(a.refs, "lowpoly_robot")
views = {"front": os.path.join(R, "front.png"), "side": os.path.join(R, "side.png")}
H = 1.62
# first pass only to read the measurement table (which parts are ambiguous)
probe_objs, table = RC.components_from_views(views["front"], views["side"], H, name="Probe")
overrides = {}
for row in table:
    if row.get("ambiguous"):
        w = row["x"][1] - row["x"][0]
        overrides[row["part"]] = {"depth": round(w, 4), "y": 0.0}
import bpy  # noqa: E402
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
S.purge_orphans()
objs, table = RC.components_from_views(views["front"], views["side"], H, name="Robot", overrides=overrides)
t.lap("build_s")
robot = M.join(objs, "GEO_LowPolyRobot")
compat.shade_flat(robot)
t.lap("join_s")
res = common.finish(robot, views, a.out, "lowpoly_robot", t, height_m=H)
emit(case="lowpoly_robot", mode="1 procedural components (+2 compare)", parts=len(table),
     overrides=overrides, inferred=[r["part"] for r in table if r.get("inferred_depth") or r.get("shape_note")],
     shapes=sorted({r["shape"].split(" (")[0] for r in table}), **res)
