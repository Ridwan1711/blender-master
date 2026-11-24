"""Procedural, seedable stand-in assets for set dressing (real-world scale, base at z=0).

Each builder returns ONE mesh object (multi-material where needed) placed at the origin in
collection `coll` (default "Assets", which library() hides from render so the originals don't
show while their instances do).

    from bkit import assets as A
    lib = A.library()                                  # hidden 'Assets' collection
    trees = A.subcollection("Trees")                   # a scatter source: one child per variant
    for s in range(3): A.pine(seed=s, coll=trees)
"""
import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

from . import compat
from . import materials as _mat
from . import mesh as _mesh
from . import scene as _scene


def library(name="Assets"):
    """Collection for source assets; excluded from the view layer render."""
    coll = _scene.collection(name)
    coll.hide_render = True
    coll.hide_viewport = False
    return coll


def subcollection(name, parent="Assets"):
    lib = library(parent)
    c = _scene.collection(name, lib)
    return c


def _jitter(bm, amount, scale, seed, verts=None):
    off = Vector((seed * 13.1, seed * 7.7, seed * 3.3))
    for v in verts or bm.verts:
        p = v.co * scale + off
        v.co += Vector((noise.noise(p), noise.noise(p + Vector((5.2, 1.3, 2.7))),
                        noise.noise(p + Vector((9.1, 4.4, 7.3))))) * amount


def _mats(*mats):
    return list(mats)


_CACHE = {}


def _material(key, builder):
    m = bpy.data.materials.get(key)
    return m if m is not None else builder()


def rock(seed=0, size=1.0, flatten=0.65, detail=3, coll="Assets", name=None, material=None):
    rnd = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=detail, radius=0.5 * size)
    off = Vector((seed * 3.7, seed * 1.9, seed * 5.3))
    for v in bm.verts:
        p = v.co / size * 1.6 + off
        d = noise.fractal(p, 0.6, 2.0, 4) * 0.35 + noise.noise(p * 3.0) * 0.08
        v.co += v.co.normalized() * d * size * 0.5
    sx, sy = rnd.uniform(0.8, 1.3), rnd.uniform(0.8, 1.3)
    bmesh.ops.scale(bm, vec=(sx, sy, flatten), verts=bm.verts)
    zmin = min(v.co.z for v in bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, -zmin - 0.12 * size * flatten), verts=bm.verts)  # sink a bit
    ob = _mesh.from_bmesh(name or "GEO_Rock_%02d" % seed, bm, coll)
    compat.shade_smooth(ob, angle_deg=35)
    m = material or _material("MAT_Rock", lambda: _mat.concrete("MAT_Rock", _mat.hex_color("#6F6A62"),
                                                                roughness=0.8, scale=3.0))
    _mat.assign(ob, m)
    return ob


def pine(seed=0, height=6.0, coll="Assets", name=None):
    """Conifer: bark trunk + 4-5 jittered cone tiers. ~300-500 tris."""
    rnd = random.Random(seed)
    h = height * rnd.uniform(0.85, 1.15)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.016 * h, radius2=0.01 * h,
                          depth=0.32 * h, matrix=Matrix.Translation((0, 0, 0.16 * h)))
    trunk = set(bm.faces)  # BMFace.index is stale for new faces until index_update(): use sets
    tiers = rnd.randint(4, 5)
    for i in range(tiers):
        t = i / tiers
        base = 0.18 * h + t * 0.62 * h
        r = (0.24 - 0.17 * t) * h * rnd.uniform(0.9, 1.1)
        depth = 0.34 * h * (1 - 0.35 * t)
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r, radius2=0.0,
                                    depth=depth, matrix=Matrix.Translation((0, 0, base + depth / 2))
                                    @ Matrix.Rotation(rnd.uniform(0, 6.28), 4, "Z"))
        _jitter(bm, 0.05 * h, 0.9 / h * 6, seed * 10 + i, verts=res["verts"])
    for f in bm.faces:
        f.material_index = 0 if f in trunk else 1
    ob = _mesh.from_bmesh(name or "GEO_Pine_%02d" % seed, bm, coll)
    compat.shade_smooth(ob, angle_deg=50)
    bark = _material("MAT_Bark", lambda: _mat.principled("MAT_Bark", _mat.hex_color("#3B2A1E"), roughness=0.9))
    needles = _material("MAT_Needles", lambda: _mat.principled(
        "MAT_Needles", _mat.hex_color("#1F3A22"), roughness=0.75, sss=0.05, sheen=0.3))
    ob.data.materials.append(bark)
    ob.data.materials.append(needles)
    return ob


def broadleaf(seed=0, height=5.0, coll="Assets", name=None):
    """Deciduous tree: tapered trunk + clustered displaced canopy blobs."""
    rnd = random.Random(seed)
    h = height * rnd.uniform(0.85, 1.15)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.035 * h, radius2=0.02 * h,
                          depth=0.55 * h, matrix=Matrix.Translation((0, 0, 0.275 * h)))
    trunk = set(bm.faces)
    for i in range(rnd.randint(4, 6)):
        a = rnd.uniform(0, 6.28)
        rr = rnd.uniform(0.0, 0.16) * h
        c = Vector((math.cos(a) * rr, math.sin(a) * rr, rnd.uniform(0.58, 0.82) * h))
        res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rnd.uniform(0.17, 0.26) * h,
                                         matrix=Matrix.Translation(c))
        _jitter(bm, 0.06 * h, 1.2 / h * 5, seed * 10 + i, verts=res["verts"])
    for f in bm.faces:
        f.material_index = 0 if f in trunk else 1
    ob = _mesh.from_bmesh(name or "GEO_Broadleaf_%02d" % seed, bm, coll)
    compat.shade_smooth(ob, angle_deg=60)
    bark = _material("MAT_Bark", lambda: _mat.principled("MAT_Bark", _mat.hex_color("#3B2A1E"), roughness=0.9))
    leaves = _material("MAT_Leaves", lambda: _mat.principled(
        "MAT_Leaves", _mat.hex_color("#2C4A1C"), roughness=0.8, sss=0.03, sheen=0.1))
    ob.data.materials.append(bark)
    ob.data.materials.append(leaves)
    return ob


def bush(seed=0, size=1.0, coll="Assets", name=None):
    bm = bmesh.new()
    rnd = random.Random(seed)
    for i in range(3):
        c = Vector((rnd.uniform(-0.25, 0.25), rnd.uniform(-0.25, 0.25), 0.3)) * size
        res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rnd.uniform(0.3, 0.45) * size,
                                         matrix=Matrix.Translation(c))
        _jitter(bm, 0.08 * size, 3.0 / size, seed * 7 + i, verts=res["verts"])
    bmesh.ops.scale(bm, vec=(1, 1, 0.75), verts=bm.verts)
    ob = _mesh.from_bmesh(name or "GEO_Bush_%02d" % seed, bm, coll)
    compat.shade_smooth(ob)
    _mat.assign(ob, _material("MAT_Leaves", lambda: _mat.principled(
        "MAT_Leaves", _mat.hex_color("#2C4A1C"), roughness=0.8, sss=0.03, sheen=0.1)))
    return ob


def grass_tuft(seed=0, height=0.35, blades=7, coll="Assets", name=None):
    """Clump of bent blades (2 tris per segment). Cheap enough to scatter by the 10 000."""
    rnd = random.Random(seed)
    verts, faces = [], []
    segs = 3
    for b in range(blades):
        a = rnd.uniform(0, 6.28)
        lean = rnd.uniform(0.15, 0.45)
        bh = height * rnd.uniform(0.6, 1.1)
        w = 0.012
        base = Vector((math.cos(a), math.sin(a), 0)) * rnd.uniform(0, 0.04)
        dirv = Vector((math.cos(a), math.sin(a), 0))
        side = Vector((-math.sin(a), math.cos(a), 0))
        start = len(verts)
        for s in range(segs + 1):
            t = s / segs
            p = base + dirv * (lean * bh * t * t) + Vector((0, 0, bh * t))
            ww = w * (1 - t) + 0.001
            verts += [tuple(p - side * ww), tuple(p + side * ww)]
        for s in range(segs):
            i0 = start + 2 * s
            faces.append((i0, i0 + 1, i0 + 3, i0 + 2))
    ob = _mesh.from_pydata(name or "GEO_GrassTuft_%02d" % seed, verts, faces, coll=coll, smooth=True)
    _mat.assign(ob, _material("MAT_Grass", lambda: _mat.principled(
        "MAT_Grass", _mat.hex_color("#4F7A2B"), roughness=0.6, sss=0.15, specular=0.3)))
    return ob
