"""Version compatibility layer. Import this instead of hard-coding API names.

Rules this module encodes (see references/compatibility.md):
* Check RNA properties with has_prop(), never hasattr(bpy.types.X, "prop").
* Dynamic enums (engine, view_transform, denoiser, ...) cannot be listed reliably
  through bl_rna in background mode; probe them by assignment (set_enum).
* Principled BSDF sockets were renamed in 4.0; use socket()/set_input().
"""
import bpy

V = tuple(bpy.app.version)  # e.g. (4, 5, 10)


def at_least(*ver):
    return V >= tuple(ver)


def has_prop(owner, name):
    """True if an RNA struct (instance or bpy.types class) has property `name`."""
    rna = getattr(owner, "bl_rna", None)
    return bool(rna) and name in rna.properties


def has_func(owner, name):
    """True if an RNA struct (instance or bpy.types class) has RNA function `name`.

    hasattr(bpy.types.Mesh, "set_sharp_from_angle") is False even where it exists.
    """
    rna = getattr(owner, "bl_rna", None)
    return bool(rna) and name in rna.functions


def set_enum(owner, prop, candidates):
    """Assign the first enum value Blender accepts. Returns the chosen value."""
    if isinstance(candidates, str):
        candidates = [candidates]
    errors = []
    for c in candidates:
        try:
            setattr(owner, prop, c)
            return c
        except (TypeError, ValueError) as e:
            errors.append("%s: %s" % (c, str(e).split("\n")[0][:120]))
    raise ValueError("No accepted value for %s.%s among %s | %s" % (
        type(owner).__name__, prop, candidates, " ; ".join(errors)))


def try_set(owner, prop, value):
    """setattr that returns False instead of raising if the property is missing/invalid."""
    if not has_prop(owner, prop):
        return False
    try:
        setattr(owner, prop, value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------- engines
ENGINE_CANDIDATES = {
    # 4.2-4.5: BLENDER_EEVEE_NEXT ; <4.2 legacy and >=5.0: BLENDER_EEVEE
    "EEVEE": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
    "CYCLES": ["CYCLES"],
    "WORKBENCH": ["BLENDER_WORKBENCH"],
}


def set_engine(scene, engine):
    key = engine.upper().replace("BLENDER_", "").replace("_NEXT", "")
    return set_enum(scene.render, "engine", ENGINE_CANDIDATES.get(key, [engine]))


def is_eevee(scene):
    return scene.render.engine.startswith("BLENDER_EEVEE")


# --------------------------------------------------------------------------- Principled BSDF
PRINCIPLED_ALIASES = {
    # canonical (4.x name): older / shorthand names
    "Base Color": ["color", "base_color", "albedo"],
    "Metallic": ["metal", "metallic"],
    "Roughness": ["rough", "roughness"],
    "IOR": ["ior"],
    "Alpha": ["alpha", "opacity"],
    "Normal": ["normal"],
    "Subsurface Weight": ["Subsurface", "sss", "subsurface"],
    "Subsurface Radius": ["sss_radius"],
    "Subsurface Scale": ["sss_scale"],
    "Specular IOR Level": ["Specular", "specular"],
    "Specular Tint": ["specular_tint"],
    "Anisotropic": ["anisotropic"],
    "Anisotropic Rotation": ["anisotropic_rotation"],
    "Transmission Weight": ["Transmission", "transmission"],
    "Coat Weight": ["Clearcoat", "coat", "clearcoat"],
    "Coat Roughness": ["Clearcoat Roughness", "coat_roughness"],
    "Coat Normal": ["Clearcoat Normal", "coat_normal"],
    "Coat Tint": ["coat_tint"],
    "Sheen Weight": ["Sheen", "sheen"],
    "Sheen Roughness": ["sheen_roughness"],
    "Sheen Tint": ["sheen_tint"],
    "Emission Color": ["Emission", "emission", "emission_color"],
    "Emission Strength": ["emission_strength"],
    "Thin Film Thickness": ["thin_film"],
}
def _norm(s):
    return s.lower().replace("_", " ").strip()


_ALIAS_TO_CANON = {}
for _canon, _alts in PRINCIPLED_ALIASES.items():
    _ALIAS_TO_CANON[_norm(_canon)] = _canon
    for _a in _alts:
        _ALIAS_TO_CANON[_norm(_a)] = _canon


def socket(node, name, output=False):
    """Find an *enabled* socket by name with Principled alias fallback.

    Matching order: exact name/identifier, then case/underscore-insensitive
    ("From_Min" finds "From Min"). Nodes with several same-named sockets of
    different types (Mix, Map Range) resolve to the enabled one.
    """
    coll = node.outputs if output else node.inputs
    names = [name]
    canon = _ALIAS_TO_CANON.get(_norm(name)) if node.bl_idname == "ShaderNodeBsdfPrincipled" else None
    if canon:
        names = [canon] + PRINCIPLED_ALIASES[canon] + [name]
    for exact in (True, False):
        for n in names:
            if exact:
                hits = [s for s in coll if s.name == n or s.identifier == n]
            else:
                hits = [s for s in coll if _norm(s.name) == _norm(n)]
            enabled = [s for s in hits if getattr(s, "enabled", True)]
            if enabled:
                return enabled[0]
            if hits:
                return hits[0]
    raise KeyError("%s has no %s socket %r. Available: %s" % (
        node.bl_idname, "output" if output else "input", name,
        [s.name for s in coll if getattr(s, "enabled", True)]))


def _coerce(sock, value):
    t = sock.type
    if t in ("RGBA",):
        if isinstance(value, (int, float)):
            return (value, value, value, 1.0)
        v = tuple(value)
        return v + (1.0,) if len(v) == 3 else v
    if t in ("VALUE", "INT") and isinstance(value, (tuple, list)):
        return value[0]
    return value


def set_input(node, name, value):
    s = socket(node, name)
    s.default_value = _coerce(s, value)
    return s


# --------------------------------------------------------------------------- shading
def shade_smooth(obj, angle_deg=None):
    """Smooth-shade a mesh. angle_deg -> keep edges sharper than angle (auto smooth).

    4.1+ removed Mesh.use_auto_smooth; uses Mesh.set_sharp_from_angle instead.
    """
    import math
    me = obj.data
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if angle_deg is not None:
        if hasattr(me, "set_sharp_from_angle"):
            me.set_sharp_from_angle(angle=math.radians(angle_deg))
        elif has_prop(me, "use_auto_smooth"):
            me.use_auto_smooth = True
            me.auto_smooth_angle = math.radians(angle_deg)
    me.update()


def shade_flat(obj):
    me = obj.data
    me.polygons.foreach_set("use_smooth", [False] * len(me.polygons))
    me.update()


def set_blend_mode(mat, mode="BLEND"):
    """Transparency mode across EEVEE Legacy (blend_method) and EEVEE Next (surface_render_method)."""
    if has_prop(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED" if mode == "BLEND" else "DITHERED"
    if has_prop(mat, "blend_method"):
        try_set(mat, "blend_method", {"BLEND": "BLEND", "HASHED": "HASHED", "OPAQUE": "OPAQUE"}.get(mode, mode))


# --------------------------------------------------------------------------- node groups
def new_interface_socket(tree, name, in_out="INPUT", socket_type="NodeSocketFloat",
                         default=None, min_value=None, max_value=None, description=""):
    """Create a group-interface socket (4.0+ tree.interface, 3.x tree.inputs/outputs)."""
    if has_prop(tree, "interface"):
        s = tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type,
                                      description=description)
    else:  # Blender 3.x
        coll = tree.inputs if in_out == "INPUT" else tree.outputs
        s = coll.new(socket_type, name)
    if default is not None and hasattr(s, "default_value"):
        s.default_value = default
    if min_value is not None and hasattr(s, "min_value"):
        s.min_value = min_value
    if max_value is not None and hasattr(s, "max_value"):
        s.max_value = max_value
    return s


def interface_items(tree, in_out="INPUT"):
    if has_prop(tree, "interface"):
        return [i for i in tree.interface.items_tree
                if getattr(i, "item_type", "SOCKET") == "SOCKET" and i.in_out == in_out]
    return list(tree.inputs if in_out == "INPUT" else tree.outputs)


def set_modifier_input(mod, name, value):
    """Set a Geometry Nodes modifier input by its interface *name*."""
    for item in interface_items(mod.node_group, "INPUT"):
        if item.name == name:
            key = item.identifier
            cur = mod[key] if key in mod.keys() else None
            if cur is not None and hasattr(cur, "__len__") and not isinstance(cur, str):
                mod[key] = tuple(value)
            else:
                mod[key] = value
            mod.id_data.update_tag()
            return key
    raise KeyError("Modifier %s has no input %r. Inputs: %s" % (
        mod.name, name, [i.name for i in interface_items(mod.node_group, "INPUT")]))


# --------------------------------------------------------------------------- compositor
def compositor_tree(scene, create=True):
    """Return the compositor node tree. <5.0: scene.node_tree ; 5.0+: compositing_node_group."""
    if has_prop(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree
    if create:
        scene.use_nodes = True
    return scene.node_tree


# --------------------------------------------------------------------------- animation
def action_fcurves(action, slot=None):
    """All F-curves of an action, for legacy (<4.4) and layered/slotted (4.4+) actions."""
    if action is None:
        return []
    layers = getattr(action, "layers", None)
    if layers is not None and len(layers):
        out = []
        for layer in layers:
            for strip in layer.strips:
                bags = strip.channelbags if slot is None else [strip.channelbag(slot)]
                for bag in bags:
                    if bag is not None:
                        out.extend(bag.fcurves)
        return out
    return list(getattr(action, "fcurves", []))


def id_fcurves(idblock):
    ad = getattr(idblock, "animation_data", None)
    if not ad or not ad.action:
        return []
    return action_fcurves(ad.action, getattr(ad, "action_slot", None))


# --------------------------------------------------------------------------- context
def override(**kw):
    """Context override usable as `with override(active_object=o, selected_objects=[o]):`."""
    return bpy.context.temp_override(**kw)


def summary():
    return {"version": bpy.app.version_string, "tuple": V,
            "eevee_id": ENGINE_CANDIDATES["EEVEE"][0] if (4, 2) <= V < (5, 0) else "BLENDER_EEVEE",
            "layered_actions": has_prop(bpy.types.Action, "layers"),
            "node_interface": has_prop(bpy.types.NodeTree, "interface"),
            "compositor_group": has_prop(bpy.types.Scene, "compositing_node_group")}
