"""T1 - Voxel character from pixel-art front + side sprites. Mode 1 (procedural voxels).

Selector: style=voxel (pixel grid detected) -> Mode 1 (score 9); Mode 3 rejected (AI smooths voxels).
Build: native-grid visual hull of the sprites, palette texture, inferred faces flagged; planar
decimation merges same-colour coplanar faces for the game asset.
"""
import os

from bkit import emit
from bkit import gameprep as GP
from bkit import recon as RC
from bkit import scene as S
import common

a = common.args()
t = common.Timer()
S.new_scene()
views = {"front": os.path.join(a.refs, "voxel_knight", "front.png"),
         "side": os.path.join(a.refs, "voxel_knight", "side.png")}
ob, info = RC.voxel_from_views(views, height_m=1.8, name="GEO_VoxelKnight")
t.lap("build_s")
before = GP.decimate(ob, planar_deg=0.5)          # merge coplanar faces of the same palette colour
t.lap("optimise_s")
res = common.finish(ob, views, a.out, "voxel_knight", t, height_m=1.8, preview_mode="texture")
emit(case="voxel_knight", mode="1 procedural voxel", build=info, after_planar=before, **res)
