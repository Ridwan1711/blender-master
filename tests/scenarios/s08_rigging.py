"""S08 - Rigging & character animation.

A) Mechanical robot arm: armature from data, IK chain with pole, rigid part binding,
   animated IK target; verified numerically (end effector reaches the target).
B) Character: skin-modifier mannequin, matching armature, automatic (heat) weights,
   procedural walk cycle with F-curve cycles; verified via weight report.
Run: python scripts/bk.py run tests/scenarios/s08_rigging.py --save OUT/s08.blend
"""
import math

import bpy
from mathutils import Vector

from bkit import anim as A
from bkit import camera as C
from bkit import emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import rig as RG
from bkit import scene as S

S.new_scene(frame_range=(1, 48))

# ------------------------------------------------------------------ A) robot arm at x = -1.2
X0 = Vector((-1.2, 0, 0))
# IK needs a PRE-BEND: a perfectly straight chain gives the solver no bend direction and it
# just points at the target fully stretched (measured: 0.40 m miss). Elbow nudged toward the pole.
arm = RG.armature("RIG_RobotArm", [
    dict(name="base", head=(0, 0, 0), tail=(0, 0, 0.25)),
    dict(name="upper", head=(0, 0, 0.25), tail=(0, 0.05, 0.85), parent="base", connect=True),
    dict(name="fore", head=(0, 0.05, 0.85), tail=(0, 0.0, 1.35), parent="upper", connect=True),
], coll="RobotArm", location=tuple(X0))
steel = MT.metal("MAT_ArmSteel", "steel", roughness=0.35)
paint = MT.plastic("MAT_ArmPaint", MT.hex_color("#E0A100"), roughness=0.4)
parts = [
    ("GEO_ArmBase", M.cylinder("GEO_ArmBase", 0.16, 0.25, location=X0 + Vector((0, 0, 0.125)), coll="RobotArm"), "base", steel),
    ("GEO_ArmUpper", M.box("GEO_ArmUpper", (0.1, 0.1, 0.6), location=X0 + Vector((0, 0, 0.55)), coll="RobotArm"), "upper", paint),
    ("GEO_ArmFore", M.box("GEO_ArmFore", (0.08, 0.08, 0.5), location=X0 + Vector((0, 0, 1.1)), coll="RobotArm"), "fore", paint),
    ("GEO_ArmJoint", M.sphere("GEO_ArmJoint", 0.075, location=X0 + Vector((0, 0, 0.85)), coll="RobotArm"), "upper", steel),
]
for _, ob, bone, mat in parts:
    MT.assign(ob, mat)
    RG.bind_rigid(ob, arm, bone)
target = RG.ik(arm, "fore", target=tuple(X0 + Vector((0.5, -0.3, 0.6))), chain=2,
               pole=tuple(X0 + Vector((0, 0.8, 0.9))))
A.keys(target, "location", [(1, tuple(X0 + Vector((0.55, -0.3, 0.55)))),
                            (24, tuple(X0 + Vector((-0.2, -0.55, 1.0)))),
                            (48, tuple(X0 + Vector((0.55, -0.3, 0.55))))])
reach = []
for f in (1, 24, 48):
    bpy.context.scene.frame_set(f)
    head, tail = RG.bone_world_head(arm, "fore")
    reach.append(round((tail - target.matrix_world.translation).length, 4))

# ------------------------------------------------------------------ B) character at x = +0.6
body, crig, report = RG.mannequin("Mannequin", coll="Character", location=(0.6, 0, 0))
MT.assign(body, MT.principled("MAT_Mannequin", MT.hex_color("#C9B9A6"), roughness=0.55))
RG.walk_cycle(crig, frames=24, start=1)
body["bk_subject"] = True
for _, ob, _, _ in parts:
    ob["bk_subject"] = True

# ------------------------------------------------------------------ shot
floor = M.plane("GEO_Floor", (8, 8), coll="Environment")
MT.assign(floor, MT.principled("MAT_Floor", MT.hex_color("#55585E"), roughness=0.7))
cam = C.add("CAM_Rig", lens=35)
C.frame(cam, [body] + [p[1] for p in parts], azimuth=-25, elevation=12, margin=1.25)
L.three_point([body] + [p[1] for p in parts], style="soft")
L.world_color((0.05, 0.055, 0.06), 1.0)
R.configure(engine="CYCLES", quality="preview", resolution=(1280, 720), device="CPU")
bpy.context.scene.frame_set(1)
emit(ik_reach_error_m=reach, weights=report, character_verts=len(body.data.vertices),
     bones=len(crig.data.bones))
