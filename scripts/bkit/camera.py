"""Cameras: placement, look-at, automatic framing, depth of field, camera moves.

Azimuth convention used everywhere in bkit: 0 = in front of the subject (on -Y,
looking toward +Y), 90 = on the +X side, 180 = behind. Elevation in degrees above horizon.

    from bkit import camera as C
    cam = C.add("CAM_Main", lens=50)
    C.frame(cam, [hero], azimuth=30, elevation=15, margin=1.2)
    C.dof(cam, focus=hero, fstop=2.8)
"""
import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

from . import anim
from . import mesh as _mesh
from . import scene as _scene


def direction(azimuth=30.0, elevation=15.0):
    az, el = math.radians(azimuth), math.radians(elevation)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def look_at(ob, target, roll=0.0):
    """Point an object's -Z axis (cameras, lights) at target (Vector, tuple or object)."""
    t = target.matrix_world.translation if hasattr(target, "matrix_world") else Vector(target)
    loc = ob.matrix_world.translation.copy() if ob.parent else Vector(ob.location)
    d = t - loc
    if d.length < 1e-9:
        return ob
    q = d.to_track_quat("-Z", "Y")
    if roll:
        q = q @ Matrix.Rotation(math.radians(roll), 4, "Z").to_quaternion()
    ob.rotation_mode = "XYZ"
    ob.rotation_euler = q.to_euler()
    return ob


def add(name="CAM_Main", lens=50.0, location=(0, -6, 2), target=(0, 0, 0.5), coll="Cameras",
        sensor=36.0, clip_start=0.05, clip_end=500.0, active=True, ortho_scale=None):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = sensor
    cd.clip_start, cd.clip_end = clip_start, clip_end
    if ortho_scale:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho_scale
    ob = _scene.add_object(name, cd, coll, location)
    if target is not None:
        look_at(ob, target)
    if active:
        bpy.context.scene.camera = ob
    return ob


def _corners(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for ob in objs:
        if ob.type in {"MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES", "POINTCLOUD", "VOLUME"}:
            ev = ob.evaluated_get(dg)
            pts += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    return pts


def projected_extent(cam, pts, scene=None):
    """Normalised frame coverage of points: dict(xmin,xmax,ymin,ymax,behind)."""
    scene = scene or bpy.context.scene
    co = [world_to_camera_view(scene, cam, p) for p in pts]
    return {"xmin": min(c.x for c in co), "xmax": max(c.x for c in co),
            "ymin": min(c.y for c in co), "ymax": max(c.y for c in co),
            "behind": sum(1 for c in co if c.z <= 0)}


def frame(cam, objs, margin=1.15, azimuth=30.0, elevation=15.0, lens=None, center=None,
          fill_axis="max"):
    """Place `cam` so `objs` fill the frame with `margin` (1.0 = touching edges).

    Perspective: binary-searches distance using exact projection of bounds corners.
    Orthographic: sets ortho_scale. Returns distance (or ortho_scale).
    """
    objs = [objs] if hasattr(objs, "bound_box") else list(objs)
    scene = bpy.context.scene
    if lens:
        cam.data.lens = lens
    pts = _corners(objs)
    if not pts:
        raise ValueError("frame(): no geometry in objs")
    mn, mx, size, c = _mesh.world_bounds(objs)
    c = Vector(center) if center is not None else c
    d_hat = direction(azimuth, elevation)
    if elevation >= 89.9:      # exact top view: +X right, +Y up (to_track_quat is ambiguous here)
        rot = Matrix.Rotation(math.radians(azimuth), 4, "Z")
    elif elevation <= -89.9:   # bottom view
        rot = Matrix.Rotation(math.radians(azimuth), 4, "Z") @ Matrix.Rotation(math.pi, 4, "X")
    else:
        rot = (-d_hat).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    radius = max(size.length / 2, 1e-3)

    if cam.data.type == "ORTHO":
        cam.matrix_world = Matrix.Translation(c + d_hat * radius * 4) @ rot
        cam.data.ortho_scale = 1.0
        e = projected_extent(cam, pts, scene)
        span = max(e["xmax"] - e["xmin"], e["ymax"] - e["ymin"])
        cam.data.ortho_scale = span * margin
        cam.data.clip_end = max(cam.data.clip_end, radius * 10)
        return cam.data.ortho_scale

    target = 1.0 / margin

    def coverage(dist):
        cam.matrix_world = Matrix.Translation(c + d_hat * dist) @ rot
        e = projected_extent(cam, pts, scene)
        if e["behind"]:
            return 99.0
        return max(abs(e["xmin"] - 0.5), abs(e["xmax"] - 0.5), abs(e["ymin"] - 0.5),
                   abs(e["ymax"] - 0.5)) * 2

    lo, hi = radius * 0.3, radius * 200
    for _ in range(60):
        mid = (lo + hi) / 2
        if coverage(mid) > target:
            lo = mid
        else:
            hi = mid
    coverage(hi)
    cam.data.clip_start = min(cam.data.clip_start, max(0.001, hi * 0.01))
    cam.data.clip_end = max(cam.data.clip_end, (hi + radius) * 4)
    return hi


def dof(cam, focus=None, fstop=2.8, distance=None, blades=0):
    """Depth of field. focus: object, point (creates CTL_Focus empty) or None with distance."""
    d = cam.data.dof
    d.use_dof = True
    d.aperture_fstop = fstop
    d.aperture_blades = blades
    if focus is not None and hasattr(focus, "matrix_world"):
        d.focus_object = focus
    elif focus is not None:
        e = _scene.empty("CTL_Focus", "Cameras", location=focus, size=0.1)
        d.focus_object = e
    elif distance is not None:
        d.focus_distance = distance
    return d


def track(cam, target):
    """Track To constraint: keeps the camera aimed while it moves."""
    if not hasattr(target, "matrix_world"):
        target = _scene.empty("CTL_CamTarget", "Cameras", location=target, size=0.2)
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    return target


def orbit(cam, center=(0, 0, 0), radius=6.0, height=2.0, frames=(1, 120), start_azimuth=0.0,
          sweep=360.0, aim=None):
    """Turntable/orbit: camera parented to a pivot empty that rotates linearly."""
    pivot = _scene.empty("CTL_CamPivot", "Cameras", location=center, size=0.3)
    cam.parent = pivot
    cam.matrix_parent_inverse = Matrix.Identity(4)
    cam.location = (0.0, -radius, height)
    track(cam, aim if aim is not None else Vector(center))
    pivot.rotation_euler.z = math.radians(start_azimuth)
    anim.key(pivot, "rotation_euler", frames[0], index=2)
    pivot.rotation_euler.z = math.radians(start_azimuth + sweep)
    anim.key(pivot, "rotation_euler", frames[1], index=2)
    anim.set_interpolation(pivot, "LINEAR")
    return pivot


def dolly(cam, start, end, frames=(1, 120), aim=None, easing="EASE_IN_OUT"):
    """Move the camera from start to end (eased) while aiming at `aim`."""
    if aim is not None:
        track(cam, aim)
    anim.keys(cam, "location", [(frames[0], tuple(start)), (frames[1], tuple(end))])
    anim.ease(cam, easing, path="location")
    return cam


def rack_focus(cam, keyframes, fstop=2.0):
    """keyframes = [(frame, distance_m), ...] focus pulls."""
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.focus_object = None
    anim.keys(cam, "data.dof.focus_distance", keyframes)
