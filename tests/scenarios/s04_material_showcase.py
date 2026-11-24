"""S04 - Material-rich scene: 12 labelled material balls + grey/white calibration cards.

Exercises: every materials.py preset, text objects, gradient world for reflections, soft
studio rig, and a measurable exposure check: the 18% grey card's rendered value is read
back from the image (tests/run_tests.py does this via bkit.inspect.sample_image).
Run: python scripts/bk.py run tests/scenarios/s04_material_showcase.py --save OUT/s04.blend
"""
import math

import bpy

from bkit import camera as C
from bkit import emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import scene as S

S.new_scene()

presets = [
    ("Gold", MT.metal("MAT_Gold", "gold", roughness=0.18)),
    ("Brushed Alu", MT.brushed_metal("MAT_BrushedAlu", "aluminium", roughness=0.3)),
    ("Copper", MT.metal("MAT_Copper", "copper", roughness=0.35)),
    ("Car Paint", MT.car_paint("MAT_CarPaint", MT.hex_color("#8E0F14"))),
    ("Glass", MT.glass("MAT_Glass")),
    ("Ceramic", MT.ceramic("MAT_Ceramic", MT.hex_color("#E8E2D6"))),
    ("Marble", MT.marble("MAT_Marble")),
    ("Wood", MT.wood("MAT_Wood")),
    ("Fabric", MT.fabric("MAT_Fabric", MT.hex_color("#2B4C7E"))),
    ("Rubber", MT.rubber("MAT_Rubber")),
    ("Concrete", MT.concrete("MAT_Concrete")),
    ("Emission", MT.emissive("MAT_Emission", MT.hex_color("#FF8A3D"), strength=6.0)),
]
label_mat = MT.principled("MAT_Label", (0.85, 0.85, 0.85), roughness=0.5)
ped_mat = MT.principled("MAT_Pedestal", MT.hex_color("#2A2A2D"), roughness=0.4)

COLS, SP, SP_ROW, R_BALL = 4, 0.36, 0.62, 0.11   # rows deep enough for labels to show
balls = []
for i, (label, mat) in enumerate(presets):
    r, c = divmod(i, COLS)
    x = (c - (COLS - 1) / 2) * SP
    y = r * SP_ROW
    ped = M.cylinder("GEO_Pedestal_%02d" % i, radius=0.075, depth=0.04, segments=48, origin="BOTTOM",
                     location=(x, y, 0.0), coll="Showcase")
    M.bevel(ped, width=0.004, segments=2)
    MT.assign(ped, ped_mat)
    ball = M.sphere("GEO_Ball_%s" % label.replace(" ", ""), radius=R_BALL, location=(x, y, 0.04 + R_BALL),
                    coll="Showcase", segments=64, rings=32)
    M.box_uv(ball, scale=4.0)          # fabric weave uses UVs
    MT.assign(ball, mat)
    ball["bk_subject"] = True
    balls.append(ball)
    # label: upright text in front of the pedestal
    cu = bpy.data.curves.new("TXT_" + label, "FONT")
    cu.body = label
    cu.size = 0.032
    cu.align_x = "CENTER"
    cu.extrude = 0.002
    txt = S.add_object("GEO_Label_%02d" % i, cu, "Showcase", location=(x, y - 0.11, 0.004),
                       rotation=(math.radians(90), 0, 0))
    txt.data.materials.append(label_mat)

# calibration cards (left): 18% grey and 90% white, linear albedo, near-zero specular
grey =M.box("GEO_CalibGrey", (0.12, 0.01, 0.12), location=(-0.70, -0.05, 0.06), coll="Calibration")
MT.assign(grey, MT.principled("MAT_Grey18", (0.18, 0.18, 0.18), roughness=0.9, specular=0.0))
white = M.box("GEO_CalibWhite", (0.12, 0.01, 0.12), location=(-0.70, 0.12, 0.06), coll="Calibration")
MT.assign(white, MT.principled("MAT_White90", (0.9, 0.9, 0.9), roughness=0.9, specular=0.0))
grey["bk_subject"] = white["bk_subject"] = True

cam = C.add("CAM_Showcase", lens=50)
C.frame(cam, balls + [grey, white], azimuth=0, elevation=34, margin=1.08)
C.dof(cam, focus=balls[5], fstop=8.0)
L.studio_backdrop(cam, balls + [grey, white], color=MT.hex_color("#7C7C80"), roughness=0.7)
L.three_point(balls, style="soft", intensity=1.0)
L.world_gradient(top=(0.5, 0.55, 0.62), bottom=(0.06, 0.06, 0.07), strength=0.6)
R.configure(engine="CYCLES", quality="draft", resolution=(1440, 900), device="CPU", view="AgX")
emit(materials=len(presets), calibration={"grey": grey.name, "white": white.name})

# meter the grey card like a photographer: exposure so the 18% card hits calibrated mid-grey
emit(metering=R.auto_exposure(grey))
