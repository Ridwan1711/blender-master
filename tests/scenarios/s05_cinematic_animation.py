"""S05 - Cinematic animation built on an EXISTING file (the S02 crate).

Exercises: opening/augmenting a .blend non-destructively (saved under a new name), orbit +
dolly camera move with eased timing, lights-up reveal (light energy keys), pulsing emissive
(node-socket keys), shallow DOF, motion blur, EEVEE Next setup, numeric motion check.
Run: python scripts/bk.py run tests/scenarios/s05_cinematic_animation.py --blend OUT/s02_crate.blend --save OUT/s05.blend
Then: python scripts/bk.py render OUT/s05.blend --out OUT/s05_frames/f_ --frames 1-72 --video OUT/s05.mp4
"""
import math

import bpy

from bkit import anim as A
from bkit import camera as C
from bkit import emit
from bkit import render as R
from bkit import scene as S

sc = bpy.context.scene
body = bpy.data.objects["GEO_CrateBody"]
S.set_frame_range(1, 72, fps=24)

# ---- new camera: orbit (pivot rotation, linear) + dolly in (eased) + slight rise
cam = C.add("CAM_Cine", lens=40, location=(0, 0, 0), target=None)
pivot = C.orbit(cam, center=(0, 0, 0.25), radius=2.2, height=0.55, frames=(1, 72),
                start_azimuth=-75.0, sweep=55.0)
A.keys(cam, "location", [(1, (0.0, -2.2, 0.55)), (72, (0.0, -1.8, 0.45))])  # push-in that keeps the handle in frame
A.ease(cam, "EASE_IN_OUT", path="location")
# pivot rotation should ease too for a smooth start/stop
A.ease(pivot, "EASE_IN_OUT")
cam.data.dof.use_dof = True
cam.data.dof.focus_object = body
cam.data.dof.aperture_fstop = 2.8
sc.camera = cam

# the S02 backdrop was sized for a static camera; rebuild it to cover the whole orbit
old = bpy.data.objects.get("GEO_Backdrop")
if old is not None:
    bpy.data.objects.remove(old, do_unlink=True)
    S.purge_orphans()  # its mesh would linger as an orphan datablock
from bkit import lighting as L  # noqa: E402
from bkit import materials as MT  # noqa: E402
L.studio_backdrop(cam, [body], color=MT.hex_color("#3A3D42"), roughness=0.5, frames=(1, 72))

# ---- lights-up reveal: key/rim ramp up over the first second
for name in ("LGT_Key", "LGT_Rim"):
    L = bpy.data.objects.get(name)
    if L:
        full = L.data.energy
        A.keys(L, "data.energy", [(1, full * 0.05), (24, full)], interpolation="BEZIER")

# ---- status strip pulse (emission strength), starts after the lights are up
glow = bpy.data.materials["MAT_StatusGlow"]
A.key_socket(glow, "Principled BSDF", "Emission Strength",
             [(1, 0.0), (20, 0.0), (26, 18.0), (34, 6.0), (42, 18.0), (50, 6.0), (58, 18.0), (72, 10.0)])

# ---- EEVEE Next for the animation (fast); motion blur on
R.configure(engine="EEVEE", quality="draft", resolution=(960, 540), view="Khronos PBR Neutral",
            motion_blur=True)
compat_ok = sc.render.engine
report = A.motion_report(cam, list(range(1, 73)))
emit(engine=compat_ok, frames=[sc.frame_start, sc.frame_end], camera_motion=report,
     focus=cam.data.dof.focus_object.name)
