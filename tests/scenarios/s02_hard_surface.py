"""S02 - Complex hard-surface asset: sci-fi cargo crate.

Exercises: live boolean stack (EXACT) with arrayed cutters, bevel after boolean + weighted
normals, extruded profiles, curve handles, instanced bolts (linked copies), assembly
parenting, edge-wear shader, emissive detail, camera-aware studio.
Run: python scripts/bk.py run tests/scenarios/s02_hard_surface.py --save OUT/s02.blend
"""
import math

from bkit import camera as C
from bkit import emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import scene as S

S.new_scene()
W, D, H = 0.80, 0.50, 0.50          # crate size (m)
RIM = 0.035                          # corner guard thickness

paint = MT.painted_metal("MAT_PaintOrange", MT.hex_color("#D9822B"), wear=0.55)
gun = MT.metal("MAT_Gunmetal", "iron", roughness=0.42)
steel = MT.metal("MAT_Steel", "steel", roughness=0.3)
rubber = MT.rubber("MAT_Rubber", MT.hex_color("#1A1A1A"))
glow = MT.emissive("MAT_StatusGlow", MT.hex_color("#3FE0FF"), strength=12)

# ---------------------------------------------------------------- body + cutters
body = M.box("GEO_CrateBody", (W, D, H), origin="BOTTOM", coll="Crate")
MT.assign(body, paint)


def panel_cutter(name, w, h, depth, loc, rot):
    c = M.extrude_polygon(name, M.rounded_rect(w, h, 0.025, seg=5), depth, center_z=True)
    c.location, c.rotation_euler = loc, rot
    return c


inset = 0.008
cuts = [
    panel_cutter("CUT_PanelFront", 0.56, 0.30, 2 * inset, (0, -D / 2, H / 2), (math.radians(90), 0, 0)),
    panel_cutter("CUT_PanelBack", 0.56, 0.30, 2 * inset, (0, D / 2, H / 2), (math.radians(90), 0, 0)),
    panel_cutter("CUT_PanelLeft", 0.30, 0.30, 2 * inset, (-W / 2, 0, H / 2), (0, math.radians(90), 0)),
    panel_cutter("CUT_PanelRight", 0.30, 0.30, 2 * inset, (W / 2, 0, H / 2), (0, math.radians(90), 0)),
]
vent = panel_cutter("CUT_Vent", 0.30, 0.018, 0.03, (0, -0.12, H), (0, 0, 0))
M.array(vent, count=6, offset=(0, 0.048, 0), relative=False)   # 6 slots across the lid
cuts.append(vent)
for c in cuts:
    M.boolean(body, c, "DIFFERENCE", solver="EXACT")
# smallest feature = 8 mm recess wall -> bevel must stay below ~3 mm (measured: 4 mm collapses)
M.hard_surface_finish(body, bevel_width=0.003, segments=3, angle=35)

# ---------------------------------------------------------------- corner guards (L profile)
L_prof = [(0, 0), (RIM + 0.05, 0), (RIM + 0.05, RIM), (RIM, RIM), (RIM, RIM + 0.05), (0, RIM + 0.05)]
for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
    g = M.extrude_polygon("GEO_CornerGuard_%d" % i, L_prof, H + 0.006, coll="Crate")
    # rotate the L so its outside corner sits on the crate corner; base on the floor (z=0)
    g.rotation_euler.z = math.atan2(sy, sx) - math.radians(225)
    g.location = (sx * (W / 2 + 0.006), sy * (D / 2 + 0.006), 0.0)
    M.bevel(g, width=0.004, segments=2, angle=35)
    M.weighted_normals(g)
    MT.assign(g, gun)
    S.parent(g, body)

# ---------------------------------------------------------------- handles on both short sides
for side in (-1, 1):
    x = side * (W / 2 - inset)
    pts = [(x, -0.11, 0.34), (x + side * 0.045, -0.10, 0.34), (x + side * 0.055, 0.0, 0.34),
           (x + side * 0.045, 0.10, 0.34), (x, 0.11, 0.34)]
    hnd = M.curve_tube("GEO_Handle_%s" % ("L" if side < 0 else "R"), pts, radius=0.011, coll="Crate",
                       to_mesh=True)
    MT.assign(hnd, rubber)
    S.parent(hnd, body)
    for j, y in enumerate((-0.11, 0.11)):
        mount = M.box("GEO_HandleMount_%s%d" % ("L" if side < 0 else "R", j), (0.024, 0.04, 0.05),
                      location=(x, y, 0.34), coll="Crate")
        M.bevel(mount, width=0.004, segments=2)
        MT.assign(mount, gun)
        S.parent(mount, body)

# ---------------------------------------------------------------- bolts: one mesh, linked copies
bolt = M.cylinder("GEO_Bolt_000", radius=0.009, depth=0.008, segments=16, coll="Crate",
                  rotation=(math.radians(90), 0, 0))
M.bevel(bolt, width=0.002, segments=2, angle=30)
MT.assign(bolt, steel)
n = 0
for face_y in (-1, 1):
    for bx in (-0.25, 0.25):
        for bz in (0.12, 0.38):
            o = bolt if n == 0 else M.linked_copy(bolt, "GEO_Bolt_%03d" % n)
            o.location = (bx, face_y * (D / 2 - inset + 0.001), bz)
            S.parent(o, body)
            n += 1

# ---------------------------------------------------------------- emissive status strip
strip = M.box("GEO_StatusStrip", (0.22, 0.01, 0.014), location=(0, -D / 2 + 0.002, 0.055), coll="Crate")
M.bevel(strip, width=0.002, segments=2)
MT.assign(strip, glow)
S.parent(strip, body)
body["bk_subject"] = True

# ---------------------------------------------------------------- shot
cam = C.add("CAM_Hero", lens=50)
C.frame(cam, [body], azimuth=-35, elevation=22, margin=1.25)
L.studio_backdrop(cam, [body], color=MT.hex_color("#3A3D42"), roughness=0.5)
L.three_point([body], style="dramatic", intensity=1.2)
L.world_color((0.02, 0.022, 0.025), 1.0)
R.configure(engine="CYCLES", quality="draft", resolution=(1280, 960), device="CPU",
            view="Khronos PBR Neutral")  # product colour fidelity (see rendering.md)
emit(body=M.stats(body), bolts=n, cutters=len(cuts))
