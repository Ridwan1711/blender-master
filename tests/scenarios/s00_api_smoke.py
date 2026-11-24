"""S00 - API smoke test: every bkit helper not exercised by s01-s09 is called once with asserts.

Run: python scripts/bk.py run tests/scenarios/s00_api_smoke.py
Emits {"checked": [...], "failed": {name: error}}; exits non-zero if anything failed.
"""
import math
import os
import tempfile

import bpy

from bkit import anim as A
from bkit import camera as C
from bkit import compat, emit
from bkit import geonodes as G
from bkit import inspect as I
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import preview as P
from bkit import render as R
from bkit import rig as RG
from bkit import scene as S

S.new_scene()
tmp = tempfile.mkdtemp(prefix="bkit_smoke_")
checked, failed = [], {}


def case(name):
    def deco(fn):
        try:
            fn()
            checked.append(name)
        except Exception as e:  # noqa: BLE001
            failed[name] = "%s: %s" % (type(e).__name__, str(e)[:200])
        return fn
    return deco


@case("mesh.smart_uv")
def _():
    ob = M.box("GEO_UVBox", (1, 1, 1))
    ob.data.uv_layers.clear() if hasattr(ob.data.uv_layers, "clear") else None
    M.smart_uv(ob)
    assert len(ob.data.uv_layers) >= 1


@case("mesh.join")
def _():
    a = M.box("GEO_JoinA", (1, 1, 1))
    b = M.box("GEO_JoinB", (1, 1, 1), location=(2, 0, 0))
    j = M.join([a, b], name="GEO_Joined")
    assert len(j.data.polygons) == 12 and "GEO_JoinB" not in bpy.data.objects


@case("mesh.apply_transform+set_origin+drop_to+apply_modifiers")
def _():
    ob = M.box("GEO_Xf", (1, 1, 1), location=(0, 0, 3))
    ob.scale = (2, 1, 1)
    M.apply_transform(ob)
    assert tuple(ob.scale) == (1, 1, 1) and abs(ob.dimensions.x - 2) < 1e-5
    M.set_origin(ob, "BOUNDS_BOTTOM")
    M.drop_to(ob, 0.0)
    assert abs(M.world_bounds([ob], exact=True)[0].z) < 1e-4
    M.bevel(ob, 0.05, 2)
    n0 = len(ob.data.polygons)
    M.apply_modifiers(ob)
    assert len(ob.data.polygons) > n0 and not ob.modifiers


@case("materials.pbr (generated texture set)")
def _():
    folder = os.path.join(tmp, "tex")
    os.makedirs(folder)
    for nm, col in (("crate_basecolor", (0.6, 0.3, 0.1, 1)), ("crate_roughness", (0.5, 0.5, 0.5, 1)),
                    ("crate_normal_gl", (0.5, 0.5, 1.0, 1))):
        img = bpy.data.images.new(nm, 16, 16)
        img.pixels.foreach_set(list(col) * 256)
        img.filepath_raw = os.path.join(folder, nm + ".png")
        img.file_format = "PNG"
        img.save()
    maps = MT.find_texture_set(folder)
    assert set(maps) == {"base", "rough", "normal"}, maps
    m = MT.pbr("MAT_PBR", folder, scale=2.0)
    imgs = [n.image for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"]
    cs = {os.path.basename(i.filepath): i.colorspace_settings.name for i in imgs}
    assert cs["crate_basecolor.png"] == "sRGB" and cs["crate_roughness.png"] == "Non-Color", cs


@case("lighting.world_hdri (generated .hdr)")
def _():
    img = bpy.data.images.new("sky", 32, 16, float_buffer=True)
    img.pixels.foreach_set([0.5, 0.6, 0.8, 1.0] * 512)
    path = os.path.join(tmp, "sky.hdr")
    img.filepath_raw = path
    img.file_format = "HDR"
    img.save()
    w = L.world_hdri(path, strength=1.2, rotation_deg=90)
    assert any(n.bl_idname == "ShaderNodeTexEnvironment" for n in w.node_tree.nodes)


@case("lighting.light kinds + kelvin")
def _():
    for k in ("POINT", "SPOT", "AREA", "SUN"):
        L.light(k, "LGT_Smoke%s" % k, energy=10, target=(0, 0, 0))
    r, g, b = L.kelvin(3200)
    assert r > b


@case("render.glare + mist (compositor)")
def _():
    R.glare(threshold=0.8)
    R.mist(start=5, depth=50)
    tree = compat.compositor_tree(bpy.context.scene)
    kinds = {n.bl_idname for n in tree.nodes}
    assert "CompositorNodeGlare" in kinds and "CompositorNodeMixRGB" in kinds


@case("camera.dolly + rack_focus + anim.noise + motion_report")
def _():
    cam = C.add("CAM_Smoke", lens=35, location=(0, -6, 2), target=(0, 0, 0))
    C.dolly(cam, (0, -6, 2), (0, -3, 1.5), frames=(1, 48), aim=(0, 0, 0.5))
    C.rack_focus(cam, [(1, 2.0), (48, 4.0)])
    A.noise(cam, "rotation_euler", strength=0.005)
    rep = A.motion_report(cam, list(range(1, 49)))
    assert rep["path_length"] > 3.0 and not rep["pops_at_frames"], rep
    fd = A.sample(cam, "data.dof.focus_distance", [1, 48])
    assert abs(fd[0] - 2.0) < 1e-4 and abs(fd[1] - 4.0) < 1e-4, fd


@case("render.estimate")
def _():
    sc = bpy.context.scene
    R.configure(engine="CYCLES", quality="preview", resolution=(320, 180), samples=4)
    sc.camera = bpy.data.objects["CAM_Smoke"]
    est = R.estimate(sc, scale=0.25)
    assert est["est_seconds_per_frame"] >= 0


@case("geonodes.instance_grid + set_inputs")
def _():
    src = M.sphere("GEO_GridSrc", 0.1)
    grid = G.instance_grid("FX_Grid", src, count=(4, 3), spacing=(0.5, 0.5), jitter=0.05, seed=1)
    S.refresh()
    assert I.evaluated_tris()["per_object"].get("FX_Grid", 0) > 0


@case("rig.bind_groups + weight_report")
def _():
    arm = RG.armature("RIG_Smoke", [dict(name="a", head=(0, 0, 0), tail=(0, 0, 1)),
                                    dict(name="b", head=(0, 0, 1), tail=(0, 0, 2), parent="a", connect=True)])
    col = M.cylinder("GEO_Col", 0.1, 2.0, origin="BOTTOM")
    assign = {"a": [(v.index, 1.0) for v in col.data.vertices if v.co.z < 1.0],
              "b": [(v.index, 1.0) for v in col.data.vertices if v.co.z >= 1.0]}
    rep = RG.bind_groups(col, arm, assign)
    assert rep["unweighted_vertices"] == 0 and not rep["bones_without_weights"], rep


@case("scene.apply_naming + purge_orphans + collection/move_to")
def _():
    me = bpy.data.meshes.new("tmp")
    ob = S.add_object("Cube", me)
    ch = S.apply_naming([ob])
    assert ob.name.startswith("GEO_"), ch
    S.move_to(ob, "Smoke")
    assert ob.users_collection[0].name == "Smoke"
    bpy.data.materials.new("orphan_mat")
    assert S.purge_orphans() >= 1


@case("compat.set_blend_mode + set_engine all")
def _():
    m = MT.principled("MAT_Alpha", (1, 1, 1), alpha=0.5)
    compat.set_blend_mode(m, "BLEND")
    for e in ("WORKBENCH", "EEVEE", "CYCLES"):
        compat.set_engine(bpy.context.scene, e)


@case("preview.views clay+random modes")
def _():
    out = os.path.join(tmp, "pv")
    r1 = P.views(out, objs=[bpy.data.objects["GEO_Col"]], views=("front",), res=160, mode="clay")
    r2 = P.views(out, objs=[bpy.data.objects["GEO_Col"]], views=("persp",), res=160, mode="random")
    assert os.path.isfile(r1["sheet"]) and os.path.isfile(r2["sheet"])


@case("inspect.intersections contact vs penetration (known geometry)")
def _():
    base = (20.0, 0.0)  # far from other smoke objects
    f = M.box("GEO_IxFloor", (4, 4, 0.2), location=(base[0], 0, -0.1))
    M.box("GEO_IxSunk", (0.5, 0.5, 0.5), location=(base[0], 0, 0.2))           # 50 mm into floor
    M.box("GEO_IxResting", (0.5, 0.5, 0.5), location=(base[0] + 1, 0, 0.2497))  # 0.3 mm (solver-like)
    M.box("GEO_IxBase", (0.2, 0.6, 0.2), location=(base[0] - 1, 0, 0.1))
    M.box("GEO_IxCross", (0.6, 0.2, 0.2), location=(base[0] - 1, 0, 0.2995))   # crossing sliver 0.5 mm
    M.box("GEO_IxWall", (1, 0.2, 1), location=(base[0], 1.5, 0.5))
    M.box("GEO_IxBeam", (0.1, 1.0, 0.1), location=(base[0], 1.5, 0.6))         # pierces, no vertex inside
    objs = [o for o in bpy.data.objects if o.name.startswith("GEO_Ix")]
    got = {tuple(sorted((p["a"], p["b"]))): (p["kind"], p["depth_mm"]) for p in I.intersections(objs)["pairs"]}
    want = {("GEO_IxFloor", "GEO_IxSunk"): "penetration", ("GEO_IxFloor", "GEO_IxResting"): "contact",
            ("GEO_IxBase", "GEO_IxCross"): "contact", ("GEO_IxBeam", "GEO_IxWall"): "penetration"}
    for k, kind in want.items():
        assert got[k][0] == kind, (k, got[k])
    assert abs(got[("GEO_IxFloor", "GEO_IxSunk")][1] - 50.0) < 1.0, got


@case("export round-trip OBJ (inline)")
def _():
    path = os.path.join(tmp, "col.obj")
    S.select_only([bpy.data.objects["GEO_Col"]])
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    assert os.path.getsize(path) > 100


emit(checked=checked, failed=failed, n_checked=len(checked), n_failed=len(failed))
if failed:
    raise SystemExit("smoke failures: %s" % sorted(failed))
