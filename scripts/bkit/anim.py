"""Keyframes, interpolation and procedural motion (safe for 4.4+ layered/slotted actions).

    from bkit import anim as A
    A.keys(obj, "location", [(1, (0, 0, 0)), (48, (2, 0, 0))], interpolation="BEZIER")
    A.keys(cam, "data.lens", [(1, 35), (96, 50)])     # "data." keys the camera datablock
    A.ease(obj, "EASE_IN_OUT")
    A.noise(cam, "rotation_euler", strength=0.01, scale=25)   # handheld shake
"""
import bpy

from . import compat


def _target(obj, path):
    if path.startswith("data."):
        return obj.data, path[5:]
    return obj, path


def _set(owner, path, value, index=-1):
    """setattr that understands dotted paths like 'dof.focus_distance'."""
    head, _, last = path.rpartition(".")
    parent = owner.path_resolve(head) if head else owner
    if index >= 0:
        getattr(parent, last)[index] = value
    else:
        setattr(parent, last, value)


def key(obj, path, frame, value=None, index=-1):
    """Set (optional) and keyframe one property at one frame."""
    owner, p = _target(obj, path)
    if value is not None:
        _set(owner, p, value, index)
    owner.keyframe_insert(data_path=p, frame=frame, index=index)


def keys(obj, path, frames_values, interpolation=None, easing=None, index=-1):
    """frames_values = [(frame, value), ...]. Returns the owner ID that holds the action."""
    owner, _ = _target(obj, path)
    for f, v in frames_values:
        key(obj, path, f, v, index=index)
    if interpolation or easing:
        set_interpolation(owner, interpolation or "BEZIER", easing=easing, path=_target(obj, path)[1])
    return owner


def fcurves(idblock, path=None):
    fcs = compat.id_fcurves(idblock)
    return [f for f in fcs if path is None or f.data_path == path]


def set_interpolation(idblock, kind="LINEAR", easing=None, path=None):
    """kind: CONSTANT | LINEAR | BEZIER | SINE | QUAD | CUBIC | EXPO | BACK | BOUNCE | ELASTIC ..."""
    n = 0
    for fc in fcurves(idblock, path):
        for kp in fc.keyframe_points:
            kp.interpolation = kind
            if easing:
                kp.easing = easing
            n += 1
        fc.update()
    return n


def ease(obj, easing="EASE_IN_OUT", path=None):
    """Smooth starts/stops: BEZIER keys with auto-clamped handles (default) or eased curves."""
    owner = obj
    for fc in fcurves(owner, path):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
            kp.easing = easing if easing != "AUTO" else "AUTO"
        fc.update()


def cycle(idblock, path=None):
    """Loop animation forever (Cycles F-curve modifier)."""
    for fc in fcurves(idblock, path):
        if not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")


def noise(obj, path="rotation_euler", strength=0.01, scale=20.0, phase=0.0, indices=(0, 1, 2)):
    """Procedural noise on an animated or static property (adds a key if none exists)."""
    owner, p = _target(obj, path)
    if not fcurves(owner, p):
        owner.keyframe_insert(data_path=p, frame=bpy.context.scene.frame_start)
    out = []
    for i, fc in enumerate(sorted(fcurves(owner, p), key=lambda f: f.array_index)):
        if fc.array_index not in indices:
            continue
        m = fc.modifiers.new("NOISE")
        m.strength = strength
        m.scale = scale
        m.phase = phase + 17.0 * fc.array_index
        out.append(m)
    return out


def key_socket(material_or_tree, node_name, socket_name, frames_values, interpolation=None):
    """Animate a node input, e.g. emission strength:
    key_socket(mat, "Principled BSDF", "Emission Strength", [(1, 0), (24, 12)])
    The action lives on the node tree (mat.node_tree.animation_data)."""
    tree = getattr(material_or_tree, "node_tree", material_or_tree)
    node = tree.nodes[node_name]
    sock = compat.socket(node, socket_name)
    for f, v in frames_values:
        sock.default_value = v
        sock.keyframe_insert("default_value", frame=f)
    if interpolation:
        set_interpolation(tree, interpolation)
    return tree


def motion_report(obj, frames, world=True):
    """Per-frame world positions and step statistics -> detect pops/jumps in camera moves.
    A 'pop' is a step > 3x the median step."""
    sc = bpy.context.scene
    cur = sc.frame_current
    pts = []
    for f in frames:
        sc.frame_set(f)
        pts.append((obj.matrix_world.translation.copy() if world else obj.location.copy()))
    sc.frame_set(cur)
    steps = [(b - a).length for a, b in zip(pts, pts[1:])]
    if not steps:
        return {}
    med = sorted(steps)[len(steps) // 2]
    pops = [frames[i + 1] for i, s in enumerate(steps) if med > 1e-6 and s > 3 * med]
    return {"path_length": round(sum(steps), 3), "max_step": round(max(steps), 4),
            "median_step": round(med, 4), "pops_at_frames": pops,
            "start": [round(x, 3) for x in pts[0]], "end": [round(x, 3) for x in pts[-1]]}


def frame_range_of(idblock):
    fr = [kp.co.x for fc in fcurves(idblock) for kp in fc.keyframe_points]
    return (min(fr), max(fr)) if fr else None


def sample(obj, path, frames):
    """Evaluate a property at frames (for verifying motion numerically)."""
    sc = bpy.context.scene
    cur = sc.frame_current
    owner, p = _target(obj, path)
    out = []
    for f in frames:
        sc.frame_set(f)
        v = owner.path_resolve(p)
        out.append(tuple(v) if hasattr(v, "__len__") else v)
    sc.frame_set(cur)
    return out
