"""Scene setup, collections, naming conventions and housekeeping.

Naming convention (validate.py checks it):
    GEO_  meshes / curves that render         LGT_  lights
    CAM_  cameras                             CTL_  empties / controllers
    RIG_  armatures                           FX_   simulation / helper geometry
    CUT_  boolean cutters (hidden in render)  MAT_  materials        GN_  node groups
Collections: one per logical unit, e.g. "Props", "Environment", "Lighting", "Cameras", "Cutters".
"""
import bpy

PREFIX = {"MESH": "GEO_", "CURVE": "GEO_", "SURFACE": "GEO_", "META": "GEO_", "FONT": "GEO_",
          "LIGHT": "LGT_", "CAMERA": "CAM_", "EMPTY": "CTL_", "ARMATURE": "RIG_",
          "CURVES": "GEO_", "POINTCLOUD": "GEO_", "VOLUME": "FX_", "GPENCIL": "GP_",
          "GREASEPENCIL": "GP_", "LIGHT_PROBE": "LGT_"}


def new_scene(units="METRIC", scale=1.0, fps=24, frame_range=(1, 120), keep=()):
    """Start from a clean slate in the CURRENT file: removes all objects except `keep`,
    then purges orphan data. Only call this on scratch/new files, never on user files.
    """
    sc = bpy.context.scene
    for ob in list(bpy.data.objects):
        if ob.name not in keep:
            bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        if not coll.objects and not coll.children:
            bpy.data.collections.remove(coll)
    purge_orphans()
    sc.unit_settings.system = units
    sc.unit_settings.scale_length = scale
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = frame_range
    sc.frame_set(frame_range[0])
    return sc


def purge_orphans(passes=4):
    """Remove datablocks with zero users (recursive). Returns count removed."""
    n = 0
    colls = ("meshes", "materials", "textures", "images", "node_groups", "curves", "lights",
             "cameras", "actions", "armatures", "worlds", "particles")
    for _ in range(passes):
        removed = 0
        for attr in colls:
            data = getattr(bpy.data, attr, None)
            if data is None:
                continue
            for block in list(data):
                if block.users == 0 and not block.use_fake_user:
                    data.remove(block)
                    removed += 1
        n += removed
        if not removed:
            break
    return n


def collection(name, parent=None):
    """Get or create a collection linked under parent (default: scene root)."""
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if isinstance(parent, str):
        parent = collection(parent)
    if coll.name not in [c.name for c in parent.children] and coll != parent:
        parent.children.link(coll)
    return coll


def move_to(obj, coll):
    """Link obj to exactly one collection."""
    if isinstance(coll, str):
        coll = collection(coll)
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


def add_object(name, data=None, coll=None, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
    """Create an object from datablock `data` (None -> empty) and link it."""
    ob = bpy.data.objects.new(name, data)
    ob.location, ob.rotation_euler, ob.scale = location, rotation, scale
    target = coll if coll is not None else bpy.context.scene.collection
    if isinstance(target, str):
        target = collection(target)
    target.objects.link(ob)
    return ob


def empty(name, coll=None, location=(0, 0, 0), display="PLAIN_AXES", size=1.0):
    ob = add_object(name, None, coll, location)
    ob.empty_display_type = display
    ob.empty_display_size = size
    return ob


def refresh():
    """Re-evaluate the depsgraph. matrix_world/bounds of objects you just moved are STALE
    until this (or evaluated_depsgraph_get()) runs."""
    bpy.context.view_layer.update()


def parent(child, par, keep_transform=True):
    refresh()  # matrix_world is stale right after setting location/rotation
    mw = child.matrix_world.copy()
    child.parent = par
    if keep_transform:
        child.matrix_parent_inverse = par.matrix_world.inverted()
        child.matrix_world = mw
    return child


def conventional_name(obj):
    return PREFIX.get(obj.type, "OBJ_")


def apply_naming(objs=None, dry_run=False):
    """Add the conventional prefix to objects that lack one. Returns {old: new}."""
    changes = {}
    for ob in objs or bpy.context.scene.objects:
        pre = conventional_name(ob)
        if not any(ob.name.startswith(p) for p in set(PREFIX.values()) | {"CUT_", "FX_", "OBJ_"}):
            new = pre + ob.name.replace(".", "_")
            changes[ob.name] = new
            if not dry_run:
                ob.name = new
    return changes


def hide(obj, render=True, viewport=True):
    obj.hide_render = render
    obj.hide_viewport = viewport
    obj.hide_set(viewport) if obj.name in bpy.context.view_layer.objects else None


def append(blend_path, objects=None, collections=None, materials=None, link=False, coll=None):
    """Append (copy) or link datablocks from another .blend. Returns the loaded objects.

    objects: names to bring in (children are NOT implied - list them, or append a collection).
    link=True keeps them read-only and referencing the source file (library overrides needed
    to edit); append for set dressing you will modify.
    """
    import os
    blend_path = os.path.abspath(blend_path)
    if not os.path.isfile(blend_path):
        raise FileNotFoundError(blend_path)
    with bpy.data.libraries.load(blend_path, link=link) as (src, dst):
        missing = [n for n in (objects or []) if n not in src.objects]
        if missing:
            raise KeyError("not in %s: %s (has %s)" % (blend_path, missing, list(src.objects)[:30]))
        if objects:
            dst.objects = list(objects)
        if collections:
            dst.collections = list(collections)
        if materials:
            dst.materials = list(materials)
    target = collection(coll) if isinstance(coll, str) else (coll or bpy.context.scene.collection)
    out = []
    for ob in dst.objects or []:
        if ob is not None and ob.name not in target.objects:
            target.objects.link(ob)
            out.append(ob)
    for c in dst.collections or []:
        if c is not None and c.name not in [x.name for x in target.children]:
            target.children.link(c)
            out += list(c.all_objects)
    return out


def set_frame_range(start, end, fps=None):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = start, end
    if fps:
        sc.render.fps = fps


def select_only(objs, active=None):
    """Selection for operators that need it. Prefer data-API helpers that need none."""
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    objs = [objs] if hasattr(objs, "name") else list(objs)
    for o in objs:
        o.select_set(True)
    vl.objects.active = active or (objs[0] if objs else None)
