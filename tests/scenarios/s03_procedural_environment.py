"""S03 - Procedural environment: GN terrain + lake + scattered forest/rocks/grass, golden hour.

Exercises: Geometry Nodes builder (terrain + scatter recipes, exposed modifier inputs),
procedural asset library, instancing at scale, raycast placement, physical sky + sun,
mist-pass aerial perspective, slope/height-blended terrain shader.
All randomness is seeded: re-running reproduces the same world. Change SEED for a new one.
Run: python scripts/bk.py run tests/scenarios/s03_procedural_environment.py --save OUT/s03.blend -- --seed 3
"""
import argparse
import sys

import bpy
from mathutils import Vector

from bkit import assets as A
from bkit import camera as C
from bkit import emit
from bkit import geonodes as G
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import scene as S

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=3)
ap.add_argument("--size", type=float, default=90.0)
a = ap.parse_args(sys.argv[1:])
SEED = a.seed

S.new_scene()

# ---- asset library (hidden originals; scatter uses them as instance sources)
trees, broad, rocks, grass, bushes = (A.subcollection(n) for n in ("Pines", "Broadleaf", "Rocks", "Grass", "Bushes"))
for s in range(3):
    A.pine(seed=SEED * 10 + s, height=7.0, coll=trees)
for s in range(2):
    A.broadleaf(seed=SEED * 10 + s, height=5.5, coll=broad)
for s in range(4):
    A.rock(seed=SEED * 10 + s, size=1.2, coll=rocks)
for s in range(3):
    A.grass_tuft(seed=SEED * 10 + s, coll=grass)
for s in range(2):
    A.bush(seed=SEED * 10 + s, size=1.0, coll=bushes)

# ---- terrain
terrain_mat = MT.terrain("MAT_Terrain", grass=MT.hex_color("#3D5A1E"), dirt=MT.hex_color("#5A4630"),
                         rock=MT.hex_color("#6B665E"), snow=MT.hex_color("#ECEFF2"), snow_height=13.0,
                         slope_start=0.82, slope_end=0.68)
terr = G.terrain("GEO_Terrain", size=a.size, resolution=280, height=5.0, scale=0.035, seed=SEED,
                 lake_center=(0.0, -6.0), lake_radius=13.0, lake_depth=3.2, mountain_height=18.0,
                 material=terrain_mat)
S.refresh()


def ground_z(x, y):
    """Raycast the evaluated terrain from above."""
    dg = bpy.context.evaluated_depsgraph_get()
    ok, loc, nrm, idx = terr.evaluated_get(dg).ray_cast(Vector((x, y, 200.0)), Vector((0, 0, -1)))
    return loc.z if ok else 0.0


lake_floor = ground_z(0.0, -6.0)
water_level = lake_floor + 1.6
lake = M.plane("GEO_Lake", size=(36, 32), location=(0.0, -6.0, water_level), coll="Environment")
MT.assign(lake, MT.water("MAT_Water", color=MT.hex_color("#7FA7A8"), wave_scale=3.0))

# ---- camera position from the ACTUAL shoreline: walk outward from the lake centre until
#      the ground rises above the water, then step back 3 m onto dry land.
centre = Vector((0.0, -6.0, 0.0))
out_dir = Vector((-0.35, -1.0, 0.0)).normalized()
shore = centre
for step in range(1, 80):
    p = centre + out_dir * (step * 0.5)
    if ground_z(p.x, p.y) > water_level + 0.25:
        shore = p
        break
cx, cy = (shore + out_dir * 3.0).xy
clear = S.empty("CTL_ClearZone", "Environment", location=(cx, cy, 0.0), display="CIRCLE", size=8.0)

# ---- scatter layers (each is its own object with exposed GN inputs)
sc_pines = G.scatter("FX_Pines", terr, trees, density=0.035, seed=SEED, scale=(0.7, 1.35), max_slope_deg=32,
                     min_height=water_level + 0.8, max_height=11.0, clump_scale=0.06, clump_threshold=0.42,
                     avoid=clear, avoid_radius=8.0)
sc_broad = G.scatter("FX_Broadleaf", terr, broad, density=0.01, seed=SEED + 1, scale=(0.8, 1.2),
                     max_slope_deg=20, min_height=water_level + 0.5, max_height=4.0, avoid=clear, avoid_radius=8.0)
sc_rocks = G.scatter("FX_Rocks", terr, rocks, density=0.02, seed=SEED + 2, scale=(0.3, 1.8), max_slope_deg=65,
                     min_height=water_level - 0.6, align=0.7, avoid=clear, avoid_radius=4.0)
sc_bush = G.scatter("FX_Bushes", terr, bushes, density=0.03, seed=SEED + 3, scale=(0.5, 1.1), max_slope_deg=28,
                    min_height=water_level + 0.3, max_height=8.0, clump_scale=0.09, clump_threshold=0.5,
                    avoid=clear, avoid_radius=6.0)
sc_grass = G.scatter("FX_Grass", terr, grass, density=2.2, seed=SEED + 4, scale=(0.6, 1.3), max_slope_deg=24,
                     min_height=water_level + 0.15, max_height=7.0, align=0.5, clump_scale=0.12, clump_threshold=0.35)

# ---- camera on the near shore, eye height, looking across the lake to the mountains
look = centre - out_dir * 45.0  # across the lake toward the mountains
cam = C.add("CAM_Vista", lens=28, location=(cx, cy, ground_z(cx, cy) + 1.8),
            target=(look.x, look.y, water_level + 6.0))  # horizon ~ upper third
cam.data.clip_end = 1000

# ---- light: golden-hour sun from camera-left, physical sky, aerial perspective
L.world_sky(sun_elevation=14.0, sun_azimuth=-115.0, strength=0.3, sun_strength=4.5)
R.configure(engine="CYCLES", quality="draft", resolution=(1280, 720), device="CPU", look="Medium High Contrast")
R.mist(start=25.0, depth=140.0, color=(0.55, 0.6, 0.68), strength=0.35)

from bkit import inspect as I  # noqa: E402
emit(seed=SEED, water_level=round(water_level, 2), tris=I.evaluated_tris()["total"],
     instances=I.evaluated_tris()["instances"])
