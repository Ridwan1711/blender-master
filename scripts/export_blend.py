"""Export a .blend to GLB/glTF, FBX, OBJ or USD and VERIFY by re-importing into an empty scene.

python bk.py run scripts/export_blend.py --blend scene.blend -- --out out/model.glb
        [--collections Props,Character] [--subjects] [--no-verify]
Format comes from the extension (.glb .gltf .fbx .obj .usd/.usdc/.usdz).
Never modifies the .blend (not saved). Cameras/lights are excluded.
"""
import argparse
import os
import sys

import bpy

from bkit import emit
from bkit import inspect as I

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--collections")
ap.add_argument("--subjects", action="store_true", help="export only bk_subject objects (+children)")
ap.add_argument("--no-verify", action="store_true")
a = ap.parse_args(sys.argv[1:])
out = os.path.abspath(a.out)
os.makedirs(os.path.dirname(out), exist_ok=True)
ext = os.path.splitext(out)[1].lower()

# selection
if a.collections:
    names = a.collections.split(",")
    objs = [o for n in names for o in bpy.data.collections[n].all_objects if o.type in I.GEOMETRY_TYPES]
elif a.subjects:
    objs = I.subjects()
else:
    objs = I.renderable()
objs = [o for o in objs if not o.name.startswith(("CUT_", "CTL_"))]
vl = bpy.context.view_layer
for o in vl.objects:
    o.select_set(False)
for o in objs:
    o.select_set(True)
vl.objects.active = objs[0] if objs else None
src_tris = sum(I.evaluated_tris()["per_object"].get(o.name, 0) for o in objs)

if ext in (".glb", ".gltf"):
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
                              use_selection=True, export_apply=True, export_cameras=False,
                              export_lights=False, export_yup=True)
elif ext == ".fbx":
    bpy.ops.export_scene.fbx(filepath=out, use_selection=True, use_mesh_modifiers=True,
                             object_types={"MESH", "ARMATURE", "EMPTY"}, apply_scale_options="FBX_SCALE_ALL",
                             path_mode="COPY", embed_textures=True)
elif ext == ".obj":
    bpy.ops.wm.obj_export(filepath=out, export_selected_objects=True, apply_modifiers=True,
                          export_materials=True)
elif ext in (".usd", ".usdc", ".usda", ".usdz"):
    bpy.ops.wm.usd_export(filepath=out, selected_objects_only=True)
else:
    raise ValueError("unsupported export format: %s" % ext)
if not os.path.isfile(out):
    raise RuntimeError("exporter wrote nothing to %s" % out)
result = {"out": out, "bytes": os.path.getsize(out), "objects": len(objs), "source_tris": src_tris}

if not a.no_verify:
    # re-import into a fresh, empty scene and compare
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=out)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=out)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=out)
    else:
        bpy.ops.wm.usd_import(filepath=out)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    tris = I.evaluated_tris()["total"]
    result.update(reimported_meshes=len(meshes), reimported_tris=tris,
                  materials=len([m for m in bpy.data.materials if m.users]),
                  tris_match=abs(tris - src_tris) <= max(4, src_tris * 0.001))
    if not meshes:
        raise RuntimeError("re-import found no meshes in %s" % out)
emit(export=result)
