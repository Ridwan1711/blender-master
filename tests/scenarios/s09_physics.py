"""S09 - Physics: rigid-body tower knocked over by a heavy ball + cloth draped over a sphere.

Exercises: rigid body world/objects via operators with overrides (headless), frame-stepped
simulation, bake to keyframes (deterministic file), cloth + collision, numeric checks
(no tunnelling through the floor, tower actually fell, cloth rests on the sphere).
Run: python scripts/bk.py run tests/scenarios/s09_physics.py --save OUT/s09.blend
"""
import math

import bpy

from bkit import camera as C
from bkit import emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import physics as P
from bkit import render as R
from bkit import scene as S

END = 90
S.new_scene(frame_range=(1, END))
# a SOLID floor slab (top at z=0): zero-thickness planes let heavy bodies sink into them
floor = M.box("GEO_Floor", (12, 12, 0.3), location=(0, 0, -0.15), coll="Environment")
MT.assign(floor, MT.concrete("MAT_FloorConcrete"))

# ---- rigid tower: 5 levels x 3 boxes, staggered like a brick stack
wood = MT.wood("MAT_Blocks")
boxes = []
for lvl in range(5):
    for i in range(3):
        rot = (lvl % 2) * math.pi / 2
        off = (i - 1) * 0.21
        x, y = (off, 0) if lvl % 2 == 0 else (0, off)
        b = M.box("GEO_Block_%d_%d" % (lvl, i), (0.2, 0.6, 0.2) if lvl % 2 == 0 else (0.6, 0.2, 0.2),
                  location=(x - 1.0, y, 0.1 + lvl * 0.2), coll="Tower")
        MT.assign(b, wood)
        boxes.append(b)
ball = M.sphere("GEO_WreckingBall", 0.25, location=(-1.0 - 2.4, 0.0, 1.6), coll="Tower", segments=32, rings=16)
MT.assign(ball, MT.metal("MAT_Iron", "iron", roughness=0.5))
# ramp to roll the ball into the tower
ramp = M.box("GEO_Ramp", (1.6, 0.8, 0.05), location=(-1.0 - 2.3, 0.0, 0.62), rotation=(0, math.radians(28), 0),
             coll="Tower")
MT.assign(ramp, MT.principled("MAT_Ramp", MT.hex_color("#3A3F47"), roughness=0.5))

P.rigid_world(1, END)
P.rigid(floor, "PASSIVE", shape="BOX", friction=0.8)
P.rigid(ramp, "PASSIVE", shape="BOX", friction=0.2)
for b in boxes:
    P.rigid(b, "ACTIVE", mass=0.8, shape="BOX", friction=0.6)
P.rigid(ball, "ACTIVE", mass=25.0, shape="SPHERE", friction=0.3, bounce=0.05)
P.remember_start(boxes)

# ---- cloth over a sphere at x = +1.6
post = M.sphere("GEO_ClothSphere", 0.45, location=(1.6, 0, 0.45), coll="Cloth", segments=48, rings=24)
MT.assign(post, MT.ceramic("MAT_Sphere", MT.hex_color("#D8D2C8")))
P.collision(post)
P.collision(floor)
sheet = M.plane("GEO_ClothSheet", (1.6, 1.6), location=(1.6, 0, 1.4), coll="Cloth", subdivisions=40)
MT.assign(sheet, MT.fabric("MAT_Cloth", MT.hex_color("#8C2F39"), weave_scale=120))
P.cloth(sheet, mass=0.3, frame_start=1, frame_end=END)
M.solidify(sheet, 0.004, even=False)  # even thickness spikes at sharp cloth folds
M.subsurf(sheet, 1)

# step the sim; check the cloth EVERY frame after it settles (single-frame spikes are defects)
sc = bpy.context.scene
spikes, zs = [], []
for f in range(1, END + 1):
    sc.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = sheet.evaluated_get(dg)
    zs = [(ev.matrix_world @ v.co).z for v in ev.to_mesh().vertices]
    ev.to_mesh_clear()
    if f > 30 and max(zs) > 1.05:
        spikes.append(f)
steps = END
rep = P.settle_report(boxes + [ball], floor_z=0.0, tol=0.02)  # heavy bodies sink ~1 cm into the margin
cloth = {"min_z": round(min(zs), 3), "max_z": round(max(zs), 3), "sphere_top": 0.9, "spike_frames": spikes}

# make the rigid result deterministic in the saved file
P.bake_to_keyframes(boxes + [ball], 1, END)
bpy.context.scene.frame_set(END)

for o in boxes + [ball, post, sheet]:
    o["bk_subject"] = True
cam = C.add("CAM_Physics", lens=32)
C.frame(cam, boxes + [ball, post, sheet], azimuth=-20, elevation=20, margin=1.2)
L.three_point(boxes + [post], style="soft")
L.world_color((0.05, 0.055, 0.06), 1.0)
R.configure(engine="CYCLES", quality="preview", resolution=(1280, 720), device="CPU")
emit(steps=steps, rigid=rep, cloth=cloth,
     tower_fell=rep["moved"] >= 5, no_tunnelling=not rep["below_floor"],
     cloth_on_sphere=cloth["max_z"] > 0.85 and cloth["max_z"] < 1.05, cloth_stable=not spikes)
