"""Render configuration: engines, devices, quality tiers, colour management, output.

    from bkit import render as R
    R.configure(scene, engine="CYCLES", quality="draft", resolution=(1920, 1080))
    R.still(scene, "C:/out/shot.png")
"""
import os
import time

import bpy

from . import compat

# Quality tiers. Samples are a ceiling: adaptive sampling stops early on clean pixels.
TIERS = {
    #            cycles spp, adaptive thr, bounces, eevee spp, eevee raytracing
    "preview": dict(cycles=32, threshold=0.1, bounces=4, eevee=16, raytrace=False),
    "draft": dict(cycles=128, threshold=0.03, bounces=8, eevee=32, raytrace=True),
    "final": dict(cycles=512, threshold=0.01, bounces=12, eevee=128, raytrace=True),
}


def setup_device(scene, device="AUTO"):
    """CPU | GPU | AUTO. AUTO honours env BKIT_DEVICE, else uses a GPU if one exists.

    Returns the backend used ('CPU', 'CUDA', 'OPTIX', 'HIP', 'METAL', 'ONEAPI').
    """
    device = (os.environ.get("BKIT_DEVICE") or device).upper() if device == "AUTO" else device.upper()
    if device == "CPU":
        scene.cycles.device = "CPU"
        return "CPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        try:
            prefs.refresh_devices()
        except AttributeError:  # very old builds
            prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == backend
            scene.cycles.device = "GPU"
            return backend
    scene.cycles.device = "CPU"
    return "CPU"


def setup_cycles(scene, samples=128, device="AUTO", denoise=True, threshold=0.03,
                 bounces=8, clamp_indirect=10.0, caustics=False, time_limit=0):
    compat.set_engine(scene, "CYCLES")
    c = scene.cycles
    backend = setup_device(scene, device)
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = threshold
    c.max_bounces = bounces
    c.diffuse_bounces = min(4, bounces)
    c.glossy_bounces = min(4, bounces)
    c.transmission_bounces = max(4, min(12, bounces))
    c.transparent_max_bounces = 16
    c.sample_clamp_indirect = clamp_indirect
    c.caustics_reflective = caustics
    c.caustics_refractive = caustics
    c.blur_glossy = 1.0
    compat.try_set(c, "time_limit", time_limit)
    c.use_denoising = denoise
    if denoise:
        compat.set_enum(c, "denoiser", ["OPENIMAGEDENOISE", "OPTIX"])
        compat.try_set(c, "denoising_input_passes", "RGB_ALBEDO_NORMAL")
        compat.try_set(c, "denoising_prefilter", "ACCURATE")
        compat.try_set(c, "denoising_use_gpu", backend != "CPU")
    return backend


def setup_eevee(scene, samples=64, raytracing=True, shadows_hq=True):
    compat.set_engine(scene, "EEVEE")
    e = scene.eevee
    e.taa_render_samples = samples
    compat.try_set(e, "use_raytracing", raytracing)            # EEVEE Next (4.2+)
    compat.try_set(e, "use_shadows", True)
    if shadows_hq:
        compat.try_set(e, "shadow_ray_count", 2)
        compat.try_set(e, "shadow_step_count", 12)
    compat.try_set(e, "use_gtao", True)
    compat.try_set(e, "use_ssr", raytracing)                   # legacy EEVEE (<4.2)
    compat.try_set(e, "use_soft_shadows", True)                 # legacy EEVEE
    return scene.render.engine


def setup_workbench(scene, color="MATERIAL", cavity=True, outline=True, light="STUDIO"):
    compat.set_engine(scene, "WORKBENCH")
    sh = scene.display.shading
    sh.light = light
    sh.color_type = color
    sh.show_cavity = cavity
    if cavity:
        compat.try_set(sh, "cavity_type", "BOTH")
    sh.show_object_outline = outline
    compat.try_set(sh, "show_specular_highlight", True)
    compat.try_set(scene.display, "render_aa", "8")
    return scene.render.engine


def color_management(scene, view="AgX", look="None", exposure=0.0, gamma=1.0, display="sRGB"):
    """AgX (4.0+) handles bright lights gracefully; Filmic on 3.x; Standard for UI/graphics."""
    compat.try_set(scene.display_settings, "display_device", display)
    compat.set_enum(scene.view_settings, "view_transform", [view, "AgX", "Filmic", "Standard"])
    looks = [look]
    if look not in ("None",) and not look.startswith(scene.view_settings.view_transform):
        looks.insert(0, "%s - %s" % (scene.view_settings.view_transform, look))
    try:
        compat.set_enum(scene.view_settings, "look", looks + ["None"])
    except ValueError:
        pass
    scene.view_settings.exposure = exposure
    scene.view_settings.gamma = gamma


def configure(scene=None, engine="CYCLES", quality="draft", resolution=(1920, 1080), percentage=100,
              transparent=False, device="AUTO", view="AgX", look="None", exposure=0.0,
              motion_blur=False, samples=None):
    """One call for a sane render setup. Returns a dict describing what was set."""
    scene = scene or bpy.context.scene
    t = TIERS[quality]
    eng = engine.upper()
    info = {"quality": quality}
    if eng == "CYCLES":
        info["device"] = setup_cycles(scene, samples=samples or t["cycles"], device=device,
                                      threshold=t["threshold"], bounces=t["bounces"])
    elif eng.startswith("EEVEE") or eng.startswith("BLENDER_EEVEE"):
        setup_eevee(scene, samples=samples or t["eevee"], raytracing=t["raytrace"])
    elif eng in ("WORKBENCH", "BLENDER_WORKBENCH"):
        setup_workbench(scene)
    else:
        compat.set_engine(scene, eng)
    info["engine"] = scene.render.engine
    r = scene.render
    r.resolution_x, r.resolution_y = resolution
    r.resolution_percentage = percentage
    r.film_transparent = transparent
    r.use_motion_blur = motion_blur
    compat.try_set(r, "use_persistent_data", False)
    color_management(scene, view=view, look=look, exposure=exposure)
    info["view_transform"] = scene.view_settings.view_transform
    info["resolution"] = [r.resolution_x * percentage // 100, r.resolution_y * percentage // 100]
    return info


def abspath(path):
    """Blender resolves bare relative paths ('out/a.png') against the DRIVE ROOT on Windows,
    not the working directory. Keep '//' (blend-relative) paths, absolutise everything else."""
    if not path or path.startswith("//"):
        return path
    keep_sep = path.endswith(("/", "\\"))
    p = os.path.abspath(path)
    return p + os.sep if keep_sep else p


def output_png(scene, path, depth="8", rgba=False):
    s = scene.render.image_settings
    s.file_format = "PNG"
    s.color_mode = "RGBA" if rgba else "RGB"
    s.color_depth = depth
    scene.render.filepath = abspath(path)


def output_video(scene, path, quality="HIGH", fps=None):
    """H.264 MP4. Resolution must be even in both axes."""
    s = scene.render.image_settings
    s.file_format = "FFMPEG"
    ff = scene.render.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    compat.try_set(ff, "constant_rate_factor", quality)
    compat.try_set(ff, "ffmpeg_preset", "GOOD")
    ff.audio_codec = "NONE"
    if fps:
        scene.render.fps = fps
    scene.render.filepath = abspath(path)
    rx = scene.render.resolution_x * scene.render.resolution_percentage // 100
    ry = scene.render.resolution_y * scene.render.resolution_percentage // 100
    if rx % 2 or ry % 2:
        raise ValueError("H.264 needs even resolution, got %dx%d" % (rx, ry))


def still(scene=None, path=None, camera=None):
    """Render the current frame to `path` (PNG unless the format is already set). Returns seconds."""
    scene = scene or bpy.context.scene
    if camera is not None:
        scene.camera = camera
    if scene.camera is None:
        raise RuntimeError("Scene has no camera; add one (bkit.camera.add) before rendering.")
    if path:
        path = abspath(path)
        if scene.render.image_settings.file_format in ("FFMPEG",):
            output_png(scene, path)
        scene.render.filepath = path
    os.makedirs(os.path.dirname(bpy.path.abspath(scene.render.filepath)) or ".", exist_ok=True)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    out = bpy.path.abspath(scene.render.filepath)
    if not os.path.isfile(out):
        raise RuntimeError("Render produced no file at %s (check log for GPU/memory errors)" % out)
    return round(dt, 2)


def animation(scene=None, path=None, frame_start=None, frame_end=None, step=1):
    """Render the frame range. For image sequences give a path prefix like '//frames/shot_'."""
    scene = scene or bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("Scene has no camera.")
    if path:
        scene.render.filepath = abspath(path)
    if frame_start is not None:
        scene.frame_start = frame_start
    if frame_end is not None:
        scene.frame_end = frame_end
    scene.frame_step = step
    t0 = time.time()
    bpy.ops.render.render(animation=True)
    return round(time.time() - t0, 2)


# --------------------------------------------------------------------------- compositor
def _cset(node, key, value):
    """Set a compositor node option that may be a property (<=4.3) or an input socket (4.4+)."""
    prop = key.lower().replace(" ", "_")
    if compat.has_prop(node, prop):
        try:
            setattr(node, prop, value)
            return True
        except (TypeError, ValueError):
            pass
    try:
        compat.set_input(node, key, value)
        return True
    except KeyError:
        return False


def _comp_base(scene):
    """(tree, render_layers_node, image_output_socket_to_feed). Builds RL -> Composite if missing."""
    tree = compat.compositor_tree(scene, create=True)
    rl = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"), None)
    if rl is None:
        rl = tree.nodes.new("CompositorNodeRLayers")
        rl.location = (-600, 0)
    out = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeComposite"), None)
    if out is None and hasattr(bpy.types, "CompositorNodeComposite"):
        out = tree.nodes.new("CompositorNodeComposite")
        out.location = (600, 0)
    if out is None:  # 5.0+: compositor is a node group ending in Group Output (untested here)
        out = next((n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"), None) or tree.nodes.new("NodeGroupOutput")
        if not compat.interface_items(tree, "OUTPUT"):
            compat.new_interface_socket(tree, "Image", "OUTPUT", "NodeSocketColor")
    target = out.inputs[0]
    if not target.is_linked:
        tree.links.new(rl.outputs["Image"], target)
    return tree, rl, target


def _insert_before_output(tree, target, node, in_index=1, out_name="Image"):
    """Splice `node` between whatever feeds `target` and `target`."""
    src = target.links[0].from_socket
    tree.links.new(src, node.inputs[in_index])
    tree.links.new(node.outputs[out_name] if out_name in node.outputs else node.outputs[0], target)
    return node


def mist(scene=None, start=5.0, depth=80.0, color=(0.62, 0.7, 0.8), strength=0.6, falloff="QUADRATIC"):
    """Aerial perspective via the Mist pass: blends distant pixels toward `color` (linear).
    Much cheaper than volumetrics; works for Cycles and EEVEE."""
    scene = scene or bpy.context.scene
    bpy.context.view_layer.use_pass_mist = True
    w = scene.world
    w.mist_settings.start = start
    w.mist_settings.depth = depth
    w.mist_settings.falloff = falloff
    tree, rl, target = _comp_base(scene)
    mul = tree.nodes.new("CompositorNodeMath")
    mul.operation = "MULTIPLY"
    tree.links.new(rl.outputs["Mist"], mul.inputs[0])
    mul.inputs[1].default_value = strength
    mix = tree.nodes.new("CompositorNodeMixRGB")
    mix.blend_type = "MIX"
    mix.inputs[2].default_value = tuple(color)[:3] + (1.0,)
    _insert_before_output(tree, target, mix, in_index=1)
    tree.links.new(mul.outputs[0], mix.inputs[0])
    mul.location, mix.location = (-250, -250), (250, 0)
    return mix


def glare(scene=None, kind="BLOOM", threshold=1.0, strength=0.4, size=6):
    """Bloom/fog glow on highlights (EEVEE Next has no built-in bloom)."""
    scene = scene or bpy.context.scene
    tree, rl, target = _comp_base(scene)
    g = tree.nodes.new("CompositorNodeGlare")
    compat.set_enum(g, "glare_type", [kind, "BLOOM", "FOG_GLOW"])
    _cset(g, "Threshold", threshold)
    _cset(g, "Strength", strength) or _cset(g, "mix", strength - 1.0)
    _cset(g, "Size", size)
    _insert_before_output(tree, target, g, in_index=0)
    g.location = (300, 200)
    return g


# Display value of scene-linear 0.18 (18% grey card under "correct" exposure), measured on
# Blender 4.5 with emission planes (tests/TESTING.md, calibration table).
GREY_TARGET = {"AgX": 0.459, "Khronos PBR Neutral": 0.408, "Filmic": 0.498, "Standard": 0.459}


def auto_exposure(card, target=None, scene=None, res=240, samples=16, lo=-5.0, hi=5.0, iters=7):
    """Set view exposure so `card` (an object with linear albedo 0.18, matte) renders at the
    calibrated mid-grey for the current view transform. Like metering a grey card on set.
    Returns {"exposure": ev, "measured": value, "target": target}. Changes only exposure.
    """
    import tempfile
    from . import inspect as _inspect
    scene = scene or bpy.context.scene
    r = scene.render
    target = target or GREY_TARGET.get(scene.view_settings.view_transform, 0.46)
    keep = dict(x=r.resolution_x, y=r.resolution_y, pct=r.resolution_percentage, path=r.filepath,
                fmt=r.image_settings.file_format, stamp=r.use_stamp)
    ks = None
    if r.engine == "CYCLES":
        ks = scene.cycles.samples
        scene.cycles.samples = samples
    elif r.engine.startswith("BLENDER_EEVEE"):
        ks = scene.eevee.taa_render_samples
        scene.eevee.taa_render_samples = samples
    path = os.path.join(tempfile.gettempdir(), "bkit_meter.png")
    measured = None
    try:
        r.resolution_x, r.resolution_y = res, max(2, int(res * keep["y"] / max(1, keep["x"])))
        r.resolution_percentage = 100
        r.use_stamp = False
        r.image_settings.file_format = "PNG"
        for _ in range(iters):
            ev = (lo + hi) / 2
            scene.view_settings.exposure = ev
            still(scene, path)
            measured = _inspect.sample_object(path, card, radius_px=2)["value"]
            if measured > target:
                hi = ev
            else:
                lo = ev
        scene.view_settings.exposure = round((lo + hi) / 2, 3)
    finally:
        r.resolution_x, r.resolution_y, r.resolution_percentage = keep["x"], keep["y"], keep["pct"]
        r.filepath, r.image_settings.file_format, r.use_stamp = keep["path"], keep["fmt"], keep["stamp"]
        if ks is not None:
            if r.engine == "CYCLES":
                scene.cycles.samples = ks
            else:
                scene.eevee.taa_render_samples = ks
    return {"exposure": scene.view_settings.exposure, "measured": measured, "target": target}


def estimate(scene=None, scale=0.25, frames=1):
    """Render once at `scale` resolution to estimate full-res time (roughly linear in pixels)."""
    import tempfile
    scene = scene or bpy.context.scene
    r = scene.render
    old_pct, old_path = r.resolution_percentage, r.filepath
    r.resolution_percentage = max(1, int(old_pct * scale))
    r.filepath = os.path.join(tempfile.gettempdir(), "bkit_estimate.png")
    try:
        dt = still(scene)
    finally:
        r.resolution_percentage, r.filepath = old_pct, old_path
    full = dt / (scale * scale)
    return {"probe_seconds": dt, "est_seconds_per_frame": round(full, 1),
            "est_total_seconds": round(full * frames, 1)}
