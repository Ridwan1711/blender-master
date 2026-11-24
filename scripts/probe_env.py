"""Capability probe: what does THIS Blender support? Run via `python bk.py probe [--bench]`.

Never assume an API exists - read this report first in a new environment.
"""
import os
import sys
import tempfile
import time

import bpy
from bkit import compat, emit

S = bpy.context.scene
bench = "--bench" in sys.argv


def ok(f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001
        return "ERR %s: %s" % (type(e).__name__, str(e)[:100])


def accepts(owner, prop, values):
    out = []
    old = getattr(owner, prop)
    for v in values:
        try:
            setattr(owner, prop, v)
            out.append(v)
        except (TypeError, ValueError):
            pass
    setattr(owner, prop, old)
    return out


def gpu_devices():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    res = {}
    for dt in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = dt
        except TypeError:
            continue
        try:
            prefs.refresh_devices()
        except AttributeError:
            prefs.get_devices()
        devs = [d.name for d in prefs.devices if d.type == dt]
        if devs:
            res[dt] = devs
    prefs.compute_device_type = "NONE"
    return res


def _principled_v2():
    m = bpy.data.materials.new("_probe")
    m.use_nodes = True
    n = m.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    v2 = "Coat Weight" in [s.name for s in n.inputs]
    bpy.data.materials.remove(m)
    return v2


import addon_utils  # noqa: E402

info = {
    "blender": bpy.app.version_string,
    "version_tuple": list(compat.V),
    "python": sys.version.split()[0],
    "platform": sys.platform,
    "binary": bpy.app.binary_path,
    "engines": accepts(S.render, "engine", ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"]),
    "view_transforms": accepts(S.view_settings, "view_transform",
                               ["AgX", "Filmic", "Standard", "Khronos PBR Neutral", "Filmic Log", "Raw"]),
    "denoisers": accepts(S.cycles, "denoiser", ["OPENIMAGEDENOISE", "OPTIX"]),
    "gpu_devices": ok(gpu_devices),
    "cpu_threads": os.cpu_count(),
    "features": {
        "layered_actions(4.4+)": compat.has_prop(bpy.types.Action, "layers"),
        "node_tree_interface(4.0+)": compat.has_prop(bpy.types.NodeTree, "interface"),
        "gn_node_tools(4.0+)": compat.has_prop(bpy.types.GeometryNodeTree, "is_tool"),
        "gn_repeat_zone(4.0+)": hasattr(bpy.types, "GeometryNodeRepeatInput"),
        "gn_foreach_zone(4.3+)": hasattr(bpy.types, "GeometryNodeForeachGeometryElementInput"),
        "gn_bake_node(4.1+)": hasattr(bpy.types, "GeometryNodeBake"),
        "gn_closures(5.0+)": hasattr(bpy.types, "NodeClosureInput"),
        "mesh_set_sharp_from_angle(4.1+)": compat.has_func(bpy.types.Mesh, "set_sharp_from_angle"),
        "mesh_use_auto_smooth(<4.1)": compat.has_prop(bpy.types.Mesh, "use_auto_smooth"),
        "material_surface_render_method(4.2+)": compat.has_prop(bpy.types.Material, "surface_render_method"),
        "compositor_node_group(5.0+)": compat.has_prop(bpy.types.Scene, "compositing_node_group"),
        "scene_node_tree(<5.0)": compat.has_prop(bpy.types.Scene, "node_tree"),
        "principled_v2(4.0+)": ok(_principled_v2),
        "ffmpeg": bpy.app.build_options.codec_ffmpeg,
        "gltf_io": hasattr(bpy.ops.export_scene, "gltf"),
        "fbx_io": hasattr(bpy.ops.export_scene, "fbx"),
        "usd_io": hasattr(bpy.ops.wm, "usd_export"),
        "obj_io(wm.obj_*)": hasattr(bpy.ops.wm, "obj_export"),
    },
    "addons_enabled": sorted(bpy.context.preferences.addons.keys()),
    "addons_available": ok(lambda: sorted(m.__name__ for m in addon_utils.modules())),
}

if bench:
    # Tiny benchmark so device choice is measured, not guessed.
    from bkit import render as R
    tmp = tempfile.mkdtemp(prefix="bkit_bench_")
    S.render.resolution_x, S.render.resolution_y, S.render.resolution_percentage = 480, 270, 100
    times = {}
    for tag, setup in [("workbench", lambda: compat.set_engine(S, "WORKBENCH")),
                       ("eevee", lambda: (compat.set_engine(S, "EEVEE"), setattr(S.eevee, "taa_render_samples", 16))),
                       ("cycles_cpu", lambda: R.setup_cycles(S, samples=64, device="CPU")),
                       ("cycles_gpu", lambda: R.setup_cycles(S, samples=64, device="GPU"))]:
        try:
            setup()
            if tag == "cycles_gpu" and S.cycles.device != "GPU":
                times[tag] = "no GPU"
                continue
            S.render.filepath = os.path.join(tmp, tag + ".png")
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            times[tag] = round(time.time() - t0, 2)
        except Exception as e:  # noqa: BLE001
            times[tag] = "ERR " + str(e)[:80]
    info["bench_480x270_seconds"] = times
    info["bench_note"] = "EEVEE first render includes shader compilation."

emit(**info)
