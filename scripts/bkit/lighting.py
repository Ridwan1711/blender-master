"""Lights, light rigs, world setups and studio backdrops.

Energy guide (AgX, exposure 0): rigs here scale power with distance^2 so a rig
looks the same for a 10 cm product and a 3 m statue. Always verify with
`bk.py imgcheck` on a render - do not trust numbers alone.

    from bkit import lighting as L
    L.three_point([hero], style="product")
    L.world_sky(sun_elevation=25, sun_azimuth=-40)
    L.backdrop("GEO_Backdrop", width=6, depth=5, height=3)
"""
import math

import bmesh
import bpy
from mathutils import Vector

from . import camera as _cam
from . import compat
from . import materials as _mat
from . import mesh as _mesh
from . import scene as _scene


def kelvin(k):
    """Approximate blackbody colour (linear RGB) for 1000K-12000K. 6500K ~ white."""
    t = k / 100.0
    r = 255 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    rgb = [min(max(x, 0), 255) / 255.0 for x in (r, g, b)]
    return tuple(_mat.srgb_to_linear(c) for c in rgb)


def light(kind="AREA", name=None, energy=100.0, color=(1, 1, 1), location=(0, 0, 4), target=None,
          size=1.0, size_y=None, shape="RECTANGLE", spot_angle=45.0, spot_blend=0.2,
          coll="Lighting", shadow=True):
    """Create a light. size = area edge (AREA), radius (POINT/SPOT), angular diameter deg (SUN)."""
    kind = kind.upper()
    name = name or "LGT_%s" % kind.title()
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = tuple(color)[:3]
    compat.try_set(ld, "use_shadow", shadow)
    if kind == "AREA":
        ld.shape = shape
        ld.size = size
        if shape in ("RECTANGLE", "ELLIPSE"):
            ld.size_y = size_y or size
    elif kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = size
        if kind == "SPOT":
            ld.spot_size = math.radians(spot_angle)
            ld.spot_blend = spot_blend
    elif kind == "SUN":
        ld.angle = math.radians(size)
    ob = _scene.add_object(name, ld, coll, location)
    if target is not None:
        _cam.look_at(ob, target)
    return ob


def sun(name="LGT_Sun", elevation=35.0, azimuth=-40.0, strength=4.0, angle=0.6, color=None,
        coll="Lighting"):
    """Sun from (elevation, azimuth) in bkit convention (azimuth 0 = from the front/-Y)."""
    ob = light("SUN", name, energy=strength, color=color or kelvin(5600), size=angle,
               location=(0, 0, 10), coll=coll)
    ob.rotation_euler = (math.radians(90 - elevation), 0.0, math.radians(azimuth))
    return ob


def _azimuth_of(p, c):
    v = Vector(p) - Vector(c)
    return math.degrees(math.atan2(v.x, -v.y))


STYLES = {
    #            key, fill, rim, key_az_offset, key_el, softness(size factor)
    "product": (1.0, 0.35, 0.7, 40.0, 40.0, 1.6),
    "soft": (1.0, 0.55, 0.4, 35.0, 35.0, 2.2),
    "dramatic": (1.0, 0.08, 1.3, 70.0, 30.0, 0.8),
    "portrait": (1.0, 0.25, 0.6, 45.0, 35.0, 1.2),
}


def three_point(objs, style="product", camera=None, intensity=1.0, temperature=(5200, 6500, 7000),
                coll="Lighting"):
    """Key/fill/rim area lights placed relative to the camera and scaled to the subject.

    Returns dict of the three light objects. intensity scales all three.
    """
    objs = [objs] if hasattr(objs, "bound_box") else list(objs)
    mn, mx, size, c = _mesh.world_bounds(objs)
    r = max(size.length / 2, 0.05)
    cam = camera or bpy.context.scene.camera
    cam_az = _azimuth_of(cam.matrix_world.translation, c) if cam else 30.0
    k, f, rim, off, kel, soft = STYLES[style]
    d = r * 3.5
    # W for the key at distance d. Calibrated so an 18% grey card lands near mid-grey
    # (S04 measured +1.6 EV with the old 450 W); fine-tune with render.auto_exposure().
    base = 170.0 * (d / 3.5) ** 2 * intensity

    def place(az, el, dist):
        return c + _cam.direction(az, el) * dist

    key = light("AREA", "LGT_Key", base * k, kelvin(temperature[0]), place(cam_az - off, kel, d), c,
                size=r * soft, coll=coll)
    fill = light("AREA", "LGT_Fill", base * f, kelvin(temperature[1]), place(cam_az + 55, 12, d * 1.1),
                 c, size=r * soft * 1.6, coll=coll)
    rim_l = light("AREA", "LGT_Rim", base * rim, kelvin(temperature[2]),
                  place(cam_az + 160, 35, d * 0.9), c + Vector((0, 0, size.z * 0.25)),
                  size=r * soft * 0.6, coll=coll)
    return {"key": key, "fill": fill, "rim": rim_l}


# --------------------------------------------------------------------------- world
def _world():
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    return w


def world_color(color=(0.05, 0.05, 0.06), strength=1.0):
    w = _world()
    nt = w.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Color"].default_value = tuple(color)[:3] + (1.0,)
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    out.location = (300, 0)
    return w


def world_gradient(top=(0.25, 0.35, 0.55), bottom=(0.04, 0.04, 0.05), strength=1.0):
    """Vertical gradient environment (studio/stylised). Colours linear."""
    w = _world()
    nt = _mat.Nodes(w.node_tree)
    w.node_tree.nodes.clear()
    tc = nt.new("ShaderNodeTexCoord")
    sep = nt.new("ShaderNodeSeparateXYZ")
    mr = nt.new("ShaderNodeMapRange", From_Min=-0.2, From_Max=0.8)
    rp = nt.ramp([(0.0, bottom), (1.0, top)])
    bg = nt.new("ShaderNodeBackground", Strength=strength)
    out = nt.new("ShaderNodeOutputWorld")
    nt.link(tc, "Generated", sep, "Vector")  # world "Generated" = view direction, z in [-1, 1]
    nt.link(sep, "Z", mr, "Value")
    nt.link(mr, "Result", rp, "Fac")
    nt.link(rp, "Color", bg, "Color")
    nt.link(bg, "Background", out, "Surface")
    nt.layout()
    return w


def world_sky(sun_elevation=35.0, sun_azimuth=-40.0, strength=0.25, air=1.0, dust=1.0,
              ozone=1.0, sun_lamp=True, sun_strength=4.0, altitude=0.0):
    """Physical (Nishita) sky. With sun_lamp=True the sky's sun disc is replaced by a
    matching Sun light (crisper shadows, works the same in EEVEE and Cycles).

    Sky strength ~0.2-0.4 balances against a ~3-5 W/m2 sun lamp under AgX.
    """
    w = _world()
    nt = w.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    compat.set_enum(sky, "sky_type", ["NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "HOSEK_WILKIE"])
    for prop, val in (("sun_elevation", math.radians(sun_elevation)),
                      ("sun_rotation", math.radians(sun_azimuth - 90.0)),
                      ("air_density", air), ("dust_density", dust), ("ozone_density", ozone),
                      ("altitude", altitude), ("sun_disc", not sun_lamp)):
        compat.try_set(sky, prop, val)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    sky.location, bg.location, out.location = (-300, 0), (0, 0), (250, 0)
    sun_ob = None
    if sun_lamp:
        warm = 5000 if sun_elevation > 15 else 3500
        sun_ob = sun("LGT_Sun", sun_elevation, sun_azimuth, sun_strength, color=kelvin(warm))
    return w, sun_ob


def world_hdri(path, strength=1.0, rotation_deg=0.0):
    import os
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    w = _world()
    nt = _mat.Nodes(w.node_tree)
    w.node_tree.nodes.clear()
    tc = nt.new("ShaderNodeTexCoord")
    mp = nt.new("ShaderNodeMapping", Rotation=(0, 0, math.radians(rotation_deg)))
    env = nt.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(path, check_existing=True)
    bg = nt.new("ShaderNodeBackground", Strength=strength)
    out = nt.new("ShaderNodeOutputWorld")
    nt.link(tc, "Generated", mp, "Vector")
    nt.link(mp, "Vector", env, "Vector")
    nt.link(env, "Color", bg, "Color")
    nt.link(bg, "Background", out, "Surface")
    nt.layout()
    return w


# --------------------------------------------------------------------------- studio
def backdrop(name="GEO_Backdrop", width=6.0, depth=5.0, height=3.0, radius=1.0, segments=16,
             color=(0.6, 0.6, 0.62), roughness=0.6, coll="Environment", location=(0, 0, 0)):
    """Seamless cyclorama: floor curving into a back wall (+Y side). Faces point at the subject."""
    prof = [(-depth / 2, 0.0)]
    y0 = depth / 2 - radius
    for i in range(segments + 1):
        a = math.radians(90.0 * i / segments)
        prof.append((y0 + radius * math.sin(a), radius - radius * math.cos(a)))
    prof.append((depth / 2, height))
    bm = bmesh.new()
    rows = []
    for y, z in prof:
        rows.append((bm.verts.new((-width / 2, y, z)), bm.verts.new((width / 2, y, z))))
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    ob = _mesh.from_bmesh(name, bm, coll, location)
    compat.shade_smooth(ob)
    m = _mat.principled("MAT_Backdrop", color, roughness=roughness)
    _mat.assign(ob, m)
    return ob


def studio_backdrop(cam, objs, color=(0.6, 0.6, 0.62), roughness=0.6, name="GEO_Backdrop",
                    coll="Environment", wall_distance=None, overscan=1.6, floor_z=0.0, frames=None):
    """Cyclorama oriented to the camera and sized from its frustum, so no edge can show.

    Call AFTER framing/animating the camera. The wall sits behind the subject as seen from `cam`.
    floor_z: height of the floor (default 0 = ground plane). None -> lowest point of objs.
    frames=(start, end): for a MOVING camera, samples the path and covers all of it
    (otherwise an orbit will see past the edge of a backdrop sized for one frame).
    """
    objs = [objs] if hasattr(objs, "bound_box") else list(objs)
    mn, mx, size, c = _mesh.world_bounds(objs)
    if floor_z is not None:
        mn = Vector((mn.x, mn.y, floor_z))
    r = max(size.length / 2, 0.05)
    sc0 = bpy.context.scene
    samples = []
    if frames:
        cur = sc0.frame_current
        n = 9
        for i in range(n):
            sc0.frame_set(int(round(frames[0] + (frames[1] - frames[0]) * i / (n - 1))))
            samples.append(cam.matrix_world.translation.copy())
        sc0.frame_set(cur)
    else:
        samples.append(cam.matrix_world.translation.copy())
    azs = [math.radians(_azimuth_of(p, c)) for p in samples]
    az = math.degrees(math.atan2(sum(math.sin(a) for a in azs), sum(math.cos(a) for a in azs)))
    spread = max(abs(math.degrees(math.atan2(math.sin(a - math.radians(az)), math.cos(a - math.radians(az)))))
                 for a in azs)
    cp = max(samples, key=lambda p: (Vector((p.x, p.y)) - Vector((c.x, c.y))).length)
    cp = Vector((cp.x, cp.y, max(p.z for p in samples)))
    dist = max((Vector((cp.x, cp.y)) - Vector((c.x, c.y))).length, r)
    D = wall_distance or max(3.0 * r, 0.6 * dist)
    sc = bpy.context.scene
    rx, ry = sc.render.resolution_x, sc.render.resolution_y
    if cam.data.type == "ORTHO":
        half_w = cam.data.ortho_scale / 2
        half_h = half_w * ry / rx
        width, height = 2 * half_w * overscan + 2 * r, (cp.z - mn.z) + 2 * half_h * overscan
    else:
        hfov = 2 * math.atan(cam.data.sensor_width / 2 / cam.data.lens)
        if ry > rx:
            hfov = 2 * math.atan(math.tan(hfov / 2) * rx / ry)
        vfov = 2 * math.atan(math.tan(hfov / 2) * ry / rx)
        reach = dist + D
        width = 2 * reach * math.tan(hfov / 2) * overscan + 2 * r
        width += 2 * reach * math.sin(math.radians(min(spread, 80)))  # orbiting cameras
        height = max(cp.z - mn.z, 0) + reach * math.tan(vfov / 2) * overscan + r
    depth = dist * 1.4 + D
    radius = min(D * 0.6, height * 0.4)
    ob = backdrop(name, width, depth, height, radius, color=color, roughness=roughness, coll=coll)
    ob.rotation_euler.z = math.radians(az)
    off = Vector((0.0, D - depth / 2, 0.0))
    off.rotate(ob.rotation_euler)
    ob.location = Vector((c.x, c.y, mn.z)) + off
    return ob
