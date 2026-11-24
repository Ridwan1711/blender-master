"""Inspection renders. Usage:
python bk.py preview scene.blend --out DIR [--views camera,persp,front,right,top]
        [--mode material|clay|random|wire] [--res 480] [--objects A,B] [--beauty] [--beauty-res 960]
        [--samples 24] [--margin 1.12]
Writes view_<name>.png, sheet_<mode>.png (and beauty.png). Never saves the .blend.
"""
import argparse
import sys

import bpy
from bkit import emit
from bkit import preview as P

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--views", default="camera,persp,front,right,top")
ap.add_argument("--mode", default="material", choices=["material", "clay", "random", "wire"])
ap.add_argument("--res", type=int, default=480)
ap.add_argument("--objects")
ap.add_argument("--margin", type=float, default=1.12)
ap.add_argument("--beauty", action="store_true", help="also render scene camera with scene engine")
ap.add_argument("--beauty-only", action="store_true")
ap.add_argument("--beauty-res", type=int, default=960)
ap.add_argument("--samples", type=int, default=24)
a = ap.parse_args(sys.argv[1:])

objs = [bpy.data.objects[n] for n in a.objects.split(",")] if a.objects else None
if a.beauty_only:
    import os
    os.makedirs(a.out, exist_ok=True)
    res = {"beauty": P.beauty_shot(os.path.join(a.out, "beauty.png"), res=a.beauty_res, samples=a.samples)}
else:
    res = P.views(a.out, objs=objs, views=a.views.split(","), res=a.res, mode=a.mode,
                  margin=a.margin, beauty=a.beauty, beauty_res=a.beauty_res, beauty_samples=a.samples)
emit(**res)
