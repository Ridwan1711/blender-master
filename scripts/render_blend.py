"""Render a .blend. Only settings you pass are changed; otherwise the file's own settings are used.
python bk.py render scene.blend --out out/shot.png [--quality preview|draft|final]
        [--engine cycles|eevee|workbench] [--res 1920x1080] [--percent 50] [--samples N]
        [--device CPU|GPU|AUTO] [--frame 24]
python bk.py render scene.blend --out out/frames/shot_ --frames 1-96 [--video out/shot.mp4]
Stills are followed by an exposure check (imgcheck) unless --no-check.
"""
import argparse
import os
import sys
import time

import bpy
from bkit import compat, emit
from bkit import inspect as I
from bkit import render as R

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--quality", choices=list(R.TIERS))
ap.add_argument("--engine")
ap.add_argument("--res")
ap.add_argument("--percent", type=int)
ap.add_argument("--samples", type=int)
ap.add_argument("--device", default=None)
ap.add_argument("--frame", type=int)
ap.add_argument("--frames")
ap.add_argument("--video", help="also/instead encode the frame range to this MP4")
ap.add_argument("--no-check", action="store_true")
a = ap.parse_args(sys.argv[1:])

sc = bpy.context.scene
r = sc.render
if a.engine:
    compat.set_engine(sc, a.engine)
if a.quality:
    t = R.TIERS[a.quality]
    if r.engine == "CYCLES":
        R.setup_cycles(sc, samples=a.samples or t["cycles"], device=a.device or "AUTO",
                       threshold=t["threshold"], bounces=t["bounces"])
    elif r.engine.startswith("BLENDER_EEVEE"):
        R.setup_eevee(sc, samples=a.samples or t["eevee"], raytracing=t["raytrace"])
elif a.samples:
    if r.engine == "CYCLES":
        sc.cycles.samples = a.samples
    elif r.engine.startswith("BLENDER_EEVEE"):
        sc.eevee.taa_render_samples = a.samples
if a.device and r.engine == "CYCLES" and not a.quality:
    R.setup_device(sc, a.device)
if a.res:
    w, h = (int(x) for x in a.res.lower().split("x"))
    r.resolution_x, r.resolution_y = w, h
if a.percent:
    r.resolution_percentage = a.percent

out = os.path.abspath(a.out)
info = {"engine": r.engine, "resolution": [r.resolution_x * r.resolution_percentage // 100,
                                           r.resolution_y * r.resolution_percentage // 100]}
if r.engine == "CYCLES":
    info["samples"] = sc.cycles.samples
    info["device"] = sc.cycles.device
if a.frames or a.video:
    if a.frames:
        f0, f1 = (int(x) for x in a.frames.split("-"))
        sc.frame_start, sc.frame_end = f0, f1
    if a.video and not a.frames:
        R.output_video(sc, os.path.abspath(a.video))
        info["seconds"] = R.animation(sc)
        info["video"] = os.path.abspath(a.video)
    else:
        R.output_png(sc, out)
        info["seconds"] = R.animation(sc, out)
        info["frames"] = [sc.frame_start, sc.frame_end]
        info["frame_dir"] = os.path.dirname(out)
        if a.video:  # encode the PNG sequence with Blender's sequencer
            from bkit import video
            info["video"] = video.encode_sequence(os.path.dirname(out), os.path.basename(out),
                                                  os.path.abspath(a.video), fps=r.fps)
    info["seconds_per_frame"] = round(info["seconds"] / max(1, sc.frame_end - sc.frame_start + 1), 2)
else:
    if a.frame is not None:
        sc.frame_set(a.frame)
    if not out.lower().endswith((".png", ".jpg", ".exr", ".tif", ".webp")):
        out += ".png"
    if out.lower().endswith(".png"):
        R.output_png(sc, out, rgba=r.film_transparent)
    else:
        r.filepath = out
    info["seconds"] = R.still(sc, out)
    info["image"] = out
    if not a.no_check:
        info["check"] = I.image_stats(out)
emit(**info)
