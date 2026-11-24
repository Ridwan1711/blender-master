"""Visual inspection renders: labelled multi-view contact sheets and quick beauty shots.

Look at the sheet with the Read tool after every significant change. The scene is
restored afterwards (temporary cameras, modifiers and settings are removed), so this
is safe to call inside a build script before saving.

    from bkit import preview as P
    P.views("C:/proj/_preview", mode="material")          # camera, persp, front, right, top
    P.views(out, objs=[hero], views=("persp", "front"), mode="wire")
    P.beauty("C:/proj/_preview/beauty.png", res=960)      # scene engine, low samples
    P.contact_sheet([a_png, b_png], "C:/proj/compare.png") # side-by-side comparison
"""
import math
import os

import bpy

from . import camera as _cam
from . import compat
from . import inspect as _inspect

VIEW_DEFS = {  # name: (azimuth, elevation, ortho)
    "persp": (35.0, 22.0, False), "persp2": (-145.0, 25.0, False), "low": (25.0, 4.0, False),
    "front": (0.0, 0.0, True), "back": (180.0, 0.0, True), "right": (90.0, 0.0, True),
    "left": (-90.0, 0.0, True), "top": (0.0, 90.0, True),
}


class _Snapshot:
    """Set attributes now, restore the original values later (in reverse order)."""

    def __init__(self):
        self.items = []

    def set(self, owner, attr, value):
        if owner is None or not compat.has_prop(owner, attr):
            return False
        self.items.append((owner, attr, getattr(owner, attr)))
        try:
            setattr(owner, attr, value)
            return True
        except (TypeError, ValueError):
            return False

    def restore(self):
        for owner, attr, val in reversed(self.items):
            try:
                setattr(owner, attr, val)
            except Exception:  # noqa: BLE001
                pass
        self.items.clear()


def contact_sheet(paths, out, cols=None, pad=6, bg=(0.12, 0.12, 0.12)):
    """Tile PNGs into one image (row-major, top-left first). Sizes may differ."""
    import numpy as np
    out = os.path.abspath(out)
    arrs = []
    for p in paths:
        img = bpy.data.images.load(p, check_existing=False)
        w, h = img.size
        a = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        arrs.append(a.reshape(h, w, 4))
        bpy.data.images.remove(img)
    # normalise heights to the median (nearest-neighbour) so one big image can't dwarf the rest
    th = sorted(a.shape[0] for a in arrs)[len(arrs) // 2]
    for i, a in enumerate(arrs):
        if a.shape[0] != th:
            f = th / a.shape[0]
            ys = np.minimum((np.arange(th) / f).astype(int), a.shape[0] - 1)
            nw = max(1, int(round(a.shape[1] * f)))
            xs = np.minimum((np.arange(nw) / f).astype(int), a.shape[1] - 1)
            arrs[i] = a[ys][:, xs]
    n = len(arrs)
    cols = cols or (1 if n == 1 else 2 if n in (2, 4) else 3)
    rows = math.ceil(n / cols)
    hm = max(a.shape[0] for a in arrs)
    wm = max(a.shape[1] for a in arrs)
    H, W = rows * hm + pad * (rows + 1), cols * wm + pad * (cols + 1)
    sheet = np.empty((H, W, 4), dtype=np.float32)
    sheet[...] = (*bg, 1.0)
    for i, a in enumerate(arrs):
        r, c = divmod(i, cols)
        h, w = a.shape[:2]
        y0 = H - pad - (r + 1) * hm - r * pad + (hm - h)  # Blender pixel rows are bottom-up
        x0 = pad + c * (wm + pad)
        sheet[y0:y0 + h, x0:x0 + w] = a
        sheet[y0:y0 + h, x0:x0 + w, 3] = 1.0
    img = bpy.data.images.new("bk_contact_sheet", W, H, alpha=False)
    img.pixels.foreach_set(sheet.ravel())
    img.filepath_raw = out
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return out


def _stamp(snap, r, res):
    snap.set(r, "use_stamp", True)
    for p in r.bl_rna.properties:
        if p.identifier.startswith("use_stamp_") and p.identifier != "use_stamp_note":
            snap.set(r, p.identifier, False)
    snap.set(r, "use_stamp_note", True)
    snap.set(r, "stamp_font_size", max(12, res // 30))


def views(out_dir, objs=None, views=("camera", "persp", "front", "right", "top"), res=480,
          mode="material", margin=1.12, sheet=True, label=True, beauty=False, beauty_res=960,
          beauty_samples=24, isolate=True):
    """Render labelled Workbench inspection views of objs (default: subjects + their children).
    isolate=True hides non-subject geometry in all views except 'camera'.

    mode: material (material viewport colours) | clay | random (per-object colours: shows
          separate parts and overlaps) | wire (clay/material + wireframe overlay)
    Returns {"views": {name: path}, "sheet": path, "beauty": path?}.
    """
    sc = bpy.context.scene
    r = sc.render
    out_dir = os.path.abspath(out_dir)  # Blender resolves bare relative paths against the drive root
    os.makedirs(out_dir, exist_ok=True)
    objs = list(objs) if objs else (_inspect.subjects(sc) or _inspect.renderable(sc))
    snap = _Snapshot()
    temp_objs, temp_mods, temp_mats, grown = [], [], [], []
    results, names = {}, list(views)
    try:
        snap.set(r, "engine", r.engine)
        compat.set_engine(sc, "WORKBENCH")
        for attr, val in (("resolution_x", res), ("resolution_y", int(res * 0.75)),
                          ("resolution_percentage", 100), ("film_transparent", False),
                          ("use_compositing", False),  # mist/glare comps would wash out previews
                          ("filepath", r.filepath)):
            snap.set(r, attr, val)
        snap.set(r.image_settings, "file_format", "PNG")
        snap.set(r.image_settings, "color_mode", "RGB")
        if label:
            _stamp(snap, r, res)
        snap.set(sc, "camera", sc.camera)
        sh = sc.display.shading
        for attr, val in (("light", "STUDIO"),
                          ("color_type", {"material": "MATERIAL", "clay": "SINGLE", "random": "RANDOM",
                                          "wire": "MATERIAL"}[mode]),
                          ("single_color", (0.75, 0.75, 0.75)), ("show_cavity", True),
                          ("cavity_type", "BOTH"), ("show_object_outline", True),
                          ("show_specular_highlight", True), ("show_shadows", False)):
            snap.set(sh, attr, val)
        snap.set(sc.view_settings, "view_transform", "Standard")
        snap.set(sc.view_settings, "look", "None")
        snap.set(sc.view_settings, "exposure", 0.0)
        if sc.world:
            snap.set(sc.world, "color", (0.06, 0.06, 0.065))

        if mode == "wire":
            wire_mat = bpy.data.materials.new("bk_tmp_wire")
            wire_mat.diffuse_color = (0.02, 0.02, 0.02, 1.0)
            clay = bpy.data.materials.new("bk_tmp_clay")
            clay.diffuse_color = (0.8, 0.8, 0.8, 1.0)
            temp_mats += [wire_mat, clay]
            seen = set()
            for ob in objs:
                if ob.type != "MESH":
                    continue
                me = ob.data
                if me.as_pointer() not in seen:
                    seen.add(me.as_pointer())
                    if not me.materials:
                        me.materials.append(clay)
                        grown.append(me)
                    me.materials.append(wire_mat)
                    grown.append(me)
                m = ob.modifiers.new("bk_tmp_wire", "WIREFRAME")
                m.thickness = max(ob.dimensions.length, 1e-3) * 0.0025
                m.use_replace = False
                m.use_even_offset = True
                m.material_offset = len(me.materials) - 1
                temp_mods.append((ob, m))

        orig_cam = sc.camera
        subj = {o.name for o in objs}
        others = [o for o in sc.objects if o.type in _inspect.GEOMETRY_TYPES and o.name not in subj
                  and not o.hide_render]
        for o in others:
            snap.set(o, "hide_render", False)
        for name in names:
            for o in others:  # orthographic/inspection views show only the subjects
                o.hide_render = isolate and name != "camera"
            if name == "camera":
                if orig_cam is None:
                    continue
                cam = orig_cam
                text = "CAMERA %s  %s" % (cam.name, ("%.0fmm" % cam.data.lens)
                                          if cam.data.type == "PERSP" else "ortho")
            else:
                az, el, ortho = VIEW_DEFS[name]
                cam = _cam.add("bk_tmp_" + name, lens=50, coll=None, target=None, active=False,
                               ortho_scale=1.0 if ortho else None)
                temp_objs.append(cam)
                v = _cam.frame(cam, objs, margin=margin, azimuth=az, elevation=el)
                text = "%s  %s" % (name.upper(), ("ortho %.2f m wide" % v) if ortho else "50mm")
            sc.camera = cam
            r.stamp_note_text = text
            path = os.path.join(out_dir, "view_%s.png" % name)
            r.filepath = path
            bpy.ops.render.render(write_still=True)
            results[name] = path
    finally:
        for ob, m in temp_mods:
            ob.modifiers.remove(m)
        for me in reversed(grown):
            me.materials.pop(index=len(me.materials) - 1)
        snap.restore()
        for ob in temp_objs:
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.cameras.remove(data)
        for m in temp_mats:
            bpy.data.materials.remove(m)
    out = {"views": results}
    if sheet and results:
        out["sheet"] = contact_sheet([results[k] for k in names if k in results],
                                     os.path.join(out_dir, "sheet_%s.png" % mode))
    if beauty:
        out["beauty"] = beauty_shot(os.path.join(out_dir, "beauty.png"), res=beauty_res,
                                    samples=beauty_samples)
    return out


def frames(out_dir, frame_list, res=480, mode="material", camera=None, cols=None):
    """Animation check: render the scene camera at several frames (Workbench, labelled with the
    frame number) and tile them. Catches pops, intersections, broken deformation, bad timing."""
    sc = bpy.context.scene
    r = sc.render
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    cam = camera or sc.camera
    snap = _Snapshot()
    paths = []
    cur = sc.frame_current
    try:
        snap.set(r, "engine", r.engine)
        compat.set_engine(sc, "WORKBENCH")
        aspect = r.resolution_y / max(1, r.resolution_x)
        for attr, val in (("resolution_x", res), ("resolution_y", int(res * aspect)),
                          ("resolution_percentage", 100), ("use_compositing", False),
                          ("filepath", r.filepath)):
            snap.set(r, attr, val)
        snap.set(r.image_settings, "file_format", "PNG")
        _stamp(snap, r, res)
        snap.set(sc, "camera", cam)
        sh = sc.display.shading
        snap.set(sh, "color_type", {"material": "MATERIAL", "clay": "SINGLE", "random": "RANDOM"}.get(mode, "MATERIAL"))
        snap.set(sh, "show_cavity", True)
        snap.set(sc.view_settings, "view_transform", "Standard")
        for f in frame_list:
            sc.frame_set(f)
            r.stamp_note_text = "FRAME %d" % f
            p = os.path.join(out_dir, "frame_%04d.png" % f)
            r.filepath = p
            bpy.ops.render.render(write_still=True)
            paths.append(p)
    finally:
        snap.restore()
        sc.frame_set(cur)
    return {"frames": paths, "sheet": contact_sheet(paths, os.path.join(out_dir, "sheet_frames.png"),
                                                    cols=cols or min(4, len(paths)))}


def beauty_shot(path, res=960, samples=24, camera=None):
    """Scene camera, scene engine and materials, reduced samples/resolution. Restores settings."""
    sc = bpy.context.scene
    r = sc.render
    cam = camera or sc.camera
    path = os.path.abspath(path)
    if cam is None:
        raise RuntimeError("beauty_shot needs a camera")
    snap = _Snapshot()
    try:
        aspect = r.resolution_y / max(1, r.resolution_x)
        snap.set(sc, "camera", cam)
        snap.set(r, "resolution_x", res)
        snap.set(r, "resolution_y", int(res * aspect) // 2 * 2)
        snap.set(r, "resolution_percentage", 100)
        snap.set(r, "filepath", path)
        snap.set(r, "use_stamp", False)
        snap.set(r.image_settings, "file_format", "PNG")
        snap.set(r.image_settings, "color_mode", "RGB")
        if r.engine == "CYCLES":
            snap.set(sc.cycles, "samples", samples)
            snap.set(sc.cycles, "use_denoising", True)
        elif r.engine.startswith("BLENDER_EEVEE"):
            snap.set(sc.eevee, "taa_render_samples", samples)
        bpy.ops.render.render(write_still=True)
    finally:
        snap.restore()
    return path
