"""Mesh construction and modifier helpers (data API + bmesh; no viewport needed).

Principles:
* Dimensions live in mesh data, not object scale (scale stays 1 -> bevels/booleans behave).
* Modifier stacks stay live (non-destructive) until export; apply_modifiers() makes a copy-safe bake.
* Every builder returns the object; pass coll="Props" etc. to file it.

    from bkit import mesh as M
    body = M.box("GEO_Crate", (1, 1, 0.8), location=(0, 0, 0.4), coll="Props")
    M.bevel(body, 0.02, segments=3); M.weighted_normals(body)
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import compat
from . import scene as _scene


# --------------------------------------------------------------------------- creation
def from_bmesh(name, bm, coll=None, location=(0, 0, 0), rotation=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = _scene.add_object(name, me, coll, location, rotation)
    if smooth:
        compat.shade_smooth(ob)
    return ob


def from_pydata(name, verts, faces, edges=(), coll=None, location=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], list(edges), [tuple(f) for f in faces])
    me.validate(clean_customdata=False)
    me.update()
    ob = _scene.add_object(name, me, coll, location)
    if smooth:
        compat.shade_smooth(ob)
    return ob


def box(name, size=(1, 1, 1), location=(0, 0, 0), rotation=(0, 0, 0), coll=None, origin="CENTER"):
    """Box with real dimensions. origin: CENTER | BOTTOM (z min at object origin)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    sx, sy, sz = size
    off = 0.5 * sz if origin == "BOTTOM" else 0.0
    bmesh.ops.transform(bm, matrix=Matrix.Translation((0, 0, off)) @ Matrix.Diagonal((sx, sy, sz, 1)),
                        verts=bm.verts)
    return from_bmesh(name, bm, coll, location, rotation)


def cylinder(name, radius=0.5, depth=1.0, segments=32, location=(0, 0, 0), rotation=(0, 0, 0),
             coll=None, cap=True, radius_top=None, origin="CENTER", smooth=True):
    """Cylinder/cone along Z. radius_top != radius -> cone frustum."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=segments, radius1=radius,
                          radius2=radius if radius_top is None else radius_top, depth=depth,
                          calc_uvs=True)
    if origin == "BOTTOM":
        bmesh.ops.translate(bm, vec=(0, 0, depth / 2), verts=bm.verts)
    ob = from_bmesh(name, bm, coll, location, rotation)
    if smooth:
        compat.shade_smooth(ob, angle_deg=40)
    return ob


def sphere(name, radius=0.5, location=(0, 0, 0), coll=None, segments=48, rings=24, ico=0, smooth=True):
    """UV sphere (default) or icosphere when ico>0 (subdivision level)."""
    bm = bmesh.new()
    if ico:
        bmesh.ops.create_icosphere(bm, subdivisions=ico, radius=radius, calc_uvs=True)
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius, calc_uvs=True)
    ob = from_bmesh(name, bm, coll, location)
    if smooth:
        compat.shade_smooth(ob)
    return ob


def plane(name, size=(2, 2), location=(0, 0, 0), rotation=(0, 0, 0), coll=None, subdivisions=0):
    sx, sy = (size, size) if isinstance(size, (int, float)) else size
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=subdivisions + 1, y_segments=subdivisions + 1, size=0.5,
                          calc_uvs=True)
    bmesh.ops.scale(bm, vec=(sx, sy, 1), verts=bm.verts)
    return from_bmesh(name, bm, coll, location, rotation)


def torus(name, major=1.0, minor=0.25, major_segments=48, minor_segments=16, location=(0, 0, 0),
          rotation=(0, 0, 0), coll=None, arc=360.0, start_deg=0.0, smooth=True):
    """Torus in XY plane. arc<360 gives an open, capped partial torus starting at start_deg
    (0 = +X axis, counter-clockwise) - e.g. a mug handle."""
    closed = arc >= 359.999
    nu = major_segments if closed else major_segments + 1
    verts, faces = [], []
    for i in range(nu):
        a = math.radians(start_deg) + math.radians(arc) * i / major_segments
        ca, sa = math.cos(a), math.sin(a)
        for j in range(minor_segments):
            b = 2 * math.pi * j / minor_segments
            r = major + minor * math.cos(b)
            verts.append((r * ca, r * sa, minor * math.sin(b)))
    for i in range(major_segments):
        i2 = (i + 1) % nu
        for j in range(minor_segments):
            j2 = (j + 1) % minor_segments
            faces.append((i * minor_segments + j, i2 * minor_segments + j,
                          i2 * minor_segments + j2, i * minor_segments + j2))
    if not closed:  # cap both ends
        faces.append(tuple(reversed(range(minor_segments))))
        last = (nu - 1) * minor_segments
        faces.append(tuple(last + j for j in range(minor_segments)))
    ob = from_pydata(name, verts, faces, coll=coll, location=location, smooth=smooth)
    ob.rotation_euler = rotation
    recalc_normals(ob)
    return ob


def lathe(name, profile, segments=48, location=(0, 0, 0), coll=None, smooth=True, angle_deg=30.0):
    """Revolve a profile around Z. profile = [(radius, z), ...] ordered along the surface.

    Points with radius ~0 become poles. To get a solid with wall thickness, walk the
    outside bottom->top, then the inside top->bottom (e.g. mug, vase, bottle).
    angle_deg: profile corners sharper than this stay sharp. Do NOT smooth everything on
    thin-walled refractive objects: S06's glass rendered BLACK with full smoothing (normals
    interpolated across rim/base corners -> wrong refraction + total internal reflection).
    """
    verts, faces, rings = [], [], []
    for r, z in profile:
        if r < 1e-6:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
        else:
            ring = []
            for s in range(segments):
                a = 2 * math.pi * s / segments
                ring.append(len(verts))
                verts.append((r * math.cos(a), r * math.sin(a), z))
            rings.append(ring)
    for ra, rb in zip(rings, rings[1:]):
        if len(ra) == 1 and len(rb) == 1:
            continue
        if len(ra) == 1:
            for s in range(segments):
                faces.append((ra[0], rb[s], rb[(s + 1) % segments]))
        elif len(rb) == 1:
            for s in range(segments):
                faces.append((ra[s], ra[(s + 1) % segments], rb[0]))
        else:
            for s in range(segments):
                s2 = (s + 1) % segments
                faces.append((ra[s], ra[s2], rb[s2], rb[s]))
    ob = from_pydata(name, verts, faces, coll=coll, location=location)
    recalc_normals(ob)
    if smooth:
        compat.shade_smooth(ob, angle_deg=angle_deg)
    return ob


def extrude_polygon(name, points2d, depth, location=(0, 0, 0), rotation=(0, 0, 0), coll=None,
                    center_z=False):
    """Extrude a closed 2D outline (XY, counter-clockwise) along +Z by depth."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, 0.0)) for x, y in points2d]
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, depth), verts=top)
    if center_z:
        bmesh.ops.translate(bm, vec=(0, 0, -depth / 2), verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return from_bmesh(name, bm, coll, location, rotation)


def rounded_rect(w, h, r, seg=6):
    """2D outline (CCW) of a rounded rectangle centred on origin, for extrude_polygon."""
    r = min(r, w / 2, h / 2)
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    # Full-radius corners (stadium/circle) make neighbouring arcs share endpoints:
    # drop coincident points or bevels later collapse them into duplicate vertices.
    tol = 1e-6 * max(w, h)
    clean = []
    for p in pts:
        if not clean or math.dist(p, clean[-1]) > tol:
            clean.append(p)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) <= tol:
        clean.pop()
    return clean


def curve_tube(name, points, radius=0.05, coll=None, resolution=12, bevel_resolution=4,
               kind="BEZIER", closed=False, to_mesh=False):
    """Tube along points (cables, pipes, handles). kind: BEZIER (auto handles) | POLY."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.resolution_u = resolution
    cu.bevel_depth = radius
    cu.bevel_resolution = bevel_resolution
    cu.use_fill_caps = True
    if kind == "BEZIER":
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(points) - 1)
        for bp, p in zip(sp.bezier_points, points):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = "AUTO"
    else:
        sp = cu.splines.new("POLY")
        sp.points.add(len(points) - 1)
        for pt, p in zip(sp.points, points):
            pt.co = (p[0], p[1], p[2], 1.0)
    sp.use_cyclic_u = closed
    ob = _scene.add_object(name, cu, coll)
    if to_mesh:
        ob = convert_to_mesh(ob)
        merge_by_distance(ob, 1e-6)   # fill caps are not welded to the tube rings
        compat.shade_smooth(ob, angle_deg=50)
    return ob


def convert_to_mesh(ob):
    """Evaluated geometry of any object as a new mesh object (original removed)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
    name, mw, colls = ob.name, ob.matrix_world.copy(), list(ob.users_collection)
    mats = [s.material for s in ob.material_slots]
    bpy.data.objects.remove(ob, do_unlink=True)
    new = bpy.data.objects.new(name, me)
    new.matrix_world = mw
    for c in colls or [bpy.context.scene.collection]:
        c.objects.link(new)
    if not me.materials:
        for m in mats:
            me.materials.append(m)
    return new


def linked_copy(ob, name=None, location=None, rotation=None, scale=None, coll=None):
    """Instance sharing mesh data (memory-cheap). Modifiers are copied too."""
    new = ob.copy()
    new.name = name or ob.name
    if location is not None:
        new.location = location
    if rotation is not None:
        new.rotation_euler = rotation
    if scale is not None:
        new.scale = scale
    target = coll or (ob.users_collection[0] if ob.users_collection else bpy.context.scene.collection)
    if isinstance(target, str):
        target = _scene.collection(target)
    target.objects.link(new)
    return new


# --------------------------------------------------------------------------- modifiers
def modifier(ob, mtype, name=None, **props):
    """Add a modifier and set properties, with a clear error for unknown properties."""
    m = ob.modifiers.new(name or mtype.title(), mtype)
    for k, v in props.items():
        if not compat.has_prop(m, k):
            raise AttributeError("%s modifier has no property %r. Valid: %s" % (
                mtype, k, [p.identifier for p in m.bl_rna.properties if not p.is_readonly][:60]))
        setattr(m, k, v)
    return m


def bevel(ob, width=0.02, segments=3, angle=30, harden=True, profile=0.5, limit="ANGLE",
          clamp=True):
    """Edge bevel for believable highlights. Width in metres (scale must be applied)."""
    m = modifier(ob, "BEVEL", "Bevel", width=width, segments=segments, limit_method=limit,
                 profile=profile, use_clamp_overlap=clamp)
    if limit == "ANGLE":
        m.angle_limit = math.radians(angle)
    compat.try_set(m, "miter_outer", "MITER_ARC")
    if harden:
        compat.try_set(m, "harden_normals", True)
        compat.shade_smooth(ob)
    return m


def hard_surface_finish(ob, bevel_width=0.003, segments=3, angle=35, weld=True):
    """Standard finishing stack for boolean'ed hard-surface parts:
    [booleans...] -> Bevel (angle) -> Weld (safety net) -> WeightedNormal.

    Rule: bevel_width < 0.4 x the smallest feature (recess depth, slot width, wall),
    otherwise opposite bevels clamp into each other and leave doubles / zero-area faces.
    Verify with inspect.mesh_health(ob) - duplicate_verts and zero_area_faces must be 0.
    """
    b = bevel(ob, width=bevel_width, segments=segments, angle=angle)
    if weld:
        modifier(ob, "WELD", "Weld", merge_threshold=1e-5)
    weighted_normals(ob)
    return b


def weighted_normals(ob, keep_sharp=True, weight=50):
    """Put LAST in the stack. Fixes shading on flat-faced, bevelled hard-surface meshes."""
    compat.shade_smooth(ob)
    return modifier(ob, "WEIGHTED_NORMAL", "WeightedNormal", keep_sharp=keep_sharp, weight=weight,
                    mode="FACE_AREA")


def subsurf(ob, levels=2, render_levels=None, smooth=True):
    if smooth:
        compat.shade_smooth(ob)
    return modifier(ob, "SUBSURF", "Subdivision", levels=levels,
                    render_levels=levels if render_levels is None else render_levels)


def solidify(ob, thickness=0.02, offset=-1.0, even=True):
    return modifier(ob, "SOLIDIFY", "Solidify", thickness=thickness, offset=offset,
                    use_even_offset=even)


def mirror(ob, x=True, y=False, z=False, clip=True, bisect=False, about=None):
    m = modifier(ob, "MIRROR", "Mirror", use_clipping=clip)
    m.use_axis = (x, y, z)
    m.use_bisect_axis = (bisect and x, bisect and y, bisect and z)
    if about is not None:
        m.mirror_object = about
    return m


def array(ob, count=3, offset=(1.0, 0, 0), relative=True, merge=False, curve=None):
    m = modifier(ob, "ARRAY", "Array", count=count, use_relative_offset=relative,
                 use_constant_offset=not relative, use_merge_vertices=merge)
    if relative:
        m.relative_offset_displace = offset
    else:
        m.constant_offset_displace = offset
    if curve is not None:
        m.fit_type = "FIT_CURVE"
        m.curve = curve
    return m


def boolean(ob, cutter, operation="DIFFERENCE", solver="EXACT", hide_cutter=True):
    """Live boolean. The cutter is renamed CUT_*, moved to 'Cutters', hidden from render."""
    m = modifier(ob, "BOOLEAN", "Bool_" + cutter.name, operation=operation, object=cutter)
    compat.set_enum(m, "solver", [solver, "EXACT", "FAST"])
    if hide_cutter:
        if not cutter.name.startswith("CUT_"):
            cutter.name = "CUT_" + cutter.name.split("_", 1)[-1]
        cutter.display_type = "WIRE"
        cutter.hide_render = True
        _scene.move_to(cutter, "Cutters")
    return m


def move_modifier_last(ob, name):
    idx = ob.modifiers.find(name)
    if idx >= 0:
        ob.modifiers.move(idx, len(ob.modifiers) - 1)


def apply_modifiers(ob):
    """Bake the modifier stack into the mesh (destructive for this object only)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True,
                                         depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return ob


# --------------------------------------------------------------------------- transforms / topology
def apply_transform(ob, location=False, rotation=True, scale=True):
    """Bake rotation/scale (and optionally location) into mesh data without operators."""
    loc, rot, sca = ob.matrix_basis.decompose()
    m = Matrix.Identity(4)
    if location:
        m = Matrix.Translation(loc) @ m
    if rotation:
        m = m @ rot.to_matrix().to_4x4()
    if scale:
        m = m @ Matrix.Diagonal(sca.to_4d())
    if ob.type == "MESH":
        ob.data.transform(m)
        ob.data.update()
    elif ob.type == "CURVE":
        ob.data.transform(m)
    basis_loc = Vector((0, 0, 0)) if location else loc
    basis_rot = rot.to_matrix().to_4x4() if not rotation else Matrix.Identity(4)
    basis_sca = Matrix.Diagonal(sca.to_4d()) if not scale else Matrix.Identity(4)
    ob.matrix_basis = Matrix.Translation(basis_loc) @ basis_rot @ basis_sca
    return ob


def set_origin(ob, mode="BOUNDS_BOTTOM"):
    """Move the origin without moving the geometry. mode: BOUNDS_BOTTOM | BOUNDS_CENTER | (x,y,z) local."""
    co = [Vector(c) for c in ob.bound_box]
    mn = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
    mx = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
    if mode == "BOUNDS_BOTTOM":
        p = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    elif mode == "BOUNDS_CENTER":
        p = (mn + mx) / 2
    else:
        p = Vector(mode)
    ob.data.transform(Matrix.Translation(-p))
    ob.matrix_world = ob.matrix_world @ Matrix.Translation(p)
    return ob


def recalc_normals(ob, inside=False):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if inside:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def merge_by_distance(ob, dist=1e-4):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    removed = n0 - len(bm.verts)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return removed


def box_uv(ob, scale=1.0):
    """Box-project UVs per face by dominant normal axis (robust, no operators, world-scaled)."""
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        n = f.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        u_i, v_i = [(1, 2), (0, 2), (0, 1)][ax]
        for lp in f.loops:
            co = lp.vert.co
            lp[uv].uv = (co[u_i] * scale, co[v_i] * scale)
    bm.to_mesh(me)
    bm.free()


def smart_uv(ob, angle=66.0, margin=0.02):
    """Smart UV Project via operator (needs edit mode; works headless with an override)."""
    vl = bpy.context.view_layer
    prev = vl.objects.active
    _scene.select_only(ob)
    with compat.override(active_object=ob, object=ob, selected_objects=[ob],
                         selected_editable_objects=[ob]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin)
        bpy.ops.object.mode_set(mode="OBJECT")
    vl.objects.active = prev


def join(objs, name=None):
    """Join meshes into the first object (operator with context override)."""
    objs = list(objs)
    target = objs[0]
    with compat.override(active_object=target, selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    if name:
        target.name = name
    return target


# --------------------------------------------------------------------------- measurement
def world_bounds(objs, exact=False):
    """World AABB of objects (evaluated, incl. modifiers). Returns (min, max, size, center).

    Default uses the 8 local bound-box corners: fast but LOOSE for rotated objects (a rolling
    sphere's box corners reach sqrt(3)*r). exact=True uses the evaluated vertices - use it for
    contact/penetration checks (physics settling, 'is it below the floor').
    """
    objs = [objs] if hasattr(objs, "bound_box") else list(objs)
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for ob in objs:
        if ob.type not in {"MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES", "POINTCLOUD", "VOLUME"}:
            continue
        ev = ob.evaluated_get(dg)
        if exact:
            try:
                me = ev.to_mesh()
            except RuntimeError:
                me = None
            if me is not None and len(me.vertices):
                import numpy as np
                co = np.empty(len(me.vertices) * 3, dtype=np.float64)
                me.vertices.foreach_get("co", co)
                co = co.reshape(-1, 3)
                mw = np.array(ev.matrix_world)
                w = co @ mw[:3, :3].T + mw[:3, 3]
                ev.to_mesh_clear()
                pts += [Vector(w.min(axis=0)), Vector(w.max(axis=0))]
                continue
            ev.to_mesh_clear()
        pts += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    if not pts:
        z = Vector((0, 0, 0))
        return z, z, z, z
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx, mx - mn, (mn + mx) / 2


def drop_to(ob, z=0.0):
    mn, _, _, _ = world_bounds([ob])
    ob.location.z += z - mn.z
    return ob


def stats(ob, evaluated=True):
    """verts/faces/tris of the (evaluated) mesh."""
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            out = {"verts": len(me.vertices), "faces": len(me.polygons), "tris": len(me.loop_triangles)}
        finally:
            ev.to_mesh_clear()
        return out
    me = ob.data
    me.calc_loop_triangles()
    return {"verts": len(me.vertices), "faces": len(me.polygons), "tris": len(me.loop_triangles)}
