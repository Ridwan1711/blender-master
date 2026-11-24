"""Encode PNG sequences to MP4 with Blender's sequencer (no external ffmpeg needed).

Render frames as PNG first (crash-safe, resumable), then encode:
    from bkit import video
    video.encode_sequence("C:/out/frames", "shot_", "C:/out/shot.mp4", fps=24)
"""
import os

import bpy

from . import compat
from . import render as _render


def encode_sequence(frame_dir, prefix, out_mp4, fps=24, quality="HIGH"):
    files = sorted(f for f in os.listdir(frame_dir)
                   if f.startswith(prefix) and f.lower().endswith(".png"))
    if not files:
        raise FileNotFoundError("no %s*.png frames in %s" % (prefix, frame_dir))
    probe = bpy.data.images.load(os.path.join(frame_dir, files[0]), check_existing=False)
    w, h = probe.size
    bpy.data.images.remove(probe)
    prev = bpy.context.window.scene if bpy.context.window else None
    sc = bpy.data.scenes.new("bk_encode")
    try:
        se = sc.sequence_editor_create()
        strips = se.strips if compat.has_prop(se, "strips") else se.sequences  # 4.4 rename
        st = strips.new_image(name="frames", filepath=os.path.join(frame_dir, files[0]),
                              channel=1, frame_start=1)
        for f in files[1:]:
            st.elements.append(f)
        sc.frame_start, sc.frame_end = 1, len(files)
        sc.render.resolution_x, sc.render.resolution_y = w - (w % 2), h - (h % 2)
        sc.render.resolution_percentage = 100
        sc.render.use_sequencer = True
        # Frames are already display-referred: do NOT tone-map them a second time.
        compat.set_enum(sc.view_settings, "view_transform", ["Standard"])
        compat.try_set(sc.sequencer_colorspace_settings, "name", "sRGB")
        _render.output_video(sc, out_mp4, quality=quality, fps=fps)
        bpy.ops.render.render(animation=True, scene=sc.name)
    finally:
        bpy.data.scenes.remove(sc)
        if prev is not None and bpy.context.window:
            bpy.context.window.scene = prev
    if not os.path.isfile(out_mp4):
        raise RuntimeError("encoding produced no file: %s" % out_mp4)
    return out_mp4
