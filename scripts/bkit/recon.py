"""Image-to-3D reconstruction helpers (Mode 1 procedural, Mode 2 reference-based, Mode 3 import).

WORLD CONVENTION (all functions): +Z up, the object FACES -Y.
  front image : seen from -Y   image x -> +X,  image down -> -Z
  side image  : seen from +X   image x -> +Y   (object's FRONT is on the image's LEFT; flip_side=True otherwise)
  back image  : seen from +Y   image x -> -X
  top image   : seen from +Z   image x -> +X,  image down -> -Y (front at the bottom of the image)

    from bkit import recon as RC
    ob, info = RC.voxel_from_views({"front": f, "side": s}, height_m=1.2)          # Mode 1 voxel
    ob, info = RC.visual_hull({"front": f, "side": s, "top": t}, height_m=0.3)     # Mode 1/2 carving
    RC.project_views(ob, {"front": f, "side": s})                                  # texture + inferred map
    RC.setup_references({"front": f, "side": s}, height_m=2.0)                     # Mode 2 GUI planes
    rep = RC.compare_views([ob], {"front": f, "side": s}, out_dir)                 # IoU + diff sheet
    rep = RC.compare_views([ob], views, out_dir, ref_m_per_px=0.0192)              # ... at TRUE scale
    ob, info = RC.inflate_from_image(f, height_m=1.0)                              # 1 view, no AI
    ob = RC.import_mesh("triposr.glb", height_m=0.5)                               # Mode 3 result
    RC.align_to_reference(ob, {"front": f}, out_dir)                               # 24 orientations
    reg = RC.register_view([ob], f); x, z = reg["to_world"](px, py)                # image -> mesh
    img, mpp = RC.render_colour([ob], "front", path, 512, "TEXTURE", return_scale=True)
Every builder returns info with what was VISIBLE vs INFERRED - report it, never hide it.
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import camera as _cam
from . import compat
from . import imageref as IR
from . import materials as _mat
from . import mesh as _mesh
from . import scene as _scene

VIEWS = {  # name: (azimuth, elevation) in bkit camera convention
    "front": (0.0, 0.0), "back": (180.0, 0.0), "side": (90.0, 0.0), "right": (90.0, 0.0),
    "left": (-90.0, 0.0), "top": (0.0, 90.0),
}


# --------------------------------------------------------------------------- loading views
def _view(path, flip=False, tol=0.12):
    img = IR.load(path)
    m = IR.foreground_mask(img, tol)
    if flip:
        img, m = img[:, ::-1].copy(), m[:, ::-1].copy()
    b = IR.bbox(m)
    if b is None:
        raise ValueError("no foreground in %s" % path)
    return {"path": os.path.abspath(path), "img": img, "mask": m, "bbox": b,
            "w": b[2] - b[0], "h": b[3] - b[1], "grid": IR.pixel_grid(img, m)}


def load_views(views, flip_side=False):
    out = {}
    for k, p in views.items():
        if p:
            out[k] = _view(p, flip=(flip_side and k in ("side", "right")))
    if "right" in out and "side" not in out:
        out["side"] = out.pop("right")
    return out


# --------------------------------------------------------------------------- palette material
def _palette_material(name, colors_srgb):
    """Tiny palette texture (one texel per colour, packed into the .blend) + Closest sampling.
    Engine-friendly: every glTF/FBX consumer understands an image texture + UVs."""
    n = len(colors_srgb)
    w = max(1, int(math.ceil(math.sqrt(n))))
    h = int(math.ceil(n / w))
    px = np.ones((h, w, 4), np.float32)
    for i, c in enumerate(colors_srgb):
        px[i // w, i % w, :3] = c
    img = bpy.data.images.new(name + "_palette", w, h, alpha=False)
    img.pixels.foreach_set(px.ravel())          # row 0 = bottom in Blender; UVs below follow that
    img.pack()
    m = _mat.new_material(name, reuse=False)
    nt = _mat.Nodes(m.node_tree)
    tex = nt.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"
    nt.link(tex, "Color", nt.bsdf, "Base Color")
    compat.set_input(nt.bsdf, "Roughness", 0.8)
    nt.layout()
    m.diffuse_color = tuple(np.mean(colors_srgb, axis=0)) + (1.0,) if n else (0.8, 0.8, 0.8, 1)

    def uv_of(i):
        return ((i % w + 0.5) / w, (i // w + 0.5) / h)
    return m, uv_of


def _srgb_to_linear(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# --------------------------------------------------------------------------- Mode 1: voxels
def voxel_from_views(views, height_m=1.0, flip_side=False, depth_cells=None, name="GEO_Voxel",
                     coll="Reconstruction", grid=None):
    """Voxel model from pixel-art (or flat) views: front (required), side, top, back.

    Grid = the front image's native pixel grid (auto-detected) or `grid=(cols, rows)`.
    Occupancy = front silhouette AND side silhouette AND top silhouette (visual hull at pixel
    resolution). Missing side -> constant depth `depth_cells` (INFERRED). Face colours come from
    the view that sees them; faces no image sees (back, left, bottom, ...) reuse the nearest view's
    colour and are flagged inferred (face attribute 'bk_inferred').
    """
    V = load_views(views, flip_side)
    if "front" not in V:
        raise ValueError("voxel_from_views needs a front view")
    F = V["front"]
    cols, rows = grid or ((F["grid"]["cols"], F["grid"]["rows"]) if F["grid"] else (None, None))
    if cols is None:
        rows = 32
        cols = max(1, int(round(rows * F["w"] / F["h"])))
    fcol, fmask = IR.sample_grid(F["img"], F["mask"], cols, rows, F["bbox"])
    inferred_views = []
    if "side" in V:
        S = V["side"]
        d = (S["grid"]["cols"] if S["grid"] else int(round(rows * S["w"] / S["h"])))
        scol, smask = IR.sample_grid(S["img"], S["mask"], d, rows, S["bbox"])
    else:
        d = depth_cells or max(1, cols // 2)
        scol, smask = None, np.repeat(fmask.any(axis=1)[:, None], d, axis=1)
        inferred_views.append("side (constant depth %d)" % d)
    if "top" in V:
        T = V["top"]
        tcol, tmask = IR.sample_grid(T["img"], T["mask"], cols, d, T["bbox"])
    else:
        tcol, tmask = None, np.ones((d, cols), bool)
    bcol = None
    if "back" in V:
        B = V["back"]
        bcol, _ = IR.sample_grid(B["img"], B["mask"], cols, rows, B["bbox"])
        bcol = bcol[:, ::-1]  # back image x runs -X
    # occupancy occ[x, y, z]: x = front column, y = 0 at the FRONT, z = 0 at the bottom
    occ = np.zeros((cols, d, rows), bool)
    for z in range(rows):
        r = rows - 1 - z
        occ[:, :, z] = fmask[r][:, None] & smask[r][None, :] & tmask[::-1].T
    s = height_m / rows
    ox, oy = -cols * s / 2, -d * s / 2

    def face_color(x, y, z, axis, sign):
        r = rows - 1 - z
        if axis == 1 and sign < 0:
            return fcol[r, x], False
        if axis == 1 and sign > 0:
            return (bcol[r, x], False) if bcol is not None else (fcol[r, x], True)
        if axis == 0:
            if scol is not None:
                return scol[r, y], sign < 0   # side image is the +X view; -X is mirrored (inferred)
            return fcol[r, x], True
        if sign > 0:
            return (tcol[d - 1 - y, x], False) if tcol is not None else (fcol[r, x], True)
        return fcol[r, x], True

    verts, vidx, faces, fcols, finf = [], {}, [], [], []

    def V_(p):
        if p not in vidx:
            vidx[p] = len(verts)
            verts.append((ox + p[0] * s, oy + p[1] * s, p[2] * s))
        return vidx[p]
    quads = {  # axis, sign -> corner offsets (CCW seen from outside)
        (0, -1): [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)], (0, 1): [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
        (1, -1): [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], (1, 1): [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],
        (2, -1): [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)], (2, 1): [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
    }
    pad = np.pad(occ, 1)
    for (x, y, z) in zip(*np.nonzero(occ)):
        for (axis, sign), corners in quads.items():
            n = [x + 1, y + 1, z + 1]
            n[axis] += sign
            if pad[n[0], n[1], n[2]]:
                continue
            faces.append([V_((x + cx, y + cy, z + cz)) for cx, cy, cz in corners])
            c, inf = face_color(x, y, z, axis, sign)
            fcols.append(tuple(np.round(np.asarray(c[:3]) * 255).astype(int)))
            finf.append(inf)
    if not faces:
        raise ValueError("empty voxel model - check masks / grid")
    uniq = sorted(set(fcols))
    ob = _mesh.from_pydata(name, verts, faces, coll=coll)
    mat, uv_of = _palette_material("MAT_" + name.replace("GEO_", "") + "Palette", [np.array(c) / 255.0 for c in uniq])
    _mat.assign(ob, mat)
    me = ob.data
    uvl = me.uv_layers.new(name="UVMap")
    lookup = {c: i for i, c in enumerate(uniq)}
    uvs = np.empty((len(me.loops), 2), np.float32)
    for poly, c in zip(me.polygons, fcols):
        u = uv_of(lookup[c])
        for li in poly.loop_indices:
            uvs[li] = u
    uvl.data.foreach_set("uv", uvs.ravel())
    attr = me.attributes.new("bk_inferred", "FLOAT", "FACE")
    attr.data.foreach_set("value", np.array(finf, np.float32))
    col = me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
    lin = np.array([list(_srgb_to_linear(np.array(fcols[p.index]) / 255.0)) + [1.0]
                    for p in me.polygons for _ in p.loop_indices], np.float32)
    col.data.foreach_set("color", lin.ravel())
    compat.shade_flat(ob)
    info = {"grid": [cols, d, rows], "voxel_size_m": round(s, 4), "voxels": int(occ.sum()),
            "faces": len(faces), "palette_colors": len(uniq), "views_used": sorted(V),
            "inferred_views": inferred_views,
            "inferred_face_fraction": round(float(np.mean(finf)), 3)}
    return ob, info


# --------------------------------------------------------------------------- Mode 1/2: visual hull
def visual_hull(views, height_m=1.0, res=96, flip_side=False, name="GEO_Hull", coll="Reconstruction",
                smooth=True, depth_ratio=None):
    """Silhouette carving: occupancy = front AND side (AND top) silhouettes, then a smooth
    isosurface (Points to Volume -> Volume to Mesh). Exact where views agree; concavities no view
    sees (e.g. a bowl's inside) are filled - that is a limit of silhouettes, report it.
    Without a side view the depth is `depth_ratio` x width (INFERRED)."""
    V = load_views(views, flip_side)
    F = V["front"]
    rows = res
    cols = max(2, int(round(res * F["w"] / F["h"])))
    _, fm = IR.sample_grid(F["img"], F["mask"], cols, rows, F["bbox"])
    inferred = []
    if "side" in V:
        S = V["side"]
        d = max(2, int(round(res * S["w"] / S["h"])))
        _, sm = IR.sample_grid(S["img"], S["mask"], d, rows, S["bbox"])
    else:
        d = max(2, int(round(cols * (depth_ratio or 0.6))))
        sm = np.repeat(fm.any(axis=1)[:, None], d, axis=1)
        inferred.append("depth (no side view): %.2f x width" % (depth_ratio or 0.6))
    if "top" in V:
        T = V["top"]
        _, tm = IR.sample_grid(T["img"], T["mask"], cols, d, T["bbox"])
    else:
        tm = np.ones((d, cols), bool)
    occ = np.zeros((cols, d, rows), bool)
    for z in range(rows):
        r = rows - 1 - z
        occ[:, :, z] = fm[r][:, None] & sm[r][None, :] & tm[::-1].T
    s = height_m / rows
    pts = (np.argwhere(occ) + 0.5) * s - np.array([cols * s / 2, d * s / 2, 0])
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(pts))
    me.vertices.foreach_set("co", pts.astype(np.float32).ravel())
    ob = _scene.add_object(name, me, coll)
    if smooth:
        from . import geonodes as G
        g = G.GN("GN_" + name.replace("GEO_", "") + "Iso")
        geo = g.geometry_io()
        p = g.node("GeometryNodeMeshToPoints", {"Mesh": geo})
        vol = g.node("GeometryNodePointsToVolume", {"Points": p.outputs[0], "Radius": s * 0.85, "Density": 1.0})
        compat.set_enum(vol, "resolution_mode", ["VOXEL_SIZE"])
        g.set(vol, "Voxel Size", s * 0.5)
        vm = g.node("GeometryNodeVolumeToMesh", {"Volume": vol.outputs[0], "Threshold": 0.5})
        compat.set_enum(vm, "resolution_mode", ["GRID"])
        sh = g.node("GeometryNodeSetShadeSmooth", {"Geometry": vm.outputs[0]})
        g.finish(sh.outputs[0])
        g.attach(ob)
        ob = _mesh.convert_to_mesh(ob)
    compat.shade_smooth(ob)
    return ob, {"grid": [cols, d, rows], "cell_m": round(s, 4), "occupied": int(occ.sum()),
                "views_used": sorted(V), "inferred": inferred}


# --------------------------------------------------------------------------- texturing
def project_views(ob, views, flip_side=False, size=1024, name=None, infer="mirror"):
    """Texture `ob` from its reference images: every face takes the view its normal points to
    (front/back/side/top), all views packed in one atlas image (engine-friendly). Faces whose
    facing view was NOT supplied are flagged inferred (`bk_inferred`) and get either
    infer="mirror": the nearest available view (back <- front, left <- side) - right for
    symmetric subjects (characters, voxel sprites), or
    infer="plain": the dominant colour of the front view - conservative, invents no screens,
    labels or decals on faces nobody drew (devices, vehicles, products).
    Assumes the object's world bounds correspond to the views' silhouette bounds (true for
    visual_hull/voxel output and for models built over setup_references)."""
    V = load_views(views, flip_side)
    keys = [k for k in ("front", "side", "back", "top") if k in V]
    tiles = []
    for k in keys:
        b = V[k]["bbox"]
        tiles.append(IR.crop(V[k]["img"], b)[..., :3])
    th = max(t.shape[0] for t in tiles)
    tiles = [IR.resample_img(t, max(1, int(t.shape[1] * th / t.shape[0])), th) for t in tiles]
    if infer == "plain":
        dom = IR.palette(V["front"]["img"], V["front"]["mask"], k=6)[0]["rgb"]
        tiles.append(np.full((th, max(4, th // 16), 3), dom, np.float32))
        keys = keys + ["_plain"]
    W = sum(t.shape[1] for t in tiles)
    atlas = np.ones((th, W, 3), np.float32)
    regions, x = {}, 0
    for k, t in zip(keys, tiles):
        atlas[:, x:x + t.shape[1]] = t
        regions[k] = (x / W, t.shape[1] / W)
        x += t.shape[1]
    sc = min(1.0, size / max(W, th))
    if sc < 1.0:
        atlas = IR.resample_img(atlas, int(W * sc), int(th * sc))
    nm = name or ob.name.replace("GEO_", "")
    img = bpy.data.images.new(nm + "_atlas", atlas.shape[1], atlas.shape[0], alpha=False)
    img.pixels.foreach_set(np.concatenate([atlas[::-1], np.ones(atlas.shape[:2] + (1,), np.float32)[::-1]], 2).ravel())
    img.pack()
    _scene.refresh()
    mw = ob.matrix_world
    me = ob.data
    vs = [mw @ v.co for v in me.vertices]
    mn = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    mx = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    size_v = mx - mn
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers.active
    nrm = mw.to_3x3()
    inferred = np.zeros(len(me.polygons), np.float32)
    area_total = area_inf = 0.0
    for p in me.polygons:
        n = (nrm @ p.normal).normalized()
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:
            want = "front" if n.y < 0 else "back"
        elif ax == 0:
            want = "side" if n.x > 0 else "left"
        else:
            want = "top" if n.z > 0 else "bottom"
        use, inf = want, False
        if use not in V or use in ("left", "bottom"):
            inf = True
            use = {"back": "front", "left": "side", "bottom": "front"}.get(want, "front")
            if use not in V:
                use = "front"
            if want == "top" and "top" not in V:
                use = "front"
        if inf and infer == "plain":
            u0, uw = regions["_plain"]
            for li in p.loop_indices:
                uvl.data[li].uv = (u0 + uw / 2, 0.5)
            inferred[p.index] = 1.0
            area_total += p.area
            area_inf += p.area
            continue
        u0, uw = regions[use]
        for li in p.loop_indices:
            co = mw @ me.vertices[me.loops[li].vertex_index].co
            if use == "front":
                u, v = (co.x - mn.x) / size_v.x, (co.z - mn.z) / size_v.z
            elif use == "back":
                u, v = (mx.x - co.x) / size_v.x, (co.z - mn.z) / size_v.z
            elif use == "side":
                u, v = (co.y - mn.y) / size_v.y, (co.z - mn.z) / size_v.z
            else:  # top: image x -> +X, image up -> +Y
                u, v = (co.x - mn.x) / size_v.x, (co.y - mn.y) / size_v.y
            uvl.data[li].uv = (u0 + min(max(u, 0), 1) * uw, min(max(v, 0), 1))
        inferred[p.index] = 1.0 if inf else 0.0
        area_total += p.area
        area_inf += p.area if inf else 0.0
    attr = me.attributes.get("bk_inferred") or me.attributes.new("bk_inferred", "FLOAT", "FACE")
    attr.data.foreach_set("value", inferred)
    m = _mat.new_material("MAT_" + nm + "_Projected", reuse=False)
    nt = _mat.Nodes(m.node_tree)
    tex = nt.new("ShaderNodeTexImage")
    tex.image = img
    nt.link(tex, "Color", nt.bsdf, "Base Color")
    compat.set_input(nt.bsdf, "Roughness", 0.7)
    nt.layout()
    me.materials.clear()
    me.materials.append(m)
    return {"atlas": [img.size[0], img.size[1]], "views": keys,
            "inferred_area_fraction": round(area_inf / max(area_total, 1e-9), 3)}


# --------------------------------------------------------------------------- simple shapes from images
def lathe_from_image(path, height_m, segments=64, samples=64, wall=None, name="GEO_Lathe", coll="Reconstruction"):
    """Turned object (vase, bottle, column, chess piece) from ONE front image: radius per row =
    half the silhouette width. wall=metres for a hollow vessel (open top)."""
    V = _view(path)
    m = IR.crop(V["mask"], V["bbox"])
    prof = IR.row_profile(m, samples=samples)
    s = height_m / V["h"]
    pts = []
    for y, xl, xr in prof[::-1]:   # bottom -> top
        pts.append((max((xr - xl) * s / 2, 0.0005), (V["h"] - y) * s))
    pts[0] = (pts[0][0], 0.0)
    if wall:
        inner = [(max(r - wall, 0.0005), z) for r, z in pts[::-1] if z > wall]
        prof3d = [(0.0, 0.0)] + pts + inner + [(0.0, wall)]
    else:
        prof3d = [(0.0, 0.0)] + pts + [(0.0, pts[-1][1])]
    ob = _mesh.lathe(name, prof3d, segments=segments, coll=coll)
    return ob, {"rows_sampled": len(pts), "symmetry_lr": IR.symmetry(V["mask"]),
                "note": "assumes rotational symmetry about the silhouette centre"}


def extrude_from_image(path, height_m, depth, name="GEO_Extruded", coll="Reconstruction", simplify_px=1.5):
    """Flat object (sign, blade, emblem, cookie-cutter shape) from its outline: outer contour
    extruded by `depth` (metres), holes cut with booleans. Lies in the XZ plane facing -Y."""
    V = _view(path)
    loops = IR.contours(V["mask"], simplify_px)
    s = height_m / V["h"]
    x0, y0 = V["bbox"][0], V["bbox"][1]

    def to2d(L):
        return [((px - x0) * s - V["w"] * s / 2, (V["h"] - (py - y0)) * s) for px, py in L]
    outer = to2d(loops[0])
    if IR._area(loops[0]) > 0:  # make CCW in XY (x right, y up)
        outer = outer[::-1]
    ob = _mesh.extrude_polygon(name, outer, depth, coll=coll, center_z=True)
    for i, L in enumerate(loops[1:]):
        hole = to2d(L)
        if IR._area(L) < 0:
            hole = hole[::-1]
        cut = _mesh.extrude_polygon("CUT_%s_Hole%d" % (name, i), hole, depth * 2, center_z=True)
        _mesh.boolean(ob, cut)
    ob.rotation_euler.x = math.radians(90)  # XY outline -> XZ plane, extrusion along Y
    _mesh.apply_transform(ob)
    return ob, {"loops": len(loops), "holes": len(loops) - 1, "outer_points": len(outer)}


def inflate_from_image(path, height_m, thickness=0.8, res=128, back_ratio=1.0, name="GEO_Inflated",
                       coll="Reconstruction", texture=True, infer="plain", smooth_iters=6, remesh=True):
    """Organic body from ONE view WITHOUT AI - the Mode 2 single-image fallback (creatures,
    mascots, plush toys, blobby props) when Mode 3 is unavailable or refused by the hardware check.

    The silhouette is inflated like a balloon: half-depth at distance d from the outline follows
    a circle, sqrt(d (2 dmax - d)) * thickness (thickness=1 -> as deep as wide at the thickest
    point). Front and back surfaces meet at a knife-edge outline; remesh=True voxel-remeshes it
    into a clean closed manifold (collapse-decimating the raw knife edge folded it: 16 boundary +
    8 non-manifold edges in T5). texture=True then projects the image onto the front; the back and
    the whole depth are INFERRED (info + `bk_inferred`). Limits: no undercuts, no limbs pointing
    at the viewer, depth is a guess - say so when reporting.
    """
    V = _view(path)
    m = IR.crop(V["mask"], V["bbox"])
    hh = res
    ww = max(1, int(round(m.shape[1] * res / m.shape[0])))
    m = IR.resample_mask(m, ww, hh)
    m = IR.opening(m, 1) | (IR.erode(m, 1) & m)          # drop 1-cell whiskers / diagonal links
    d = np.zeros(m.shape, np.float32)
    cur = m.copy()
    while cur.any():
        d[cur] += 1.0
        cur = IR.erode(cur, 1)
    dmax = float(d.max())
    s = height_m / hh
    pad = np.pad(m, 1)
    dp = np.pad(d, 1)
    verts, front_idx, back_idx = [], {}, {}
    for i in range(hh + 1):
        for j in range(ww + 1):
            adj = pad[i:i + 2, j:j + 2]
            if not adj.any():
                continue
            x, z = (j - ww / 2) * s, (hh - i) * s
            if not adj.all():
                front_idx[i, j] = back_idx[i, j] = len(verts)
                verts.append((x, 0.0, z))
                continue
            dd = float(dp[i:i + 2, j:j + 2].mean()) - 0.5
            h = math.sqrt(max(0.0, dd * (2 * dmax - dd))) * s * thickness
            front_idx[i, j] = len(verts)
            verts.append((x, -h, z))
            back_idx[i, j] = len(verts)
            verts.append((x, h * back_ratio, z))
    faces = []
    for i in range(hh):
        for j in range(ww):
            if not m[i, j]:
                continue
            c = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]
            faces.append([front_idx[k] for k in c])
            faces.append([back_idx[k] for k in reversed(c)])
    ob = _mesh.from_pydata(name, verts, faces, coll=coll)
    _mesh.merge_by_distance(ob, 1e-7)
    _mesh.recalc_normals(ob)
    info = {"cells": int(m.sum()), "grid": [ww, hh], "max_half_depth_m": round(dmax * s * thickness, 4),
            "thickness": thickness, "inferred": ["all depth (balloon model)", "back surface"]}
    if smooth_iters:
        _mesh.modifier(ob, "SMOOTH", "Smooth", factor=0.5, iterations=smooth_iters)
        _mesh.apply_modifiers(ob)
    if remesh:
        _mesh.modifier(ob, "REMESH", "Remesh", mode="VOXEL", voxel_size=height_m / (1.5 * res))
        _mesh.apply_modifiers(ob)
    compat.shade_smooth(ob)
    if texture:
        info["projection"] = project_views(ob, {"front": path}, infer=infer)
    return ob, info


# --------------------------------------------------------------------------- Mode 2: reference planes
def setup_references(views, height_m, opacity=0.4, flip_side=False, coll="References", depth_m=None):
    """Image empties aligned to the world convention and scaled to real size (GUI modelling guides
    and documentation of the setup). The object's silhouette bottom sits at z=0, centred on X/Y."""
    V = load_views(views, flip_side)
    s = height_m / V["front"]["h"]
    depth_m = depth_m or (V["side"]["w"] * s if "side" in V else height_m)
    out = {}
    rot = {"front": (math.radians(90), 0, 0), "back": (math.radians(90), 0, math.radians(180)),
           "side": (math.radians(90), 0, math.radians(90)), "top": (0, 0, 0)}
    off = {"front": (0, depth_m, 0), "back": (0, -depth_m, 0), "side": (-depth_m, 0, 0), "top": (0, 0, -0.01)}
    for k, v in V.items():
        if k not in rot:
            continue
        img = bpy.data.images.load(v["path"], check_existing=True)
        e = _scene.empty("REF_" + k.title(), coll)
        e.empty_display_type = "IMAGE"
        e.data = img
        H, W = v["img"].shape[:2]
        e.empty_display_size = max(W, H) * s
        cx, cy = (v["bbox"][0] + v["bbox"][2]) / 2, (v["bbox"][1] + v["bbox"][3]) / 2
        # image centre -> bbox centre offset, in metres within the image plane
        dx, dz = (W / 2 - cx) * s, (cy - H / 2) * s
        e.empty_image_offset = (-0.5, -0.5)
        e.color[3] = opacity
        compat.try_set(e, "use_empty_image_alpha", True)
        compat.try_set(e, "show_empty_image_only_axis_aligned", True)
        e.rotation_euler = rot[k]
        loc = Vector(off[k])
        plane_x = Vector((1, 0, 0)) if k in ("front", "top") else Vector((-1, 0, 0)) if k == "back" else Vector((0, 1, 0))
        up = Vector((0, 0, 1)) if k != "top" else Vector((0, 1, 0))
        bottom = Vector((0, 0, (v["h"] * s) / 2)) if k != "top" else Vector((0, 0, 0))
        e.location = loc + plane_x * dx + up * dz + bottom
        out[k] = e.name
    return {"empties": out, "px_to_m": s}


def px_to_world(view, px, py, views_info, height_m):
    """Map a pixel (top-down) in a reference view to world coordinates on that view's plane
    (two axes; the third is unknown from one view). Use with imageref.segments boxes."""
    v = views_info[view]
    s = height_m / views_info["front"]["h"]
    u = (px - (v["bbox"][0] + v["bbox"][2]) / 2) * s
    z = (v["bbox"][3] - py) * s
    if view == "front":
        return {"x": u, "z": z}
    if view == "back":
        return {"x": -u, "z": z}
    if view == "side":
        return {"y": u, "z": z}
    return {"x": u, "y": -(py - (v["bbox"][1] + v["bbox"][3]) / 2) * s}


# --------------------------------------------------------------------------- comparison
def render_silhouette(objs, view, path, res=512, return_scale=False):
    """Orthographic alpha silhouette of objs from a named view (Workbench, temporary camera).
    return_scale=True -> (mask, metres_per_pixel)."""
    img, mpp = _render_ortho(objs, view, path, res)
    mask = img[..., 3] > 0.5
    return (mask, mpp) if return_scale else mask


def render_colour(objs, view, path, res=256, color_type="VERTEX", return_scale=False):
    """Flat-lit orthographic colour render (Workbench VERTEX / TEXTURE / MATERIAL colours, Standard
    view transform) - for colour checks against a reference, or to find painted features (eyes,
    logos) ON the model. Returns RGBA float array (top-down); return_scale -> (img, m_per_px).
    The view is centred on the objects' world-bounds centre (camera.frame), so pixel (px, py) of
    a front render is world x = cx + (px + .5 - res/2) * mpp, z = cz - (py + .5 - res/2) * mpp."""
    img, mpp = _render_ortho(objs, view, path, res, color_type)
    return (img, mpp) if return_scale else img


def _render_ortho(objs, view, path, res, color_type="SINGLE"):
    from .preview import _Snapshot
    sc = bpy.context.scene
    r = sc.render
    snap = _Snapshot()
    az, el = VIEWS[view]
    cam = _cam.add("bk_tmp_sil", lens=50, coll=None, target=None, active=False, ortho_scale=1.0)
    names = {o.name for o in objs}
    others = [o for o in sc.objects if o.type in ("MESH", "CURVE", "FONT", "SURFACE", "META") and o.name not in names
              and not o.hide_render]
    try:
        _cam.frame(cam, objs, margin=1.05, azimuth=az, elevation=el)
        snap.set(r, "engine", r.engine)
        compat.set_engine(sc, "WORKBENCH")
        for a, v in (("resolution_x", res), ("resolution_y", res), ("resolution_percentage", 100),
                     ("film_transparent", True), ("use_compositing", False), ("use_stamp", False),
                     ("filepath", os.path.abspath(path))):
            snap.set(r, a, v)
        snap.set(r.image_settings, "file_format", "PNG")
        snap.set(r.image_settings, "color_mode", "RGBA")
        snap.set(sc, "camera", cam)
        sh = sc.display.shading
        for a, v in (("light", "FLAT"), ("color_type", color_type), ("single_color", (1, 1, 1)),
                     ("show_cavity", False), ("show_object_outline", False), ("show_shadows", False)):
            snap.set(sh, a, v)
        if color_type != "SINGLE":
            snap.set(sc.view_settings, "view_transform", "Standard")
            snap.set(sc.view_settings, "look", "None")
        for o in others:
            snap.set(o, "hide_render", True)
        bpy.ops.render.render(write_still=True)
        mpp = cam.data.ortho_scale / res
    finally:
        snap.restore()
        bpy.data.objects.remove(cam, do_unlink=True)
    return IR.load(path), mpp


def compare_views(objs, views, out_dir, flip_side=False, res=512, ref_m_per_px=None):
    """Silhouette similarity of the model vs every reference view + a diff sheet to LOOK at.
    Sheet rows: reference | model | diff (grey both, red model-only, blue reference-only).

    Default: scale-free shape IoU (right for AI meshes / unknown size). ref_m_per_px (float, or
    {view: float}) = the references' known drawing scale -> `iou` is measured at TRUE scale
    (bottom-centre aligned) and the scale-free value is kept as `iou_shape`."""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    V = load_views(views, flip_side)
    rep, tiles = {}, []
    for k, v in V.items():
        if k not in VIEWS:
            continue
        mm, mpp = render_silhouette(objs, k, os.path.join(out_dir, "sil_%s.png" % k), res, return_scale=True)
        if not mm.any():
            rep[k] = {"iou": 0.0, "error": "model not visible"}
            continue
        r = IR.silhouette_iou(mm, v["mask"])
        ref_mpp = ref_m_per_px.get(k) if isinstance(ref_m_per_px, dict) else ref_m_per_px
        if ref_mpp:
            shape = r
            r = IR.silhouette_iou(mm, v["mask"], metric=(mpp, ref_mpp))
            r["iou_shape"] = shape["iou"]
            r["mode"] = "metric"
        pa, pb = r.pop("_pa"), r.pop("_pb")
        rep[k] = r
        H = 256
        ref = IR.crop(v["img"], v["bbox"])[..., :3]
        ref = IR.resample_img(ref, max(1, int(ref.shape[1] * H / ref.shape[0])), H)
        model = np.repeat(pb[..., None] * 0 + pa[..., None], 3, axis=2).astype(np.float32) * 0.85 + 0.1
        diff = IR.overlay(pa, pb)
        row = [ref, model, diff]
        Wm = max(t.shape[1] for t in row)
        Hm = max(t.shape[0] for t in row)     # metric mode: the model may stand taller than the reference
        row = [np.pad(t, ((Hm - t.shape[0], 0), (0, Wm - t.shape[1]), (0, 0)), constant_values=0.1) for t in row]
        tiles.append(np.concatenate([np.concatenate(row, 1)], 0))
    if tiles:
        Wt = max(t.shape[1] for t in tiles)
        sheet = np.concatenate([np.pad(t, ((0, 6), (0, Wt - t.shape[1]), (0, 0)), constant_values=0.1) for t in tiles], 0)
        rep["sheet"] = IR.save(sheet, os.path.join(out_dir, "compare_sheet.png"))
    ious = [v["iou"] for k, v in rep.items() if isinstance(v, dict) and "iou" in v]
    rep["mean_iou"] = round(float(np.mean(ious)), 4) if ious else 0.0
    return rep


def register_view(objs, view_path, view="front", res=384, core=0.06, out_dir=None):
    """Register a reference image onto the model's silhouette in that view (2-D similarity:
    uniform scale + offset), so features MEASURED in the image (eyes, logos, buttons, decals) can
    be placed on ANY mesh - AI output, hull, inflated body - by ray-casting at the mapped point.

    Uses centroid + area of the CORE silhouettes: parts thinner than 2*core*height (ears, tails,
    antennas, fingers) are removed by a morphological opening first - they are where AI meshes and
    drawings disagree most, and they skew bounding boxes (found in T5: eyes placed via bbox
    mapping landed beside the painted eyes). Returns {"to_world": f(px, py) -> (u, v) on the
    view plane (front: x,z / side: y,z / top: x,y), "m_per_ref_px", "core_iou"}.
    """
    V = load_views({view: view_path})[view]
    path = os.path.join(out_dir or bpy.app.tempdir, "_register_%s.png" % view)
    mm, mpp = render_silhouette(objs, view, path, res, return_scale=True)
    mn, mx, size, c = _mesh.world_bounds(objs)
    cu, cv = {"front": (c.x, c.z), "side": (c.y, c.z), "right": (c.y, c.z), "top": (c.x, c.y)}[view]

    def core_stats(m):
        b = IR.bbox(m)
        r = max(1, int(core * (b[3] - b[1])))
        k = IR.opening(m, r)
        k = k if k.sum() > 0.3 * m.sum() else m
        ys, xs = np.nonzero(k)
        return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5, float(len(xs)), k
    mx_, my_, ma, km = core_stats(mm)
    rx_, ry_, ra, kr = core_stats(V["mask"])
    s = mpp * math.sqrt(ma / ra)
    Cu, Cv = cu + (mx_ - res / 2) * mpp, cv - (my_ - res / 2) * mpp

    def to_world(px, py):
        return Cu + (px - rx_) * s, Cv - (py - ry_) * s
    if not out_dir and os.path.exists(path):
        os.remove(path)
    return {"to_world": to_world, "m_per_ref_px": s, "model_core_centre": [round(Cu, 4), round(Cv, 4)],
            "core_area_ratio": round(ma * mpp * mpp / (ra * s * s), 4)}


# --------------------------------------------------------------------------- Mode 3: import AI output
def import_mesh(path, name="GEO_AIRecon", height_m=None, coll="Reconstruction", rotate_deg=(0, 0, 0)):
    """Import an AI reconstruction (GLB/GLTF/OBJ/PLY), join parts, apply transforms, recalc normals,
    put the origin at the bottom centre, scale to `height_m`, and show vertex colours via a
    Colour Attribute material (bake it for engines with gameprep.bake_materials)."""
    path = os.path.abspath(path)
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    else:
        raise ValueError("unsupported mesh format " + ext)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh imported from " + path)
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    _scene.refresh()
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    ob = _mesh.join(meshes, name) if len(meshes) > 1 else meshes[0]
    ob.name = name
    _scene.move_to(ob, coll)
    ob.rotation_euler = [math.radians(a) for a in rotate_deg] if any(rotate_deg) else ob.rotation_euler
    _scene.refresh()
    _mesh.apply_transform(ob, location=True, rotation=True, scale=True)
    _mesh.merge_by_distance(ob, 1e-6)
    _mesh.recalc_normals(ob)
    _mesh.set_origin(ob, "BOUNDS_BOTTOM")
    ob.location = (0, 0, 0)
    if height_m:
        f = height_m / max(ob.dimensions.z, 1e-9)
        ob.data.transform(Matrix.Diagonal((f, f, f, 1)))
        ob.data.update()
    compat.shade_smooth(ob)
    me = ob.data
    if me.color_attributes:
        ca = me.color_attributes[0]
        m = _mat.new_material("MAT_" + name.replace("GEO_", "") + "_VertexColour", reuse=False)
        nt = _mat.Nodes(m.node_tree)
        vc = nt.new("ShaderNodeVertexColor")
        vc.layer_name = ca.name
        nt.link(vc, "Color", nt.bsdf, "Base Color")
        compat.set_input(nt.bsdf, "Roughness", 0.7)
        nt.layout()
        me.materials.clear()
        me.materials.append(m)
    return ob


# --------------------------------------------------------------------------- Mode 1: components
def _hsv(rgb):
    import colorsys
    return colorsys.rgb_to_hsv(*[float(x) for x in rgb[:3]])


def _same_family(a, b, hue_tol=12.0):
    """Facet shades of one material belong together: same hue (chromatic) or both greyish with
    similar value. Hue tolerance in degrees."""
    ha, hb = _hsv(a), _hsv(b)
    if ha[1] < 0.18 and hb[1] < 0.18:
        return abs(ha[2] - hb[2]) < 0.25
    if (ha[1] < 0.18) != (hb[1] < 0.18):
        return False
    d = abs(ha[0] - hb[0]) * 360
    return min(d, 360 - d) < hue_tol


def _families(segs):
    fam, reps = [], []
    for s in segs:
        for i, r in enumerate(reps):
            if _same_family(s["rgb"], r):
                fam.append(i)
                break
        else:
            reps.append(s["rgb"])
            fam.append(len(reps) - 1)
    return fam, reps


def _parts(segs, fam, gap=3):
    """Union touching/overlapping boxes of the same colour family into parts."""
    boxes = [(fam[i], list(s["bbox_px"]), s["area_frac"]) for i, s in enumerate(segs)]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                fi, a, wa = boxes[i]
                fj, b, wb = boxes[j]
                if fi != fj:
                    continue
                if a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                    boxes[i] = (fi, [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])], wa + wb)
                    boxes.pop(j)
                    merged = True
                    break
            if merged:
                break
    return boxes


def _shape_stats(img, box, rep_rgbs, tol=0.12):
    """fill, roundness and taper of one part (its colour family inside its bbox).

    round: an ellipse leaves >= 3 bbox corners empty; a box with a facet/visor/decal keeps them
           (fill ratio alone is fooled by embedded details of another colour).
    taper: linear fit of row widths over the CENTRAL rows (15-85 %), so occluders at the ends
           (e.g. a shoulder ball over the top of an arm) do not fake a taper.
    """
    x0, y0, x1, y1 = box
    sub = img[y0:y1, x0:x1, :3]
    m = np.zeros(sub.shape[:2], bool)
    for c in rep_rgbs:
        m |= np.linalg.norm(sub - np.asarray(c), axis=2) < tol
    h, w = m.shape
    ch, cw = max(1, int(h * 0.15)), max(1, int(w * 0.15))
    corners = [m[:ch, :cw], m[:ch, -cw:], m[-ch:, :cw], m[-ch:, -cw:]]
    empty = sum(1 for c in corners if c.mean() < 0.3)
    rows = np.arange(int(h * 0.15), max(int(h * 0.85), int(h * 0.15) + 2))
    # row EXTENT (leftmost..rightmost pixel), not pixel count: interior decals/lights leave gaps
    ext = []
    for r in rows:
        xs = np.nonzero(m[r])[0]
        if len(xs):
            ext.append((r, xs.max() - xs.min() + 1))
    taper, inliers = 1.0, 0.0
    if len(ext) >= 6:
        R_ = np.array([e[0] for e in ext], float) / max(h - 1, 1)
        Wd = np.array([e[1] for e in ext], float)
        # Theil-Sen slope: median of pairwise slopes - robust to occluded rows (shoulder over an arm)
        idx = np.linspace(0, len(R_) - 1, min(len(R_), 40)).astype(int)
        sl = [(Wd[j] - Wd[i]) / (R_[j] - R_[i]) for a_, i in enumerate(idx) for j in idx[a_ + 1:] if R_[j] > R_[i]]
        b = float(np.median(sl)) if sl else 0.0
        a = float(np.median(Wd - b * R_))
        inliers = float((np.abs(Wd - (a + b * R_)) <= max(2.0, 0.03 * w)).mean())
        top, bot = a, a + b
        if inliers > 0.7 and bot > 1:
            taper = top / bot
    return {"fill": round(float(m.mean()), 3), "empty_corners": empty,
            "taper_top_over_bottom": round(float(taper), 3), "taper_fit_inliers": round(inliers, 3)}


def components_from_views(front, side, height_m, k=10, name="Part", coll="Reconstruction", lowpoly=True,
                          overrides=None, min_area_frac=0.002, proud=None):
    """Measured part decomposition of flat-coloured concept art (front + side views).

    Pass 1 (measure): each front part (one colour family, touching regions merged) is matched to
    the side part of the same family with the best height overlap; roundness (empty bbox corners)
    and taper (robust fit of row extents) are measured in BOTH views. Unmatched parts drawn on
    another part become thin panels on its front face (inferred depth). Ambiguous matches (side
    region much deeper than the part is wide, e.g. an arm drawn over the torso) are FLAGGED - after
    LOOKING at the images pass overrides={part_index: {"depth": m, "y": m}}.
    Pass 2 (build): parts contained in another part's front silhouette are pushed `proud` in front
    of it (no coplanar z-fighting), then boxes / tapered boxes / ellipsoids are created.
    Returns (objects, table).
    """
    overrides = overrides or {}
    proud = proud if proud is not None else 0.003 * height_m
    V = load_views({"front": front, "side": side})
    F, S = V["front"], V["side"]
    s = height_m / F["h"]
    sS_scale = height_m / S["h"]
    sF = IR.segments(F["img"], F["mask"], k=k, min_frac=min_area_frac)
    sS = IR.segments(S["img"], S["mask"], k=k, min_frac=min_area_frac)
    famF, repF = _families(sF)
    famS, repS = _families(sS)
    pF, pS = _parts(sF, famF), _parts(sS, famS)
    fam_map = {}
    for j, r in enumerate(repS):
        for i, q in enumerate(repF):
            if _same_family(r, q):
                fam_map[j] = i
    fx0, fy1 = (F["bbox"][0] + F["bbox"][2]) / 2, F["bbox"][3]
    sx0, sy1 = (S["bbox"][0] + S["bbox"][2]) / 2, S["bbox"][3]

    def side_cols(sfam):
        return [repS[sfam]] + [sg["rgb"] for sg, f in zip(sS, famS) if f == sfam]

    def area(b):
        return (b[2] - b[0]) * (b[3] - b[1])

    ordered = sorted(pF, key=lambda p: (p[1][1], p[1][0]))
    rows = []
    # ---------------- pass 1: measure
    for idx, (fam, box, _a) in enumerate(ordered):
        x0, y0, x1, y1 = box
        X0, X1 = (x0 - fx0) * s, (x1 - fx0) * s
        Z0, Z1 = (fy1 - y1) * s, (fy1 - y0) * s
        best, bov, bfam = None, 0.0, None
        for sfam, sbox, _ in pS:
            if fam_map.get(sfam) != fam:
                continue
            sz0, sz1 = (sy1 - sbox[3]) * sS_scale, (sy1 - sbox[1]) * sS_scale
            ov = max(0.0, min(Z1, sz1) - max(Z0, sz0)) / max(1e-6, min(Z1 - Z0, sz1 - sz0))
            if ov > bov:
                best, bov, bfam = sbox, ov, sfam
        container = None
        for fam2, box2, _ in pF:
            if box2 is not box and fam2 != fam and box2[0] <= x0 and box2[1] <= y0 and box2[2] >= x1 \
                    and box2[3] >= y1 and area(box2) > 1.5 * area(box):
                if container is None or area(box2) < area(container):
                    container = box2
        row = {"part": idx, "family_rgb": [round(c, 3) for c in repF[fam]], "front_px": box, "fam": fam,
               "x": [X0, X1], "z": [Z0, Z1], "container_px": container}
        st = _shape_stats(F["img"], box, [repF[fam]] + [sg["rgb"] for sg, f in zip(sF, famF) if f == fam])
        row.update(st)
        row["taper_x"] = st["taper_top_over_bottom"]
        row["taper_y"] = 1.0
        if best is not None and bov > 0.5:
            Y0, Y1 = (best[0] - sx0) * sS_scale, (best[2] - sx0) * sS_scale
            row.update(side_px=best, match=round(bov, 2))
            sst = _shape_stats(S["img"], best, side_cols(bfam))
            row["taper_y"] = sst["taper_top_over_bottom"]
            if (Y1 - Y0) > 2.2 * (X1 - X0) and (X1 - X0) < 0.25 * height_m:
                row["ambiguous"] = "side region much deeper than this part is wide (overlapping part in side view?)"
                row["taper_y"] = 1.0
        elif container is not None:
            Y0 = Y1 = None   # resolved after all parts are measured
            row["shape_note"] = "surface detail: no side counterpart -> thin panel on its container (INFERRED depth)"
        else:
            w = X1 - X0
            Y0, Y1 = -w / 2, w / 2
            row["inferred_depth"] = True
        ov_ = overrides.get(idx, {})
        if "depth" in ov_:
            yc = ov_.get("y", ((Y0 or 0) + (Y1 or 0)) / 2)
            Y0, Y1 = yc - ov_["depth"] / 2, yc + ov_["depth"] / 2
            row["override"] = ov_
            row["taper_y"] = 1.0
        row["y"] = [Y0, Y1]
        rows.append(row)
    # ---------------- resolve decals / proud details against their containers
    by_box = {tuple(r["front_px"]): r for r in rows}
    for r in rows:
        c = r["container_px"]
        if c is None:
            continue
        cont = by_box.get(tuple(c))
        if cont is None or cont["y"][0] is None:
            continue
        front_face = cont["y"][0]
        if r["y"][0] is None:  # unmatched decal: thin panel on the container's front
            t = max(0.004, 0.012 * height_m)
            r["y"] = [front_face - proud, front_face - proud + t]
        elif abs(r["y"][0] - front_face) < proud:  # coplanar with the container: push it proud
            r["y"][0] = front_face - proud
            r["proud"] = round(proud, 4)
    # ---------------- pass 2: build
    objs, table, mats = [], [], {}
    for r in rows:
        X0, X1 = r["x"]
        Y0, Y1 = r["y"] if r["y"][0] is not None else (-(X1 - X0) / 2, (X1 - X0) / 2)
        Z0, Z1 = r["z"]
        dims = (max(X1 - X0, 1e-3), max(Y1 - Y0, 1e-3), max(Z1 - Z0, 1e-3))
        nm = "GEO_%s_%02d" % (name, r["part"])
        if r["empty_corners"] >= 3 and 0.6 < r["fill"] < 0.9:
            ob = _mesh.sphere(nm, 0.5, segments=8 if lowpoly else 32, rings=6 if lowpoly else 16, coll=coll)
            ob.data.transform(Matrix.Diagonal((dims[0], dims[1], dims[2], 1)))
            ob.location = ((X0 + X1) / 2, (Y0 + Y1) / 2, Z0 + dims[2] / 2)
            r["shape"] = "ellipsoid"
        else:
            ob = _mesh.box(nm, dims, location=((X0 + X1) / 2, (Y0 + Y1) / 2, Z0), origin="BOTTOM", coll=coll)
            shaped = []
            for axis, t in ((0, r["taper_x"]), (1, r["taper_y"])):
                if abs(t - 1) <= 0.08:
                    continue
                # the bbox spans the WIDER end: shrink the narrower one (t = top / bottom)
                for v in ob.data.vertices:
                    top = v.co.z > dims[2] / 2
                    if t > 1 and not top:
                        v.co[axis] /= t
                    elif t < 1 and top:
                        v.co[axis] *= t
                shaped.append("%s %.2f" % ("x" if axis == 0 else "y", t))
            r["shape"] = ("tapered box (top/bottom %s)" % ", ".join(shaped)) if shaped else "box"
            ob.data.update()
        if lowpoly:
            compat.shade_flat(ob)
        key = tuple(round(c, 2) for c in repF[r["fam"]])
        if key not in mats:
            mats[key] = _mat.principled("MAT_%s_%d" % (name, len(mats)), tuple(_srgb_to_linear(repF[r["fam"]])),
                                        roughness=0.55)
        _mat.assign(ob, mats[key])
        objs.append(ob)
        out = {k: v for k, v in r.items() if k not in ("fam", "container_px")}
        out["x"] = [round(v, 4) for v in r["x"]]
        out["y"] = [round(v, 4) for v in (Y0, Y1)]
        out["z"] = [round(v, 4) for v in r["z"]]
        table.append(out)
    return objs, table


# --------------------------------------------------------------------------- Mode 3: orientation
def _orientations():
    from mathutils import Euler
    out, seen = [], set()
    for rx in (0, 90, 180, 270):
        for ry in (0, 90, 180, 270):
            for rz in (0, 90, 180, 270):
                m = Euler([math.radians(a) for a in (rx, ry, rz)]).to_matrix()
                key = tuple(round(x) for row in m for x in row)
                if key not in seen:
                    seen.add(key)
                    out.append(((rx, ry, rz), m))
    return out  # the 24 axis-aligned orientations


def align_to_reference(ob, views, out_dir, res=192, flip_side=False, resolve_by_colour=True):
    """Rotate an imported (e.g. AI-generated) mesh into the bkit convention by maximising silhouette
    IoU against the reference views over all 24 axis-aligned orientations; applies the best.
    A single front view cannot tell front from back (mirror-identical silhouettes) - check the
    colours/beauty render afterwards. Returns {rotation_deg, iou_by_view, ranking}."""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    V = load_views(views, flip_side)
    base = ob.data.copy()
    scores = []
    for rot, m in _orientations():
        tmp = base.copy()
        tmp.transform(m.to_4x4())
        old, ob.data = ob.data, tmp
        if old != base and old.users == 0:
            bpy.data.meshes.remove(old)
        _mesh.set_origin(ob, "BOUNDS_BOTTOM")
        ob.location = (0, 0, 0)
        _scene.refresh()
        per = {}
        for k, v in V.items():
            if k not in VIEWS:
                continue
            mm = render_silhouette([ob], k, os.path.join(out_dir, "_align_%s.png" % k), res)
            per[k] = IR.silhouette_iou(mm, v["mask"], 128)["iou"] if mm.any() else 0.0
        scores.append((sum(per.values()), rot, per, m))
    scores.sort(key=lambda t: -t[0])
    best = scores[0]
    colour = None
    if resolve_by_colour and "front" in V:
        # silhouettes cannot tell front from back (or mirrored poses) - near-ties are settled by
        # comparing flat colour renders with the reference (e.g. the face is on the front)
        ties = [sc_ for sc_ in scores if sc_[0] >= best[0] - 0.01 * len(V)][:4]
        if len(ties) > 1:
            ct = "VERTEX" if ob.data.color_attributes else "MATERIAL"
            ref = IR.crop(V["front"]["img"], V["front"]["bbox"])
            colour = []
            for sc_ in ties:
                tmp = base.copy()
                tmp.transform(sc_[3].to_4x4())
                old, ob.data = ob.data, tmp
                if old != base and old.users == 0:
                    bpy.data.meshes.remove(old)
                _mesh.set_origin(ob, "BOUNDS_BOTTOM")
                ob.location = (0, 0, 0)
                _scene.refresh()
                img = render_colour([ob], "front", os.path.join(out_dir, "_align_colour.png"), res, ct)
                mm = img[..., 3] > 0.5
                if not mm.any():
                    continue
                a_ = IR.resample_img(IR.crop(img, IR.bbox(mm)), 96, 96)
                b_ = IR.resample_img(ref, 96, 96)
                both = (a_[..., 3] > 0.5) & IR.resample_mask(IR.crop(V["front"]["mask"], V["front"]["bbox"]), 96, 96)
                err = float(np.abs(a_[..., :3][both] - b_[..., :3][both]).mean()) if both.any() else 1.0
                colour.append((err, sc_))
            if colour:
                colour.sort(key=lambda t: t[0])
                best = colour[0][1]
                colour = [(r[1], round(e, 4)) for e, r in colour]
    final = base.copy()
    final.transform(best[3].to_4x4())
    old, ob.data = ob.data, final
    if old.users == 0:
        bpy.data.meshes.remove(old)
    bpy.data.meshes.remove(base)
    _mesh.set_origin(ob, "BOUNDS_BOTTOM")
    ob.location = (0, 0, 0)
    for f in os.listdir(out_dir):
        if f.startswith("_align_"):
            os.remove(os.path.join(out_dir, f))
    return {"rotation_deg": best[1], "iou_by_view": best[2],
            "ranking": [(r, round(sc, 3)) for sc, r, _, _ in scores[:5]],
            "colour_tiebreak": colour}
