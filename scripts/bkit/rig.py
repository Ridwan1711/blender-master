"""Rigging: armatures from data, IK/constraints, binding (rigid, manual, automatic), posing.

Edit bones only exist in Edit Mode; these helpers switch modes with a context override so
they work headless. Always return to Object Mode before saving or rendering.

    from bkit import rig as RG
    arm = RG.armature("RIG_Arm", [
        dict(name="base", head=(0,0,0), tail=(0,0,0.3)),
        dict(name="upper", head=(0,0,0.3), tail=(0,0,1.0), parent="base", connect=True),
        dict(name="fore", head=(0,0,1.0), tail=(0,0,1.6), parent="upper", connect=True)])
    tgt = RG.ik(arm, "fore", target=(0.6, 0, 0.9), chain=2)
    RG.bind_rigid(part_obj, arm, "upper")           # mechanical parts follow one bone
    RG.bind_auto(body_mesh, arm)                     # organic: heat-map automatic weights
"""
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import compat
from . import scene as _scene


def _mode(ob, mode):
    vl = bpy.context.view_layer
    vl.objects.active = ob
    ob.select_set(True)
    with compat.override(active_object=ob, object=ob, selected_objects=[ob],
                         selected_editable_objects=[ob]):
        bpy.ops.object.mode_set(mode=mode)


def armature(name, bones, coll="Rig", location=(0, 0, 0), display="OCTAHEDRAL", in_front=True):
    """bones: dicts(name, head, tail, parent=None, connect=False, roll=None, deform=True).

    Rolls are made DETERMINISTIC unless given: horizontal bones get local Z = world up,
    near-vertical bones get local Z = world forward (-Y). Blender's default roll differs
    between mirrored bones, so the same rotation would raise one arm and lower the other.
    With these rolls: rotate X- to lower T-pose arms, X+ to swing a leg forward (facing -Y).
    """
    arm = bpy.data.armatures.new(name)
    arm.display_type = display
    ob = _scene.add_object(name, arm, coll, location)
    ob.show_in_front = in_front
    _mode(ob, "EDIT")
    try:
        ebs = {}
        for b in bones:
            eb = arm.edit_bones.new(b["name"])
            eb.head, eb.tail = Vector(b["head"]), Vector(b["tail"])
            if b.get("roll") is not None:
                eb.roll = b["roll"]
            else:
                d = (eb.tail - eb.head).normalized()
                eb.align_roll(Vector((0, -1, 0)) if abs(d.z) > 0.7 else Vector((0, 0, 1)))
            eb.use_deform = b.get("deform", True)
            ebs[b["name"]] = eb
        for b in bones:
            if b.get("parent"):
                ebs[b["name"]].parent = ebs[b["parent"]]
                ebs[b["name"]].use_connect = b.get("connect", False)
    finally:
        _mode(ob, "OBJECT")
    return ob


def ik(arm_ob, bone, target, chain=2, pole=None, pole_angle_deg=-90.0, name=None):
    """IK constraint on `bone`; target may be an object or a point (creates CTL_ empty).

    The chain MUST have a slight rest-pose bend toward the pole (elbow/knee offset a few cm).
    A perfectly straight chain will not bend: it points at the target fully stretched.
    Verify with bone_world_head(...) tail vs target distance.
    """
    if not hasattr(target, "matrix_world"):
        target = _scene.empty(name or "CTL_IK_%s" % bone, "Rig", location=target, display="SPHERE", size=0.08)
    pb = arm_ob.pose.bones[bone]
    c = pb.constraints.new("IK")
    c.target = target
    c.chain_count = chain
    if pole is not None:
        if not hasattr(pole, "matrix_world"):
            pole = _scene.empty("CTL_Pole_%s" % bone, "Rig", location=pole, display="CONE", size=0.06)
        c.pole_target = pole
        c.pole_angle = math.radians(pole_angle_deg)
    return target


def bind_rigid(ob, arm_ob, bone):
    """Parent a (mechanical) object to a bone, keeping its current world transform."""
    _scene.refresh()
    mw = ob.matrix_world.copy()
    ob.parent = arm_ob
    ob.parent_type = "BONE"
    ob.parent_bone = bone
    _scene.refresh()
    ob.matrix_world = mw
    return ob


def bind_auto(mesh_ob, arm_ob):
    """Automatic (bone heat) weights + Armature modifier. Needs a clean, manifold mesh;
    check the log for 'Bone Heat Weighting: failed' and the returned empty-group list."""
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    mesh_ob.select_set(True)
    arm_ob.select_set(True)
    vl.objects.active = arm_ob
    with compat.override(active_object=arm_ob, object=arm_ob, selected_objects=[mesh_ob, arm_ob],
                         selected_editable_objects=[mesh_ob, arm_ob]):
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    return weight_report(mesh_ob, arm_ob)


def bind_groups(mesh_ob, arm_ob, assign):
    """Manual weights. assign: {bone_name: [(vertex_index, weight), ...]} -> vertex groups +
    Armature modifier. Use for stylised/mechanical meshes where heat weights fail."""
    for bone, items in assign.items():
        vg = mesh_ob.vertex_groups.get(bone) or mesh_ob.vertex_groups.new(name=bone)
        for vi, w in items:
            vg.add([vi], w, "REPLACE")
    mod = mesh_ob.modifiers.get("Armature") or mesh_ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm_ob
    _scene.refresh()
    mw = mesh_ob.matrix_world.copy()
    mesh_ob.parent = arm_ob
    mesh_ob.matrix_world = mw
    return weight_report(mesh_ob, arm_ob)


def weight_report(mesh_ob, arm_ob):
    """Which deform bones got weights, and how many vertices have none (would not deform)."""
    deform = [b.name for b in arm_ob.data.bones if b.use_deform]
    counts = {g.name: 0 for g in mesh_ob.vertex_groups}
    idx = {g.index: g.name for g in mesh_ob.vertex_groups}
    unweighted = 0
    for v in mesh_ob.data.vertices:
        ws = [g for g in v.groups if g.weight > 1e-4]
        if not ws:
            unweighted += 1
        for g in ws:
            counts[idx[g.group]] += 1
    return {"bones_without_weights": [b for b in deform if counts.get(b, 0) == 0],
            "unweighted_vertices": unweighted, "vertices": len(mesh_ob.data.vertices),
            "groups": {k: v for k, v in counts.items() if v}}


def pose(arm_ob, bone, rotation=None, location=None, frame=None, mode="XYZ"):
    """Set a pose-bone rotation (degrees, Euler) and/or location; keyframe if frame given."""
    pb = arm_ob.pose.bones[bone]
    if rotation is not None:
        pb.rotation_mode = mode
        pb.rotation_euler = Euler([math.radians(a) for a in rotation], mode)
        if frame is not None:
            pb.keyframe_insert("rotation_euler", frame=frame)
    if location is not None:
        pb.location = location
        if frame is not None:
            pb.keyframe_insert("location", frame=frame)
    return pb


def bone_world_head(arm_ob, bone, frame=None):
    """World-space head of a posed bone (for verifying IK/animation numerically)."""
    if frame is not None:
        bpy.context.scene.frame_set(frame)
    pb = arm_ob.pose.bones[bone]
    return arm_ob.matrix_world @ pb.head, arm_ob.matrix_world @ pb.tail


# --------------------------------------------------------------------------- character
HUMANOID = {  # joint: (position, parent) ~1.75 m, origin between the feet, facing -Y
    "hips": ((0, 0, 0.95), None), "spine": ((0, 0, 1.15), "hips"), "chest": ((0, 0, 1.35), "spine"),
    "neck": ((0, 0, 1.52), "chest"), "head": ((0, 0, 1.62), "neck"), "head_top": ((0, 0, 1.78), "head"),
    "shoulder.L": ((0.18, 0, 1.45), "chest"), "elbow.L": ((0.45, 0, 1.43), "shoulder.L"),
    "wrist.L": ((0.70, 0, 1.42), "elbow.L"), "hand.L": ((0.80, 0, 1.42), "wrist.L"),
    "shoulder.R": ((-0.18, 0, 1.45), "chest"), "elbow.R": ((-0.45, 0, 1.43), "shoulder.R"),
    "wrist.R": ((-0.70, 0, 1.42), "elbow.R"), "hand.R": ((-0.80, 0, 1.42), "wrist.R"),
    "hip.L": ((0.10, 0, 0.92), "hips"), "knee.L": ((0.11, -0.02, 0.50), "hip.L"),
    "ankle.L": ((0.11, 0.0, 0.08), "knee.L"), "toe.L": ((0.11, -0.14, 0.03), "ankle.L"),
    "hip.R": ((-0.10, 0, 0.92), "hips"), "knee.R": ((-0.11, -0.02, 0.50), "hip.R"),
    "ankle.R": ((-0.11, 0.0, 0.08), "knee.R"), "toe.R": ((-0.11, -0.14, 0.03), "ankle.R"),
}
RADII = {"hips": 0.15, "spine": 0.14, "chest": 0.17, "neck": 0.06, "head": 0.1, "head_top": 0.09,
         "shoulder.L": 0.07, "elbow.L": 0.05, "wrist.L": 0.04, "hand.L": 0.045,
         "shoulder.R": 0.07, "elbow.R": 0.05, "wrist.R": 0.04, "hand.R": 0.045,
         "hip.L": 0.09, "knee.L": 0.065, "ankle.L": 0.05, "toe.L": 0.04,
         "hip.R": 0.09, "knee.R": 0.065, "ankle.R": 0.05, "toe.R": 0.04}


def mannequin(name="Mannequin", coll="Character", scale=1.0, location=(0, 0, 0)):
    """Skin-modifier body + matching armature + automatic weights. Returns (mesh_ob, arm_ob, report).
    Bones are named after the joint where they END (e.g. 'knee.L' = thigh).
    The mesh is parented to the armature: move the ARMATURE only (moving both doubles the offset
    and the mesh deforms around bones that are somewhere else)."""
    from . import mesh as _mesh
    names = list(HUMANOID)
    verts = [Vector(HUMANOID[n][0]) * scale for n in names]
    edges = [(names.index(n), names.index(p)) for n, (_, p) in HUMANOID.items() if p]
    me = bpy.data.meshes.new("GEO_" + name)
    me.from_pydata([tuple(v) for v in verts], edges, [])
    ob = _scene.add_object("GEO_" + name, me, coll)
    skin = ob.modifiers.new("Skin", "SKIN")
    skin.branch_smoothing = 0.6
    sv = me.skin_vertices[0].data
    for i, n in enumerate(names):
        r = RADII[n] * scale
        sv[i].radius = (r, r * (0.75 if n in ("hips", "spine", "chest") else 1.0))
        sv[i].use_root = n == "hips"
    sub = ob.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = sub.render_levels = 1
    _mesh.apply_modifiers(ob)
    compat.shade_smooth(ob)
    bones = []
    for n, (pos, par) in HUMANOID.items():
        if par is None:
            continue
        bones.append(dict(name=n, head=tuple(Vector(HUMANOID[par][0]) * scale), tail=tuple(Vector(pos) * scale),
                          parent=par if HUMANOID[par][1] is not None else None,
                          connect=HUMANOID[par][1] is not None))
    arm = armature("RIG_" + name, bones, coll)
    report = bind_auto(ob, arm)
    arm.location = location  # child mesh follows
    return ob, arm, report


def walk_cycle(arm_ob, frames=24, start=1, stride_deg=28.0, knee_deg=40.0, arm_swing_deg=22.0, cycles=True):
    """Procedural in-place walk keys (thigh, shin, upper arm) with an F-curve cycle modifier."""
    from . import anim
    half = frames / 2
    for f_off, phase in ((0, 1), (half, -1), (frames, 1)):
        f = start + f_off
        pose(arm_ob, "knee.L", (stride_deg * phase, 0, 0), frame=f)
        pose(arm_ob, "knee.R", (-stride_deg * phase, 0, 0), frame=f)
        # upper arms lowered from T-pose (-70 about local X), then swung about the rest bone
        # axis; mirrored rolls make the SAME sign swing the arms in opposite directions,
        # and the arm opposite the forward leg goes forward.
        pose(arm_ob, "elbow.L", (-70, arm_swing_deg * phase, 0), frame=f)
        pose(arm_ob, "elbow.R", (-70, arm_swing_deg * phase, 0), frame=f)
    for f_off, side in ((half / 2, "R"), (half * 1.5, "L")):
        pose(arm_ob, "ankle." + side, (-knee_deg, 0, 0), frame=start + f_off)
    for side in ("L", "R"):
        for f_off in (0, frames):
            pose(arm_ob, "ankle." + side, (0, 0, 0), frame=start + f_off)
    if cycles:
        anim.cycle(arm_ob)
    return arm_ob
