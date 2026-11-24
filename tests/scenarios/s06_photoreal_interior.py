"""S06 - Photorealistic still: morning light through a window onto a breakfast table.

Exercises: asset reuse (the S01 mug is APPENDED from its .blend), architectural modelling
(wall with boolean window opening, sill, floor), sun + physical sky through a window
(motivated light), glass and liquid, shallow DOF, grey-card metering with a temporary card,
Cycles final-tier settings.
Run: python scripts/bk.py run tests/scenarios/s06_photoreal_interior.py --save OUT/s06.blend -- --mug OUT/s01_mug.blend
"""
import argparse
import math
import sys

import bpy
from mathutils import Vector

from bkit import camera as C
from bkit import emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import scene as S

ap = argparse.ArgumentParser()
ap.add_argument("--mug", required=True, help="path to the S01 .blend")
a = ap.parse_args(sys.argv[1:])

S.new_scene()

# ---------------------------------------------------------------- room shell (interior faces)
plaster = MT.concrete("MAT_Plaster", MT.hex_color("#D9D3C7"), roughness=0.92, scale=2.0)
floor = M.box("GEO_Floor", (6, 6, 0.1), location=(0, 0, -0.05), coll="Room")
M.box_uv(floor, scale=1.0)
MT.assign(floor, MT.wood("MAT_FloorOak", light=MT.hex_color("#9A6B43"), dark=MT.hex_color("#5C3A22"),
                         scale=1.2, roughness=0.38))
back = M.box("GEO_WallBack", (6, 0.2, 3.0), location=(0, 1.6, 1.5), coll="Room")
side = M.box("GEO_WallLeft", (0.2, 6, 3.0), location=(-1.4, 0, 1.5), coll="Room")
# closed room: light may only enter through the window (motivated lighting)
right = M.box("GEO_WallRight", (0.2, 6, 3.0), location=(1.9, 0, 1.5), coll="Room")
front = M.box("GEO_WallFront", (6, 0.2, 3.0), location=(0, -2.6, 1.5), coll="Room")
ceiling = M.box("GEO_Ceiling", (6, 6, 0.1), location=(0, 0, 3.05), coll="Room")
for w in (back, side, right, front, ceiling):
    MT.assign(w, plaster)
    w["bk_allow_intersect"] = True  # wall slabs overlap at the corners by design
# window opening in the left wall (live boolean) + sill
win_cut = M.box("CUT_Window", (0.6, 1.1, 1.2), location=(-1.4, 0.35, 1.55), coll="Room")
M.boolean(side, win_cut)
sill = M.box("GEO_WindowSill", (0.32, 1.2, 0.04), location=(-1.36, 0.35, 0.94), coll="Room")
M.bevel(sill, 0.006, 2)
MT.assign(sill, MT.principled("MAT_SillPaint", MT.hex_color("#EDEBE6"), roughness=0.35))
sill["bk_allow_intersect"] = True  # sill is embedded in the wall opening

# ---------------------------------------------------------------- table
table_wood = MT.wood("MAT_Walnut", light=MT.hex_color("#7A5034"), dark=MT.hex_color("#3E2414"),
                     scale=2.5, roughness=0.32)
top = M.box("GEO_TableTop", (1.4, 0.8, 0.04), location=(-0.35, 0.6, 0.74), coll="Table")
M.bevel(top, 0.008, 3)
MT.assign(top, table_wood)
for sx in (-1, 1):
    for sy in (-1, 1):
        leg = M.box("GEO_TableLeg_%d%d" % (sx + 1, sy + 1), (0.05, 0.05, 0.72),
                    location=(-0.35 + sx * 0.62, 0.6 + sy * 0.32, 0.36), coll="Table")
        M.bevel(leg, 0.004, 2)
        MT.assign(leg, table_wood)
TOP_Z = 0.76

# ---------------------------------------------------------------- props
mug_parts = S.append(a.mug, objects=["GEO_Mug", "GEO_MugHandle", "GEO_Coffee"], coll="Props")
mug = bpy.data.objects["GEO_Mug"]
mug.location = (-0.25, 0.55, TOP_Z)
mug.rotation_euler.z = math.radians(-35)

glass_profile = [(0.0, 0.0), (0.034, 0.0), (0.036, 0.004), (0.038, 0.11), (0.0365, 0.11),
                 (0.0345, 0.008), (0.0, 0.006)]
glass = M.lathe("GEO_Glass", glass_profile, segments=64, location=(-0.05, 0.72, TOP_Z), coll="Props")
MT.assign(glass, MT.glass("MAT_GlassClear", roughness=0.0, ior=1.5))
# (no liquid volume: keep the test focused on glass; see materials.md for liquids.)

plate = M.lathe("GEO_Plate", [(0.0, 0.0), (0.07, 0.0), (0.075, 0.004), (0.12, 0.012), (0.125, 0.016),
                              (0.12, 0.017), (0.075, 0.009), (0.0, 0.007)], segments=96,
                location=(-0.52, 0.5, TOP_Z), coll="Props")
MT.assign(plate, MT.ceramic("MAT_PlateWhite", MT.hex_color("#F2F0EB"), roughness=0.08))
book = M.box("GEO_Book", (0.17, 0.24, 0.03), origin="BOTTOM", location=(-0.72, 0.78, TOP_Z),
             rotation=(0, 0, math.radians(12)), coll="Props")
M.bevel(book, 0.003, 2)
MT.assign(book, MT.fabric("MAT_BookCloth", MT.hex_color("#2F4F3E"), weave_scale=300))
M.box_uv(book, 4.0)
for o in (mug, glass, plate, book):
    o["bk_subject"] = True

# ---------------------------------------------------------------- camera
cam = C.add("CAM_Table", lens=50)
C.frame(cam, [mug, glass, plate, book], azimuth=10, elevation=22, margin=1.25)
C.dof(cam, focus=(-0.25, 0.55, TOP_Z + 0.05), fstop=2.8)

# ---------------------------------------------------------------- light: sun through the window
# sun comes from the -X side (window), low morning elevation, slightly from the front
L.world_sky(sun_elevation=24.0, sun_azimuth=-70.0, strength=0.6, sun_strength=6.0, sun_lamp=True)
bpy.data.objects["LGT_Sun"].data.angle = math.radians(1.5)   # crisp but not razor shadows
R.configure(engine="CYCLES", quality="final", resolution=(1280, 854), device="CPU", view="AgX",
            look="None", samples=256)
bpy.context.scene.cycles.max_bounces = 8
bpy.context.scene.cycles.caustics_refractive = False

# meter with a TEMPORARY grey card at the subject, facing the camera, then remove it
card = M.box("CTL_TmpGreyCard", (0.08, 0.005, 0.08), location=(-0.25, 0.45, TOP_Z + 0.05), coll="Props")
C.look_at(card, cam.location)
card.rotation_euler.x += math.radians(90)
MT.assign(card, MT.principled("MAT_TmpGrey18", (0.18, 0.18, 0.18), roughness=0.95, specular=0.0))
meter = R.auto_exposure(card, res=200, samples=12)
bpy.data.objects.remove(card, do_unlink=True)
S.purge_orphans()
# the card sat in the sun patch: mid-grey there crushes the shade. Open up +0.6 EV (intent: airy morning)
bpy.context.scene.view_settings.exposure += 0.6
emit(appended=[o.name for o in mug_parts], metering=meter)
