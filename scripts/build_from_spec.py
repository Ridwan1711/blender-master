"""Build a scene from a declarative JSON spec (runs inside Blender).

    python bk.py run scripts/build_from_spec.py --save out/scene.blend -- spec.json

Spec format: see examples/spec_desk.json. Top-level keys (all optional except objects):
  scene        {units, fps, frames:[a,b]}
  materials    {key: {preset: principled|metal|brushed_metal|plastic|rubber|ceramic|glass|emissive|
                      car_paint|fabric|wood|marble|concrete|painted_metal|water, color:"#hex", ...}}
  objects      [{name, type: box|cylinder|sphere|plane|torus|lathe|extrude|rounded_box|tube|text|empty,
                 location, rotation_deg, material, parent, subject, collection,
                 bevel: width | {width, segments, angle}, subsurf: levels, solidify: t,
                 array: {count, offset, relative}, mirror: {x,y,z}, smooth: angle, ...type params}]
  camera       {lens, azimuth, elevation, margin, frame: "subjects"|[names], dof: {focus, fstop}}
  environment  {backdrop: {color, roughness} , world: {type: color|gradient|sky, ...}}
  lighting     {rig: three_point|none, style, intensity, meter: true}
  render       {engine, quality, resolution:[w,h], view, look, samples}
Unknown keys raise errors instead of being silently ignored.
"""
import json
import math
import sys

import bpy

from bkit import camera as C
from bkit import compat, emit
from bkit import lighting as L
from bkit import materials as MT
from bkit import mesh as M
from bkit import render as R
from bkit import scene as S

if len(sys.argv) < 2:
    raise SystemExit("usage: build_from_spec.py -- spec.json")
with open(sys.argv[1], encoding="utf-8") as f:
    spec = json.load(f)

KNOWN_TOP = {"name", "scene", "materials", "objects", "camera", "environment", "lighting", "render",
             "export", "notes"}
bad = set(spec) - KNOWN_TOP
if bad:
    raise KeyError("unknown top-level spec keys: %s (known: %s)" % (sorted(bad), sorted(KNOWN_TOP)))


def col(v):
    if v is None:
        return None
    if isinstance(v, str):
        return MT.hex_color(v)
    return tuple(v)


# ---------------------------------------------------------------- scene
sc_spec = spec.get("scene", {})
S.new_scene(units=sc_spec.get("units", "METRIC"), fps=sc_spec.get("fps", 24),
            frame_range=tuple(sc_spec.get("frames", (1, 1))))

# ---------------------------------------------------------------- materials
PRESETS = {
    "principled": lambda n, p: MT.principled(n, col(p.pop("color", "#CCCCCC")), **p),
    "metal": lambda n, p: MT.metal(n, p.pop("kind", "steel"), color=col(p.pop("color", None)), **p),
    "brushed_metal": lambda n, p: MT.brushed_metal(n, p.pop("kind", "aluminium"), **p),
    "plastic": lambda n, p: MT.plastic(n, col(p.pop("color", "#C0392B")), **p),
    "rubber": lambda n, p: MT.rubber(n, col(p.pop("color", "#1A1A1A"))),
    "ceramic": lambda n, p: MT.ceramic(n, col(p.pop("color", "#EEEAE2")), **p),
    "glass": lambda n, p: MT.glass(n, col(p.pop("color", "#FFFFFF")), **p),
    "emissive": lambda n, p: MT.emissive(n, col(p.pop("color", "#FFD8A8")), **p),
    "car_paint": lambda n, p: MT.car_paint(n, col(p.pop("color", "#8E0F14")), **p),
    "fabric": lambda n, p: MT.fabric(n, col(p.pop("color", "#2B4C7E")), **p),
    "wood": lambda n, p: MT.wood(n, **{k: (col(v) if k in ("light", "dark") else v) for k, v in p.items()}),
    "marble": lambda n, p: MT.marble(n, **p),
    "concrete": lambda n, p: MT.concrete(n, col(p.pop("color", "#6B6A66")), **p),
    "painted_metal": lambda n, p: MT.painted_metal(n, col(p.pop("color", "#D9822B")), **p),
    "water": lambda n, p: MT.water(n, **p),
}
mats = {}
for key, m in spec.get("materials", {}).items():
    p = dict(m)
    preset = p.pop("preset", "principled")
    if preset not in PRESETS:
        raise KeyError("material %r: unknown preset %r (known: %s)" % (key, preset, sorted(PRESETS)))
    mats[key] = PRESETS[preset]("MAT_" + key, p)

# ---------------------------------------------------------------- objects
COMMON = {"name", "type", "location", "rotation_deg", "material", "parent", "subject", "collection",
          "bevel", "subsurf", "solidify", "array", "mirror", "smooth", "uv"}


def build(o):
    t = o["type"]
    name = o["name"]
    coll = o.get("collection", "Props")
    loc = tuple(o.get("location", (0, 0, 0)))
    p = {k: v for k, v in o.items() if k not in COMMON}
    if t == "box":
        ob = M.box(name, tuple(p.pop("size", (1, 1, 1))), loc, coll=coll, origin=p.pop("origin", "CENTER"))
    elif t == "cylinder":
        ob = M.cylinder(name, location=loc, coll=coll, **p)
    elif t == "sphere":
        ob = M.sphere(name, location=loc, coll=coll, **p)
    elif t == "plane":
        ob = M.plane(name, tuple(p.pop("size", (2, 2))), loc, coll=coll, **p)
    elif t == "torus":
        ob = M.torus(name, location=loc, coll=coll, **p)
    elif t == "lathe":
        ob = M.lathe(name, [tuple(x) for x in p.pop("profile")], location=loc, coll=coll, **p)
    elif t == "extrude":
        ob = M.extrude_polygon(name, [tuple(x) for x in p.pop("points")], p.pop("depth"), loc, coll=coll, **p)
    elif t == "rounded_box":
        w, d, h = p.pop("size")
        ob = M.extrude_polygon(name, M.rounded_rect(w, d, p.pop("radius", 0.02)), h, loc, coll=coll, **p)
    elif t == "tube":
        ob = M.curve_tube(name, [tuple(x) for x in p.pop("points")], coll=coll, to_mesh=True, **p)
    elif t == "text":
        cu = bpy.data.curves.new(name, "FONT")
        cu.body = p.pop("body")
        cu.size = p.pop("size", 0.1)
        cu.extrude = p.pop("extrude", 0.005)
        cu.align_x = p.pop("align", "CENTER")
        ob = S.add_object(name, cu, coll, loc)
    elif t == "empty":
        ob = S.empty(name, coll, loc)
    else:
        raise KeyError("object %r: unknown type %r" % (name, t))
    if p and t not in ("cylinder", "sphere", "torus", "lathe", "plane", "extrude", "tube"):
        raise KeyError("object %r: unknown keys %s" % (name, sorted(p)))
    if "rotation_deg" in o:
        ob.rotation_euler = [math.radians(a) for a in o["rotation_deg"]]
    if "uv" in o:
        M.box_uv(ob, o["uv"])
    if "array" in o:  # one array or a list (e.g. X then Y for table legs)
        for a in (o["array"] if isinstance(o["array"], list) else [o["array"]]):
            M.array(ob, a.get("count", 2), tuple(a.get("offset", (1, 0, 0))), a.get("relative", False))
    if "mirror" in o:
        mm = o["mirror"]
        M.mirror(ob, mm.get("x", True), mm.get("y", False), mm.get("z", False))
    if "solidify" in o:
        M.solidify(ob, o["solidify"])
    if "bevel" in o:
        b = o["bevel"] if isinstance(o["bevel"], dict) else {"width": o["bevel"]}
        M.bevel(ob, b.get("width", 0.003), b.get("segments", 3), b.get("angle", 35))
    if "subsurf" in o:
        M.subsurf(ob, o["subsurf"])
    if "smooth" in o and ob.type == "MESH":
        compat.shade_smooth(ob, o["smooth"])
    if "material" in o:
        if o["material"] not in mats:
            raise KeyError("object %r: unknown material %r" % (name, o["material"]))
        if hasattr(ob.data, "materials"):
            MT.assign(ob, mats[o["material"]])
    if o.get("subject"):
        ob["bk_subject"] = True
    return ob


objs = {}
for o in spec["objects"]:
    objs[o["name"]] = build(o)
for o in spec["objects"]:
    if o.get("parent"):
        S.parent(objs[o["name"]], objs[o["parent"]])

# ---------------------------------------------------------------- camera
from bkit import inspect as I  # noqa: E402
cs = spec.get("camera", {})
cam = C.add("CAM_Main", lens=cs.get("lens", 50))
frame_sel = cs.get("frame", "subjects")
targets = I.subjects() if frame_sel == "subjects" else [objs[n] for n in frame_sel]
C.frame(cam, targets, margin=cs.get("margin", 1.2), azimuth=cs.get("azimuth", 30),
        elevation=cs.get("elevation", 18))
if "dof" in cs:
    focus = cs["dof"].get("focus")
    C.dof(cam, focus=objs[focus] if focus in objs else focus, fstop=cs["dof"].get("fstop", 4.0))

# ---------------------------------------------------------------- environment & light
env = spec.get("environment", {})
if "backdrop" in env:
    bd = env["backdrop"]
    L.studio_backdrop(cam, targets, color=col(bd.get("color", "#808084")), roughness=bd.get("roughness", 0.6))
w = env.get("world", {"type": "color"})
if w["type"] == "color":
    L.world_color(col(w.get("color", "#0E0E10")), w.get("strength", 1.0))
elif w["type"] == "gradient":
    L.world_gradient(col(w.get("top", "#8C9BB0")), col(w.get("bottom", "#101012")), w.get("strength", 0.6))
elif w["type"] == "sky":
    L.world_sky(w.get("sun_elevation", 35), w.get("sun_azimuth", -40), w.get("strength", 0.3),
                sun_strength=w.get("sun_strength", 4.0))
lt = spec.get("lighting", {"rig": "three_point"})
if lt.get("rig", "three_point") == "three_point":
    L.three_point(targets, style=lt.get("style", "product"), intensity=lt.get("intensity", 1.0))

rs = spec.get("render", {})
R.configure(engine=rs.get("engine", "CYCLES"), quality=rs.get("quality", "draft"),
            resolution=tuple(rs.get("resolution", (1280, 720))), view=rs.get("view", "AgX"),
            look=rs.get("look", "None"), samples=rs.get("samples"), device=rs.get("device", "AUTO"))

meter = None
if lt.get("meter"):
    mn, mx, size, c = M.world_bounds(targets)
    card = M.box("CTL_TmpGreyCard", (size.length * 0.1,) * 2 + (0.002,), location=tuple(c))
    C.look_at(card, cam.matrix_world.translation)
    MT.assign(card, MT.principled("MAT_TmpGrey18", (0.18, 0.18, 0.18), roughness=0.95, specular=0.0))
    # the card must not be hidden by the subject it sits in: put it just in front, toward camera
    d = (cam.matrix_world.translation - c).normalized()
    card.location = c + d * (size.length * 0.6)
    meter = R.auto_exposure(card, res=200, samples=12)
    bpy.data.objects.remove(card, do_unlink=True)
S.purge_orphans()
emit(spec=spec.get("name", sys.argv[1]), objects=len(objs), materials=len(mats),
     subjects=[o.name for o in targets], metering=meter)
