"""Scene QA rule engine. Every issue: severity, code, object, message, fix hint.

    from bkit import validate as V
    res = V.run(tier="hero")
    res["score"], res["counts"], res["issues"]

Severities: error (must fix before delivery), warn (fix or justify), info (hygiene).
"""
import os
import re

import bpy

from . import compat
from . import inspect as I

TIERS = {  # max evaluated triangles: per object, whole scene
    "mobile": (5_000, 150_000),
    "game": (40_000, 2_000_000),
    "hero": (400_000, 8_000_000),
    "film": (3_000_000, 60_000_000),
}
DEFAULT_NAME = re.compile(r"^(Cube|Plane|Sphere|Icosphere|Cylinder|Cone|Torus|Circle|Suzanne|Empty|"
                          r"Camera|Light|Point|Sun|Spot|Area|Text|BezierCurve|NurbsPath|Armature|"
                          r"Material|Object|Mesh|Grid)(\.\d{3})?$")
SCALE_SENSITIVE = {"BEVEL", "SOLIDIFY", "WIREFRAME", "SCREW", "DISPLACE", "SKIN"}


class Issues(list):
    def add(self, sev, code, obj, msg, fix=""):
        self.append({"sev": sev, "code": code, "obj": obj, "msg": msg, "fix": fix})


def _check_references(iss):
    for im in I.image_status():
        if not im["exists"] and not im["packed"] and im["users"] > 0:
            iss.add("error", "REF_MISSING_IMAGE", im["name"], "image file not found: %s" % im["path"],
                    "relink (File > External Data > Find Missing) or pack; check relative paths")
        elif im["path"].startswith(("C:", "/", "\\")) and not im["path"].startswith("//") and bpy.data.filepath:
            iss.add("info", "REF_ABSOLUTE_PATH", im["name"], "absolute path breaks on other machines",
                    "bpy.ops.file.make_paths_relative() or pack resources")
    for lib in bpy.data.libraries:
        if not os.path.exists(bpy.path.abspath(lib.filepath)):
            iss.add("error", "REF_MISSING_LIBRARY", lib.name, "linked library missing: %s" % lib.filepath,
                    "relink library path")


def _check_camera(iss, sc, subjects):
    if sc.camera is None:
        iss.add("error", "CAM_NONE", None, "scene has no active camera", "bkit.camera.add() / scene.camera = ...")
        return None
    cov = I.camera_coverage(sc.camera, subjects, sc)
    for o in cov["objects"]:
        if o["status"] == "outside":
            iss.add("error", "CAM_SUBJECT_OUTSIDE", o["name"], "subject not visible from scene camera",
                    "camera.frame(cam, subjects) or tag non-subjects (collection 'Environment')")
        elif o["status"] == "cropped":
            iss.add("warn", "CAM_SUBJECT_CROPPED", o["name"], "subject crosses frame edge %s" % o["bbox_frame"],
                    "increase margin / pull back; ignore if intentional close-up")
    if subjects and cov["subject_fill"] < 0.04:
        iss.add("warn", "CAM_SUBJECT_SMALL", None, "subjects fill only %.1f%% of frame" % (cov["subject_fill"] * 100),
                "move camera closer or use a longer lens")
    return cov


def _check_lighting(iss, sc):
    lights = [o for o in sc.objects if o.type == "LIGHT" and not o.hide_render]
    w = I.world_summary(sc)
    world_lit = w.get("type") in ("sky", "hdri", "gradient") or (
        w.get("type") == "color" and (w.get("strength") or 0) > 0 and sum(w.get("color", [0])) > 0.05)
    emissive = any(
        n.bl_idname == "ShaderNodeBsdfPrincipled" and compat.socket(n, "Emission Strength").default_value > 0
        and sum(compat.socket(n, "Emission Color").default_value[:3]) > 0
        for m in bpy.data.materials if m.users and m.use_nodes and m.node_tree for n in m.node_tree.nodes)
    if not lights and not world_lit and not emissive:
        iss.add("error", "LIGHT_NONE", None, "no lights, dark world and no emitters: render will be black",
                "bkit.lighting.three_point(...) or world_sky(...)")
    for o in lights:
        if o.data.energy <= 0:
            iss.add("warn", "LIGHT_ZERO", o.name, "light energy is 0", "set energy")
    return {"lights": len(lights), "world": w}


def _material_uses_uv_images(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return False
    for n in mat.node_tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image:
            vec = n.inputs.get("Vector")
            if vec is None or not vec.is_linked:
                return True  # default vector = UV
            src = vec.links[0].from_socket
            if src.name == "UV" or src.node.bl_idname in ("ShaderNodeUVMap",):
                return True
            if src.node.bl_idname == "ShaderNodeMapping":
                v2 = src.node.inputs["Vector"]
                if not v2.is_linked or v2.links[0].from_socket.name == "UV":
                    return True
    return False


def _check_objects(iss, sc, tier, health, intersect, subjects):
    per_max, scene_max = TIERS[tier]
    tri = I.evaluated_tris(sc)
    cutters = {m.object.name for o in sc.objects for m in o.modifiers
               if m.type == "BOOLEAN" and getattr(m, "object", None)}
    for ob in sc.objects:
        if DEFAULT_NAME.match(ob.name):
            iss.add("info", "NAME_DEFAULT", ob.name, "default name", "rename with a prefix (GEO_, LGT_, CAM_ ...)")
        if ob.name in cutters and not ob.hide_render:
            iss.add("error", "CUTTER_RENDERS", ob.name, "boolean cutter is visible in render",
                    "ob.hide_render = True (bkit.mesh.boolean does this)")
        if ob.type not in I.GEOMETRY_TYPES or ob.hide_render or ob.name in cutters:
            continue
        if ob.hide_viewport != ob.hide_render and ob.hide_viewport:
            iss.add("info", "HIDDEN_MISMATCH", ob.name, "hidden in viewport but renders", "make visibility consistent")
        instancer = I.is_instancer(ob)
        if hasattr(ob.data, "materials") and not instancer:
            mats = list(ob.data.materials)
            if not mats or all(m is None for m in mats):
                iss.add("warn", "MAT_NONE", ob.name, "renders without a material (default grey)", "assign a material")
            elif any(m is None for m in mats):
                iss.add("warn", "MAT_EMPTY_SLOT", ob.name, "empty material slot", "fill or remove slot")
            if ob.type == "MESH" and not ob.data.uv_layers and any(_material_uses_uv_images(m) for m in mats):
                iss.add("error", "MAT_IMAGE_NO_UV", ob.name, "image texture uses UVs but mesh has none",
                        "bkit.mesh.box_uv(ob) / smart_uv(ob), or use Object/Generated coordinates")
        neg = ob.matrix_world.to_3x3().determinant() < 0
        if neg:
            iss.add("warn", "XFORM_NEGATIVE_SCALE", ob.name, "negative scale flips normals/booleans",
                    "apply scale (bkit.mesh.apply_transform) and recalc normals")
        if any(abs(s - 1) > 1e-4 for s in ob.scale) and ob.type == "MESH":
            sens = [m.type for m in ob.modifiers if m.type in SCALE_SENSITIVE]
            sev = "warn" if sens else "info"
            iss.add(sev, "XFORM_UNAPPLIED_SCALE", ob.name, "scale %s%s" % (
                [round(s, 3) for s in ob.scale], (" with scale-sensitive modifiers %s" % sens) if sens else ""),
                "bkit.mesh.apply_transform(ob)")
        t = tri["own"].get(ob.name, 0)  # unique geometry; instanced copies count toward the scene total
        if t > per_max:
            iss.add("warn", "BUDGET_OBJECT", ob.name, "%d tris > %s budget %d" % (t, tier, per_max),
                    "lower subdiv levels/resolution, decimate, or instance repeated parts")
        if health and ob.type == "MESH":
            h = I.mesh_health(ob)
            if "skipped" in h:
                continue
            if h["multi_face_edges"]:
                iss.add("warn", "GEO_NONMANIFOLD", ob.name, "%d edges shared by >2 faces" % h["multi_face_edges"],
                        "remove internal faces / merge by distance")
            if h["inconsistent_normal_edges"]:
                iss.add("warn", "GEO_NORMALS_INCONSISTENT", ob.name,
                        "%d edges with flipped neighbour faces" % h["inconsistent_normal_edges"],
                        "bkit.mesh.recalc_normals(ob)")
            if h["inverted"]:
                iss.add("error", "GEO_NORMALS_INVERTED", ob.name, "closed mesh with inward normals",
                        "bkit.mesh.recalc_normals(ob)")
            if h["zero_area_faces"]:
                iss.add("warn", "GEO_DEGENERATE", ob.name, "%d zero-area faces" % h["zero_area_faces"],
                        "merge by distance / dissolve degenerate")
            if h["duplicate_verts"] > 0:
                iss.add("warn", "GEO_DOUBLES", ob.name, "%d duplicate vertices" % h["duplicate_verts"],
                        "bkit.mesh.merge_by_distance(ob)")
            if h["loose_verts"] or h["wire_edges"]:
                iss.add("info", "GEO_LOOSE", ob.name, "%d loose verts, %d wire edges" % (
                    h["loose_verts"], h["wire_edges"]), "delete loose geometry")
    if tri["total"] > scene_max:
        iss.add("warn", "BUDGET_SCENE", None, "%d tris > %s scene budget %d" % (tri["total"], tier, scene_max),
                "use instancing, LODs, Simplify, or decimate background assets")
    hits = None
    if intersect:
        hits = I.intersections()
        for p in hits["pairs"]:
            if p["kind"] == "penetration":
                iss.add("warn", "GEO_INTERSECT", "%s x %s" % (p["a"], p["b"]),
                        "%d intersecting face pairs, ~%.1f mm deep" % (p["penetrating_pairs"], p["depth_mm"]),
                        "move apart, parent into one assembly if intentional, or set obj['bk_allow_intersect']=True")
    return tri, hits


def _check_render(iss, sc, purpose):
    r = sc.render
    if r.engine == "CYCLES":
        c = sc.cycles
        if c.samples > 4096 and not c.use_adaptive_sampling:
            iss.add("warn", "RENDER_SAMPLES", None, "%d samples without adaptive sampling" % c.samples,
                    "enable adaptive sampling / lower samples + denoise")
        if not c.use_denoising and c.samples < 1024:
            iss.add("warn", "RENDER_NO_DENOISE", None, "low samples without denoising -> visible noise",
                    "scene.cycles.use_denoising = True")
    if r.resolution_percentage < 100 and purpose == "final":
        iss.add("warn", "RENDER_PERCENT", None, "resolution at %d%%" % r.resolution_percentage, "set 100%")
    if sc.view_settings.view_transform in ("Standard", "Raw") and purpose == "final":
        iss.add("info", "COLOR_STANDARD", None, "Standard view transform clips highlights harshly",
                "use AgX (or Filmic on 3.x) for photoreal work")
    if r.image_settings.file_format == "FFMPEG":
        rx = r.resolution_x * r.resolution_percentage // 100
        ry = r.resolution_y * r.resolution_percentage // 100
        if rx % 2 or ry % 2:
            iss.add("error", "RENDER_ODD_RES", None, "H.264 needs even resolution (%dx%d)" % (rx, ry), "")


def _check_org(iss, sc):
    for c in bpy.data.collections:
        if not c.objects and not c.children and c.users:
            iss.add("info", "ORG_EMPTY_COLLECTION", c.name, "empty collection", "remove it")
    orphans = sum(1 for attr in ("meshes", "materials", "images", "node_groups")
                  for b in getattr(bpy.data, attr) if b.users == 0 and not b.use_fake_user)
    if orphans:
        iss.add("info", "ORG_ORPHANS", None, "%d orphan datablocks" % orphans, "bkit.scene.purge_orphans()")


def run(tier="hero", health=True, intersect=True, purpose="final", subjects=None):
    sc = bpy.context.scene
    iss = Issues()
    subj = subjects or I.subjects(sc)
    _check_references(iss)
    cov = _check_camera(iss, sc, subj)
    light = _check_lighting(iss, sc)
    tri, hits = _check_objects(iss, sc, tier, health, intersect, subj)
    _check_render(iss, sc, purpose)
    _check_org(iss, sc)
    order = {"error": 0, "warn": 1, "info": 2}
    iss.sort(key=lambda i: order[i["sev"]])
    counts = {k: sum(1 for i in iss if i["sev"] == k) for k in order}
    score = max(0, round(100 - 15 * counts["error"] - 4 * counts["warn"] - 0.5 * counts["info"]))
    return {"score": score, "passed": counts["error"] == 0, "counts": counts, "tier": tier,
            "tris_total": tri["total"], "subjects": [o.name for o in subj],
            "subject_fill": cov["subject_fill"] if cov and "subject_fill" in cov else None,
            "lighting": light, "intersections": hits["pairs"] if hits else None, "issues": iss}
