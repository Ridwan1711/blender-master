"""Post-reconstruction pipeline: clean, normalise, optimise, bake and export for game engines.

Blender-only constructs do NOT survive export: modifiers (unless applied), procedural shader
nodes, colour-attribute materials, Geometry Nodes instances. This module converts them into what
glTF/FBX and Godot/Unity understand: one mesh per asset, image textures on a Principled BSDF,
sane origin/scale, optional LODs.

    from bkit import gameprep as GP
    rep = GP.cleanup(ob)                                 # apply mods, weld, normals, loose parts
    GP.normalize(ob, height_m=1.8, origin="BOTTOM")      # real size, pivot at the feet
    GP.decimate(ob, target_tris=5000)                    # budget
    GP.bake_materials(ob, size=1024)                     # procedural/vertex colour -> textures
    lods = GP.make_lods(ob, ratios=(1, .5, .25))         # Unity-style _LOD0.._LOD2
    GP.export(ob, "out/asset.glb", engine="godot")       # + re-import verification
"""
import math
import os

import bmesh
import bpy
import numpy as np

from . import compat
from . import inspect as _inspect
from . import materials as _mat
from . import mesh as _mesh
from . import scene as _scene


# --------------------------------------------------------------------------- cleanup
def cleanup(ob, merge_dist=1e-5, remove_loose=True, min_part_ratio=0.0):
    """Apply modifiers, weld duplicates, delete loose verts/edges (and tiny islands if
    min_part_ratio > 0, e.g. 0.002 = parts under 0.2% of the faces - AI reconstruction debris),
    recalculate normals, clear custom split normals. Returns before/after stats."""
    before = _mesh.stats(ob)
    if ob.modifiers:
        _mesh.apply_modifiers(ob)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
    removed_parts = 0
    if remove_loose:
        loose_v = [v for v in bm.verts if not v.link_edges]
        loose_e = [e for e in bm.edges if not e.link_faces]
        bmesh.ops.delete(bm, geom=loose_e, context="EDGES")
        bmesh.ops.delete(bm, geom=[v for v in loose_v if v.is_valid], context="VERTS")
    if min_part_ratio > 0 and bm.faces:
        bm.faces.ensure_lookup_table()
        islands, seen = [], set()
        for f in bm.faces:
            if f.index in seen:
                continue
            stack, isl = [f], []
            seen.add(f.index)
            while stack:
                cur = stack.pop()
                isl.append(cur)
                for e in cur.edges:
                    for nf in e.link_faces:
                        if nf.index not in seen:
                            seen.add(nf.index)
                            stack.append(nf)
            islands.append(isl)
        total = len(bm.faces)
        kill = [f for isl in islands if len(isl) < total * min_part_ratio for f in isl]
        removed_parts = sum(1 for isl in islands if len(isl) < total * min_part_ratio)
        if kill:
            bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    if ob.data.has_custom_normals if hasattr(ob.data, "has_custom_normals") else False:
        with compat.override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
    ob.data.update()
    return {"before": before, "after": _mesh.stats(ob), "removed_small_parts": removed_parts}


def normalize(ob, height_m=None, origin="BOTTOM", face="-Y"):
    """Apply transforms, put the pivot at the bottom centre (origin='BOTTOM') or bounds centre
    ('CENTER'), move to the world origin and scale to `height_m`. Engines expect: metres,
    pivot at the feet for props/characters, the asset's front along the exporter's forward axis
    (bkit convention: front faces -Y; the glTF exporter maps Blender -Y forward to glTF +Z)."""
    _scene.refresh()
    _mesh.apply_transform(ob, location=False, rotation=True, scale=True)
    if height_m:
        f = height_m / max(ob.dimensions.z, 1e-9)
        from mathutils import Matrix
        ob.data.transform(Matrix.Diagonal((f, f, f, 1)))
        ob.data.update()
    _mesh.set_origin(ob, "BOUNDS_BOTTOM" if origin == "BOTTOM" else "BOUNDS_CENTER")
    ob.location = (0, 0, 0)
    _scene.refresh()
    return {"dimensions_m": [round(x, 4) for x in ob.dimensions], "origin": origin}


def decimate(ob, target_tris=None, ratio=None, planar_deg=None):
    """Polygon reduction. planar_deg=5 merges coplanar faces (great for voxels/hard-surface,
    keeps UV/material borders); otherwise collapse to target_tris or ratio. Applied immediately."""
    if planar_deg is not None:
        m = ob.modifiers.new("Planar", "DECIMATE")
        m.decimate_type = "DISSOLVE"
        m.angle_limit = math.radians(planar_deg)
        m.delimit = {"UV", "MATERIAL", "SHARP"}
        _mesh.apply_modifiers(ob)
    tris = _mesh.stats(ob, evaluated=False)["tris"]
    if target_tris and tris > target_tris:
        ratio = target_tris / tris
    if ratio and ratio < 1.0:
        m = ob.modifiers.new("Collapse", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = ratio
        compat.try_set(m, "use_collapse_triangulate", True)
        _mesh.apply_modifiers(ob)
    return _mesh.stats(ob, evaluated=False)


def make_lods(ob, ratios=(1.0, 0.5, 0.25), naming="unity"):
    """LOD copies with collapse decimation. unity: <name>_LOD0/_LOD1/... (Unity builds a LODGroup on
    FBX import). godot: Godot 4 generates LODs itself on import - export LOD0 only (returns [ob])."""
    if naming == "godot":
        return [ob]
    base = ob.name
    ob.name = base + "_LOD0"
    out = [ob]
    for i, r in enumerate(ratios[1:], 1):
        c = ob.copy()
        c.data = ob.data.copy()
        c.name = "%s_LOD%d" % (base, i)
        for coll in ob.users_collection:
            coll.objects.link(c)
        decimate(c, ratio=r)
        out.append(c)
    return out


# --------------------------------------------------------------------------- baking
def _principled(mat):
    if not mat or not mat.use_nodes:
        return None
    return next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)


def needs_bake(mat):
    """True if the material uses anything an engine importer cannot read directly: procedural
    textures, colour attributes, math/ramp nodes feeding the BSDF, several BSDFs, etc.
    A Principled with plain values or Image Texture -> BSDF links is engine-safe."""
    if not mat or not mat.use_nodes:
        return False
    ok = {"ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial", "ShaderNodeTexImage", "ShaderNodeNormalMap",
          "ShaderNodeUVMap", "ShaderNodeTexCoord", "ShaderNodeMapping", "ShaderNodeSeparateColor"}
    return any(n.bl_idname not in ok for n in mat.node_tree.nodes if n.type != "FRAME")


def bake_materials(ob, size=1024, maps=("Base Color", "Roughness", "Metallic"), normal=True, samples=4,
                   out_dir=None, margin=8):
    """Bake every non-engine-safe material on `ob` into image textures on ONE new Principled
    material (glTF/FBX-safe). Each Principled input is baked through an emission pass (exact
    values, no lighting); bump/normal detail via a tangent normal bake. Needs Cycles; creates
    UVs (smart UV) if missing. Images are packed (and saved to out_dir if given)."""
    sc = bpy.context.scene
    mats = [m for m in ob.data.materials if m]
    if not mats:
        return {"baked": False, "reason": "no materials"}
    if not any(needs_bake(m) for m in mats) and len(mats) == 1:
        return {"baked": False, "reason": "already engine-safe"}
    if not ob.data.uv_layers:
        _mesh.smart_uv(ob)
    keep_engine = sc.render.engine
    compat.set_engine(sc, "CYCLES")
    keep_samples = sc.cycles.samples
    sc.cycles.samples = samples
    from .render import setup_device
    setup_device(sc, "CPU")
    name = ob.name.replace("GEO_", "")
    images = {}
    _scene.select_only(ob)

    def target_image(label, non_color):
        img = bpy.data.images.new("%s_%s" % (name, label.replace(" ", "")), size, size, alpha=False,
                                  float_buffer=False)
        img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        return img

    def plug_target(img):
        nodes = []
        for m in mats:
            n = m.node_tree.nodes.new("ShaderNodeTexImage")
            n.image = img
            m.node_tree.nodes.active = n
            nodes.append((m, n))
        return nodes

    def unplug(nodes):
        for m, n in nodes:
            m.node_tree.nodes.remove(n)

    result = {}
    for label in maps:
        img = target_image(label, label != "Base Color")
        rewired = []
        for m in mats:
            nt = m.node_tree
            b = _principled(m)
            out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output), None)
            if out is None:
                continue
            em = nt.nodes.new("ShaderNodeEmission")
            surf_link = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].is_linked else None
            if b is not None:
                sock = compat.socket(b, label)
                if sock.is_linked:
                    nt.links.new(sock.links[0].from_socket, em.inputs["Color"])
                else:
                    v = sock.default_value
                    em.inputs["Color"].default_value = tuple(v) if hasattr(v, "__len__") else (v, v, v, 1.0)
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            rewired.append((m, em, out, surf_link))
        tn = plug_target(img)
        with compat.override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.object.bake(type="EMIT", margin=margin, use_clear=True)
        unplug(tn)
        for m, em, out, surf_link in rewired:
            if surf_link is not None:
                m.node_tree.links.new(surf_link, out.inputs["Surface"])
            m.node_tree.nodes.remove(em)
        images[label] = img
        result[label] = img.name
    if normal:
        img = target_image("Normal", True)
        tn = plug_target(img)
        with compat.override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=margin, use_clear=True)
        unplug(tn)
        images["Normal"] = img
        result["Normal"] = img.name
    # one clean engine material
    nm = _mat.new_material("MAT_%s_Baked" % name, reuse=False)
    nt = _mat.Nodes(nm.node_tree)
    for label, img in images.items():
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            img.filepath_raw = os.path.join(os.path.abspath(out_dir), img.name + ".png")
            img.file_format = "PNG"
            img.save()
        img.pack()
        t = nt.new("ShaderNodeTexImage")
        t.image = img
        if label == "Normal":
            nmap = nt.new("ShaderNodeNormalMap")
            nt.link(t, "Color", nmap, "Color")
            nt.link(nmap, "Normal", nt.bsdf, "Normal")
        else:
            nt.link(t, "Color", nt.bsdf, label)
    nt.layout()
    ob.data.materials.clear()
    ob.data.materials.append(nm)
    sc.cycles.samples = keep_samples
    sc.render.engine = keep_engine
    return {"baked": True, "material": nm.name, "images": result, "size": size}


# --------------------------------------------------------------------------- export
ENGINE_PRESETS = {
    # glTF: Y-up, metres, -Y forward handled by the exporter. Godot 4 imports .glb natively and
    # generates LODs + collision on import (import settings), so export LOD0 only.
    "godot": {"format": ".glb"},
    # Unity: FBX with all-scale application so the asset arrives at scale 1 with no -90 X rotation
    # on the root; meshes named *_LOD0.. become a LODGroup. glTF needs a package (glTFast).
    "unity": {"format": ".fbx"},
}


def export(objs, path, engine="godot", verify=True):
    """Export selected objects for an engine and verify by re-importing into an empty scene:
    triangle count, dimensions, materials that use image textures, no procedural leftovers."""
    objs = [objs] if hasattr(objs, "name") else list(objs)
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    src = {"tris": sum(_mesh.stats(o)["tris"] for o in objs),
           "dims": [round(x, 3) for x in _mesh.world_bounds(objs, exact=True)[2]],
           "bake_needed": [m.name for o in objs for m in o.data.materials if m and needs_bake(m)]}
    _scene.select_only(objs)
    if ext in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
                                  use_selection=True, export_apply=True, export_yup=True,
                                  export_cameras=False, export_lights=False)
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, use_mesh_modifiers=True,
                                 apply_scale_options="FBX_SCALE_ALL", bake_space_transform=True,
                                 axis_forward="-Z", axis_up="Y", object_types={"MESH", "ARMATURE", "EMPTY"},
                                 path_mode="COPY", embed_textures=True, mesh_smooth_type="FACE")
    elif ext == ".obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, apply_modifiers=True,
                              export_materials=True, path_mode="COPY")
    else:
        raise ValueError("unsupported export format " + ext)
    rep = {"path": path, "engine": engine, "bytes": os.path.getsize(path), "source": src}
    if src["bake_needed"]:
        rep["warning"] = "materials not engine-safe (bake_materials first): %s" % src["bake_needed"]
    if verify:
        rep["verify"] = verify_file(path, src)
    return rep


def verify_file(path, src=None):
    """Re-import into a temporary scene (the current scene is untouched) and compare."""
    keep_scene = bpy.context.window.scene if bpy.context.window else bpy.context.scene
    tmp = bpy.data.scenes.new("bk_verify")
    if bpy.context.window:
        bpy.context.window.scene = tmp
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    try:
        with compat.override(scene=tmp):
            if ext in (".glb", ".gltf"):
                bpy.ops.import_scene.gltf(filepath=path)
            elif ext == ".fbx":
                bpy.ops.import_scene.fbx(filepath=path)
            else:
                bpy.ops.wm.obj_import(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        meshes = [o for o in new if o.type == "MESH"]
        dg = bpy.context.evaluated_depsgraph_get()
        tris = 0
        for o in meshes:
            me = o.evaluated_get(dg).to_mesh()
            tris += sum(len(p.vertices) - 2 for p in me.polygons)
            o.evaluated_get(dg).to_mesh_clear()
        _scene.refresh()
        dims = [round(x, 3) for x in _mesh.world_bounds(meshes, exact=True)[2]] if meshes else None
        mats = {m.name for o in meshes for m in o.data.materials if m}
        textured = sorted(m for m in mats if any(n.bl_idname == "ShaderNodeTexImage" and n.image
                                                for n in bpy.data.materials[m].node_tree.nodes))
        out = {"meshes": len(meshes), "names": [o.name for o in meshes][:10], "tris": tris, "dims_m": dims,
               "materials": sorted(mats), "textured_materials": textured}
        if src:
            out["tris_match"] = abs(tris - src["tris"]) <= max(4, 0.002 * src["tris"])
            out["dims_match"] = all(abs(a - b) <= max(0.01, 0.01 * b) for a, b in zip(dims or [0, 0, 0], src["dims"]))
    finally:
        for o in [o for o in bpy.data.objects if o not in before]:
            bpy.data.objects.remove(o, do_unlink=True)
        if bpy.context.window:
            bpy.context.window.scene = keep_scene
        bpy.data.scenes.remove(tmp)
    return out


def asset_report(ob):
    """What an engine will receive: size, pivot, tris, UVs, materials (engine-safe or not)."""
    _scene.refresh()
    mn, mx, size, c = _mesh.world_bounds([ob], exact=True)
    return {"name": ob.name, "dims_m": [round(x, 3) for x in size],
            "pivot_at_bottom_centre": abs(mn.z - ob.location.z) < 1e-3 and abs(c.x - ob.location.x) < 1e-3
            and abs(c.y - ob.location.y) < 1e-3,
            "scale_applied": all(abs(s - 1) < 1e-6 for s in ob.scale), "tris": _mesh.stats(ob)["tris"],
            "uv_layers": len(ob.data.uv_layers), "materials": [m.name for m in ob.data.materials if m],
            "engine_safe_materials": not any(needs_bake(m) for m in ob.data.materials if m),
            "health": {k: v for k, v in _inspect.mesh_health(ob).items()
                       if k in ("closed", "boundary_edges", "multi_face_edges", "inconsistent_normal_edges",
                                "inverted", "duplicate_verts", "zero_area_faces")}}
