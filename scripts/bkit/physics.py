"""Physics: rigid bodies, cloth, collisions; headless simulation and baking.

Simulations are evaluated by stepping frames in order (the point cache fills as you go).
Never jump straight to frame N of an unbaked sim - step from the start frame.
For deterministic files, bake_to_keyframes() converts a rigid-body result into plain keys.

    from bkit import physics as P
    P.rigid_world(frame_end=120)
    P.rigid(floor, "PASSIVE", shape="MESH")
    for b in boxes: P.rigid(b, "ACTIVE", mass=2.0)
    P.simulate(1, 120)
    P.settle_report(boxes, floor_z=0.0)
"""
import bpy

from . import compat


def _ov(ob):
    vl = bpy.context.view_layer
    vl.objects.active = ob
    return compat.override(active_object=ob, object=ob, selected_objects=[ob],
                           selected_editable_objects=[ob], scene=bpy.context.scene)


def rigid_world(frame_start=1, frame_end=250, substeps=10, iterations=10, gravity=None):
    sc = bpy.context.scene
    if sc.rigidbody_world is None:
        with compat.override(scene=sc):
            bpy.ops.rigidbody.world_add()
    w = sc.rigidbody_world
    compat.try_set(w, "substeps_per_frame", substeps)
    compat.try_set(w, "solver_iterations", iterations)
    w.point_cache.frame_start = frame_start
    w.point_cache.frame_end = frame_end
    if gravity is not None:
        sc.gravity = gravity
    return w


def rigid(ob, kind="ACTIVE", mass=1.0, shape="CONVEX_HULL", friction=0.5, bounce=0.1, margin=0.001,
          damping=(0.04, 0.1), kinematic=False):
    """Add a rigid body. shape: BOX | SPHERE | CAPSULE | CYLINDER | CONE | CONVEX_HULL | MESH.
    CONVEX_HULL/primitives for movers; MESH only for passive concave colliders (terrain).
    Floors: a slab with real thickness + BOX is the robust default.
    To check 'did anything fall through', measure with world_bounds(..., exact=True):
    bound-box corners of a rotated body overstate its extent (S09 reported a phantom
    7 cm 'sink' for a rolling ball until exact bounds were used)."""
    with _ov(ob):
        bpy.ops.rigidbody.object_add(type=kind)
    rb = ob.rigid_body
    rb.collision_shape = shape
    rb.friction = friction
    rb.restitution = bounce
    rb.use_margin = True
    rb.collision_margin = margin
    if kind == "ACTIVE":
        rb.mass = mass
        rb.linear_damping, rb.angular_damping = damping
    rb.kinematic = kinematic
    return rb


def collision(ob, thickness_outer=0.01, friction=5.0):
    """Collider for cloth/soft body/particles."""
    m = ob.modifiers.get("Collision") or ob.modifiers.new("Collision", "COLLISION")
    ob.collision.thickness_outer = thickness_outer
    ob.collision.cloth_friction = friction
    return m


def cloth(ob, quality=10, mass=0.3, stiffness=15.0, pin_group=None, self_collision=False,
          frame_start=1, frame_end=120, collision_quality=4, distance_min=0.006):
    """Cloth modifier (quality/collision slightly above Blender defaults for stable contact).

    If you see single-frame spikes, check the stack BEFORE blaming the sim: Solidify with
    Even Thickness after Cloth throws spikes at sharp folds (S09: that was the real cause).
    Use solidify(..., even=False) on cloth."""
    m = ob.modifiers.new("Cloth", "CLOTH")
    s = m.settings
    s.quality = quality
    s.mass = mass
    s.tension_stiffness = s.compression_stiffness = stiffness
    if pin_group:
        s.vertex_group_mass = pin_group
    cs = m.collision_settings
    cs.use_self_collision = self_collision
    cs.collision_quality = collision_quality
    cs.distance_min = distance_min
    m.point_cache.frame_start = frame_start
    m.point_cache.frame_end = frame_end
    return m


def simulate(frame_start=None, frame_end=None):
    """Step every frame in order so caches fill (works headless, no bake operator needed)."""
    sc = bpy.context.scene
    fs = frame_start or sc.frame_start
    fe = frame_end or sc.frame_end
    for f in range(fs, fe + 1):
        sc.frame_set(f)
    return fe - fs + 1


def bake_to_keyframes(objs, frame_start, frame_end, step=1):
    """Convert simulated rigid bodies to plain keyframes (rigid body removed). Deterministic.

    Data-API implementation: bpy.ops.rigidbody.bake_to_keyframes FAILS headless (it calls
    anim.keyframe_insert_by_name, whose poll needs a UI context - no override fixes it).
    Records matrix_world per frame, detaches the bodies, keys loc/rot with Euler continuity.
    """
    objs = list(objs)
    sc = bpy.context.scene
    rec = {o.name: [] for o in objs}
    for f in range(frame_start, frame_end + 1):
        sc.frame_set(f)
        if (f - frame_start) % step == 0 or f == frame_end:
            for o in objs:
                rec[o.name].append((f, o.matrix_world.copy()))
    for o in objs:
        with _ov(o):
            bpy.ops.rigidbody.object_remove()
    for o in objs:
        o.rotation_mode = "XYZ"
        prev = None
        for f, m in rec[o.name]:
            loc, rot, _ = m.decompose()
            e = rot.to_euler("XYZ", prev) if prev is not None else rot.to_euler("XYZ")
            prev = e
            o.location = loc
            o.rotation_euler = e
            o.keyframe_insert("location", frame=f)
            o.keyframe_insert("rotation_euler", frame=f)
    sc.frame_set(frame_start)
    return {o.name: len(rec[o.name]) for o in objs}


def settle_report(objs, floor_z=0.0, tol=0.01):
    """Positions at the current frame: anything below the floor (tunnelled) or exploded?"""
    from . import mesh as _mesh
    out = {"below_floor": [], "max_height": -1e9, "moved": 0, "deepest_sink": 0.0}
    for o in objs:
        mn, mx, _, c = _mesh.world_bounds([o], exact=True)  # bbox corners are loose when rotated
        out["deepest_sink"] = round(min(out["deepest_sink"], mn.z - floor_z), 4)
        if mn.z < floor_z - tol:
            out["below_floor"].append(o.name)
        out["max_height"] = max(out["max_height"], mx.z)
        start = o.get("bk_start")
        if start is not None and (c - __import__("mathutils").Vector(start)).length > 0.05:
            out["moved"] += 1
    out["max_height"] = round(out["max_height"], 3)
    return out


def remember_start(objs):
    from . import mesh as _mesh
    for o in objs:
        o["bk_start"] = list(_mesh.world_bounds([o])[3])
