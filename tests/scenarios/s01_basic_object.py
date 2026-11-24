"""S01 - Basic object: a glazed ceramic coffee mug, studio product shot.

Exercises: lathe modelling, partial torus, per-face materials, assembly parenting,
studio backdrop, camera auto-framing, three-point rig, Cycles draft render.
Run: python scripts/bk.py run tests/scenarios/s01_basic_object.py --save OUT/s01.blend
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

# ---- body: profile walks outside bottom->rim, then inside rim->bottom (gives wall thickness)
profile = [
    (0.0, 0.0), (0.034, 0.0), (0.0385, 0.0012), (0.0405, 0.004),   # foot with soft bevel
    (0.0415, 0.02), (0.0425, 0.06), (0.0432, 0.092),                 # slightly flared outer wall
    (0.0431, 0.0945), (0.0420, 0.0957), (0.0408, 0.0950),             # rounded lip
    (0.0402, 0.092), (0.0395, 0.06), (0.0386, 0.016),                 # inner wall
    (0.0360, 0.0095), (0.030, 0.0085), (0.0, 0.0085),                 # inner floor
]
mug = M.lathe("GEO_Mug", profile, segments=96, coll="Props")
M.subsurf(mug, levels=1, render_levels=2)

glaze = MT.ceramic("MAT_GlazeBlue", MT.hex_color("#1F4E79"), roughness=0.18, coat=0.8)
inner = MT.ceramic("MAT_GlazeCream", MT.hex_color("#EFE6D2"), roughness=0.12, coat=0.6)
MT.assign(mug, glaze)
inside = [p.index for p in mug.data.polygons
          if p.normal.z > -0.5 and math.hypot(p.center.x, p.center.y) < 0.0409 and
          (p.center.x * p.normal.x + p.center.y * p.normal.y) < 0 or
          (p.center.z > 0.0080 and p.center.z < 0.0100 and p.normal.z > 0.9)]
MT.assign(mug, inner, faces=inside)

# ---- handle: open torus arc in the XZ plane, ends sunk into the wall, parented (one assembly)
handle = M.torus("GEO_MugHandle", major=0.024, minor=0.0055, major_segments=40, minor_segments=14,
                 arc=230, start_deg=-115, coll="Props")
handle.rotation_euler = (math.radians(90), 0, 0)
handle.scale = (1.0, 1.25, 1.0)
M.apply_transform(handle)
handle.location = (0.050, 0.0, 0.050)
MT.assign(handle, glaze)
S.parent(handle, mug)

# ---- coffee surface
coffee = M.cylinder("GEO_Coffee", radius=0.0393, depth=0.002, segments=96, location=(0, 0, 0.074),
                    coll="Props")
MT.assign(coffee, MT.principled("MAT_Coffee", MT.hex_color("#2B1608"), roughness=0.05, specular=0.6))
S.parent(coffee, mug)
mug["bk_subject"] = True
handle["bk_subject"] = True

# ---- studio: camera first, then backdrop + lights derived from it
cam = C.add("CAM_Product", lens=85)
C.frame(cam, [mug, handle], azimuth=-28, elevation=16, margin=1.35)
C.dof(cam, focus=(0.0, 0.0, 0.05), fstop=5.6)
bd = L.studio_backdrop(cam, [mug, handle], color=MT.hex_color("#B8B2A7"))
rig = L.three_point([mug, handle], style="product")
L.world_color((0.18, 0.18, 0.2), strength=0.3)

R.configure(engine="CYCLES", quality="draft", resolution=(1280, 960), device="CPU")
emit(tris=M.stats(mug)["tris"] + M.stats(handle)["tris"], inside_faces=len(inside),
     camera_lens=cam.data.lens)
