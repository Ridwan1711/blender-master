"""Geometry Nodes from Python: a small builder plus tested recipes.

Builder style - nodes are created with inputs given as values OR sockets (sockets get linked):

    g = GN("GN_Wave")
    geo = g.geometry_io()                                  # Geometry in/out interface
    amp = g.input("Amplitude", "NodeSocketFloat", 0.3)
    pos = g.node("GeometryNodeInputPosition").outputs["Position"]
    sep = g.node("ShaderNodeSeparateXYZ", {"Vector": pos})
    z = g.math("SINE", sep.outputs["X"])
    off = g.node("ShaderNodeCombineXYZ", {"Z": g.math("MULTIPLY", z, amp)})
    sp = g.node("GeometryNodeSetPosition", {"Geometry": geo, "Offset": off.outputs[0]})
    g.finish(sp.outputs[0])
    mod = g.attach(obj)                       # modifier; set inputs by name:
    compat.set_modifier_input(mod, "Amplitude", 0.5)

Recipes: terrain(), scatter(), instance_grid(). All expose their knobs as modifier inputs,
so the result stays procedural and reproducible (seed inputs everywhere).
"""
import math

import bpy

from . import compat
from . import scene as _scene


class GN:
    def __init__(self, name, reuse=False):
        tree = bpy.data.node_groups.get(name) if reuse else None
        if tree is None:
            tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links
        self.nodes.clear()
        self.inp = self.nodes.new("NodeGroupInput")
        self.out = self.nodes.new("NodeGroupOutput")
        compat.try_set(tree, "is_modifier", True)
        self._geo_out = None

    # ---- interface
    def input(self, name, socket_type="NodeSocketFloat", default=None, min_value=None, max_value=None,
              description=""):
        compat.new_interface_socket(self.tree, name, "INPUT", socket_type, default, min_value, max_value,
                                    description)
        return self.inp.outputs[name]

    def output(self, name, socket_type="NodeSocketGeometry"):
        compat.new_interface_socket(self.tree, name, "OUTPUT", socket_type)
        return self.out.inputs[name]

    def geometry_io(self):
        """Create Geometry input + output; returns the incoming geometry socket."""
        g = self.input("Geometry", "NodeSocketGeometry")
        self._geo_out = self.output("Geometry", "NodeSocketGeometry")
        return g

    def finish(self, socket, name="Geometry"):
        if self._geo_out is None or name != "Geometry":
            self._geo_out = self.output(name, "NodeSocketGeometry")
        self.links.new(socket, self.out.inputs[name])
        self.layout()
        return self.tree

    # ---- nodes
    def node(self, idname, inputs=None, **props):
        """Create a node. props are set BEFORE inputs (data_type changes which sockets exist)."""
        n = self.nodes.new(idname)
        for k, v in props.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(n, k, v)
        return n

    def set(self, node, key, value):
        sock = node.inputs[key] if isinstance(key, int) else compat.socket(node, key)
        if hasattr(value, "is_output") and hasattr(value, "node"):  # a socket -> link
            self.links.new(value, sock)
        elif hasattr(value, "outputs") and hasattr(value, "bl_idname"):  # a node -> first output
            self.links.new(value.outputs[0], sock)
        else:
            if sock.type == "RGBA" and len(value) == 3:
                value = tuple(value) + (1.0,)
            sock.default_value = value
        return sock

    def link(self, a, b):
        return self.links.new(a, b)

    def math(self, op, a, b=None, c=None):
        n = self.node("ShaderNodeMath", operation=op)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set(n, i, v)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        if scale is not None:
            self.set(n, "Scale", scale)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]

    def map_range(self, value, from_min, from_max, to_min=0.0, to_max=1.0, interp="LINEAR", clamp=True):
        n = self.node("ShaderNodeMapRange", interpolation_type=interp, clamp=clamp)
        for k, v in (("Value", value), ("From Min", from_min), ("From Max", from_max),
                     ("To Min", to_min), ("To Max", to_max)):
            self.set(n, k, v)
        return n.outputs["Result"]

    def random(self, data_type="FLOAT", lo=0.0, hi=1.0, seed=0, id_socket=None):
        n = self.node("FunctionNodeRandomValue", data_type=data_type)
        self.set(n, "Min", lo)
        self.set(n, "Max", hi)
        self.set(n, "Seed", seed)
        if id_socket is not None:
            self.set(n, "ID", id_socket)
        return compat.socket(n, "Value", output=True)

    def compare(self, a, b, op="GREATER_THAN"):
        n = self.node("FunctionNodeCompare", data_type="FLOAT", operation=op)
        self.set(n, "A", a)
        self.set(n, "B", b)
        return n.outputs["Result"]

    def bool_and(self, a, b):
        n = self.node("FunctionNodeBooleanMath", operation="AND")
        self.set(n, 0, a)
        self.set(n, 1, b)
        return n.outputs[0]

    def position(self):
        return self.node("GeometryNodeInputPosition").outputs["Position"]

    def separate(self, vec):
        n = self.node("ShaderNodeSeparateXYZ", {"Vector": vec})
        return n.outputs["X"], n.outputs["Y"], n.outputs["Z"]

    def combine(self, x=0.0, y=0.0, z=0.0):
        n = self.node("ShaderNodeCombineXYZ", {"X": x, "Y": y, "Z": z})
        return n.outputs["Vector"]

    def noise(self, vector, scale=1.0, detail=4.0, roughness=0.5, distortion=0.0):
        n = self.node("ShaderNodeTexNoise", {"Vector": vector, "Scale": scale, "Detail": detail,
                                             "Roughness": roughness, "Distortion": distortion})
        n.noise_dimensions = "3D"
        return n.outputs["Fac"]

    # ---- finishing
    def layout(self, dx=220, dy=170):
        """Columns by longest distance from the output node."""
        depth = {self.out: 0}
        order = [self.out]
        i = 0
        while i < len(order):
            n = order[i]
            i += 1
            for s in n.inputs:
                for l in s.links:
                    m = l.from_node
                    d = depth[n] + 1
                    if depth.get(m, -1) < d:
                        depth[m] = d
                        order.append(m)
        if self.inp not in depth:
            depth[self.inp] = max(depth.values()) + 1
        depth[self.inp] = max(depth.values())
        cols = {}
        for n, d in depth.items():
            cols.setdefault(d, []).append(n)
        for d, ns in cols.items():
            for k, n in enumerate(ns):
                n.location = (-d * dx, -k * dy)

    def attach(self, obj, name=None):
        mod = obj.modifiers.new(name or self.tree.name, "NODES")
        mod.node_group = self.tree
        return mod


def set_inputs(mod, **values):
    """compat.set_modifier_input for several inputs; underscores map to spaces (Lake_Depth)."""
    names = {i.name for i in compat.interface_items(mod.node_group, "INPUT")}
    for k, v in values.items():
        key = k if k in names else k.replace("_", " ")
        compat.set_modifier_input(mod, key, v)
    return mod


# --------------------------------------------------------------------------- recipes
def terrain(name="GEO_Terrain", size=60.0, resolution=240, height=6.0, scale=0.045, seed=0,
            lake_center=(0.0, 4.0), lake_radius=9.0, lake_depth=2.5, mountain_height=14.0,
            coll="Environment", material=None):
    """Procedural terrain: fBm hills + optional lake basin + mountains rising toward +Y.
    All knobs are modifier inputs (Size, Resolution, Height, Scale, Seed, Lake *, Mountain Height).
    """
    me = bpy.data.meshes.new(name)
    ob = _scene.add_object(name, me, coll)
    g = GN("GN_" + name.replace("GEO_", ""))
    g.geometry_io()
    i_size = g.input("Size", "NodeSocketFloat", size, 1.0)
    i_res = g.input("Resolution", "NodeSocketInt", resolution, 2, 2000)
    i_h = g.input("Height", "NodeSocketFloat", height)
    i_sc = g.input("Scale", "NodeSocketFloat", scale)
    i_seed = g.input("Seed", "NodeSocketInt", seed)
    i_lc = g.input("Lake Center", "NodeSocketVector", (lake_center[0], lake_center[1], 0.0))
    i_lr = g.input("Lake Radius", "NodeSocketFloat", lake_radius, 0.0)
    i_ld = g.input("Lake Depth", "NodeSocketFloat", lake_depth)
    i_mh = g.input("Mountain Height", "NodeSocketFloat", mountain_height)

    grid = g.node("GeometryNodeMeshGrid", {"Size X": i_size, "Size Y": i_size,
                                            "Vertices X": i_res, "Vertices Y": i_res})
    pos = g.position()
    seed_off = g.combine(g.math("MULTIPLY", i_seed, 17.13), g.math("MULTIPLY", i_seed, 31.7), 0.0)
    p_seed = g.vmath("ADD", pos, seed_off)
    hills = g.noise(g.vmath("SCALE", p_seed, scale=i_sc), 1.0, 8.0, 0.55)
    h = g.math("MULTIPLY", g.math("SUBTRACT", hills, 0.5), i_h)
    # lake basin: smooth bowl around Lake Center
    x, y, _ = g.separate(pos)
    d = g.vmath("DISTANCE", g.combine(x, y, 0.0), i_lc)
    bowl = g.map_range(d, 0.0, i_lr, 1.0, 0.0, interp="SMOOTHSTEP")
    h = g.math("SUBTRACT", h, g.math("MULTIPLY", bowl, i_ld))
    # mountains: rise along +Y beyond 15% of the size, modulated by ridged noise
    half = g.math("MULTIPLY", i_size, 0.5)
    ramp = g.map_range(y, g.math("MULTIPLY", i_size, 0.15), half, 0.0, 1.0, interp="SMOOTHSTEP")
    ridge_n = g.noise(g.vmath("SCALE", p_seed, scale=g.math("MULTIPLY", i_sc, 2.2)), 1.0, 6.0, 0.6)
    ridge = g.math("SUBTRACT", 1.0, g.math("ABSOLUTE", g.math("SUBTRACT", g.math("MULTIPLY", ridge_n, 2.0), 1.0)))
    h = g.math("ADD", h, g.math("MULTIPLY", g.math("MULTIPLY", ramp, ridge), i_mh))
    sp = g.node("GeometryNodeSetPosition", {"Geometry": grid.outputs["Mesh"], "Offset": g.combine(0.0, 0.0, h)})
    sm = g.node("GeometryNodeSetShadeSmooth", {"Geometry": sp.outputs["Geometry"]})
    last = sm.outputs["Geometry"]
    if material is not None:
        last = g.node("GeometryNodeSetMaterial", {"Geometry": last, "Material": material}).outputs[0]
    g.finish(last)
    g.attach(ob, "Terrain")
    if material is not None:
        ob.data.materials.append(material)
    return ob


def scatter(name, target, instances, density=0.5, seed=0, scale=(0.7, 1.3), max_slope_deg=30.0,
            min_height=-1e6, max_height=1e6, align=0.0, clump_scale=0.0, clump_threshold=0.5,
            coll="Environment", avoid=None, avoid_radius=0.0):
    """Scatter `instances` (collection or object) over `target`'s evaluated surface.

    Creates a separate object (the target is not modified). Filters by slope and height,
    optional clumping noise (clump_scale > 0, e.g. 0.05 for forests). align: 0 = upright,
    1 = follow surface normal. avoid=<object> + avoid_radius keeps a clear zone (XY distance)
    around e.g. the camera or a path. Instances stay instances (memory-cheap). Inputs exposed on
    the modifier: Density, Seed, Scale Min/Max, Max Slope, Min/Max Height, Align, Clump *,
    Avoid Object, Avoid Radius.
    """
    me = bpy.data.meshes.new(name)
    ob = _scene.add_object(name, me, coll)
    g = GN("GN_" + name.replace("GEO_", "").replace("FX_", ""))
    g.geometry_io()
    i_den = g.input("Density", "NodeSocketFloat", density, 0.0)
    i_seed = g.input("Seed", "NodeSocketInt", seed)
    i_smin = g.input("Scale Min", "NodeSocketFloat", scale[0])
    i_smax = g.input("Scale Max", "NodeSocketFloat", scale[1])
    i_slope = g.input("Max Slope", "NodeSocketFloat", max_slope_deg, 0.0, 90.0)
    i_hmin = g.input("Min Height", "NodeSocketFloat", min_height)
    i_hmax = g.input("Max Height", "NodeSocketFloat", max_height)
    i_align = g.input("Align", "NodeSocketFloat", align, 0.0, 1.0)
    i_cs = g.input("Clump Scale", "NodeSocketFloat", clump_scale, 0.0)
    i_ct = g.input("Clump Threshold", "NodeSocketFloat", clump_threshold, 0.0, 1.0)

    info = g.node("GeometryNodeObjectInfo", {"Object": target}, transform_space="RELATIVE")
    # density factor from clumping noise (1 everywhere when Clump Scale == 0)
    n = g.noise(g.vmath("SCALE", g.position(), scale=i_cs), 1.0, 3.0, 0.5)
    clump = g.map_range(n, i_ct, g.math("ADD", i_ct, 0.12), 0.0, 1.0, interp="SMOOTHSTEP")
    use_clump = g.compare(i_cs, 0.0, "GREATER_THAN")
    sw = g.node("GeometryNodeSwitch", input_type="FLOAT")
    g.set(sw, "Switch", use_clump)
    g.set(sw, "False", 1.0)
    g.set(sw, "True", clump)
    dist = g.node("GeometryNodeDistributePointsOnFaces", {"Mesh": info.outputs["Geometry"],
                                                          "Density": i_den, "Seed": i_seed},
                  distribute_method="RANDOM")
    g.set(dist, "Density Factor", sw.outputs[0])
    # filters: slope (normal z) and height
    nz = g.separate(dist.outputs["Normal"])[2]
    cos_lim = g.math("COSINE", g.math("RADIANS", i_slope))
    ok_slope = g.compare(nz, cos_lim, "GREATER_EQUAL")
    px, py, pz = g.separate(g.position())
    ok_h = g.bool_and(g.compare(pz, i_hmin, "GREATER_EQUAL"), g.compare(pz, i_hmax, "LESS_EQUAL"))
    sel = g.bool_and(ok_slope, ok_h)
    i_av = g.input("Avoid Object", "NodeSocketObject")
    i_ar = g.input("Avoid Radius", "NodeSocketFloat", avoid_radius, 0.0)
    av = g.node("GeometryNodeObjectInfo", {"Object": i_av}, transform_space="RELATIVE")
    ax, ay, _ = g.separate(av.outputs["Location"])
    dxy = g.vmath("DISTANCE", g.combine(px, py, 0.0), g.combine(ax, ay, 0.0))
    sel = g.bool_and(sel, g.compare(dxy, i_ar, "GREATER_THAN"))  # radius 0 -> no effect
    # instances
    if isinstance(instances, bpy.types.Collection):
        src = g.node("GeometryNodeCollectionInfo", {"Collection": instances, "Separate Children": True,
                                                    "Reset Children": True}, transform_space="ORIGINAL")
        n_children = max(1, len(instances.objects))
        pick = True
    else:
        src = g.node("GeometryNodeObjectInfo", {"Object": instances, "As Instance": True},
                     transform_space="ORIGINAL")
        n_children, pick = 1, False
    idx = g.random("INT", 0, n_children - 1, seed=seed + 7)
    s = g.random("FLOAT", i_smin, i_smax, seed=seed + 11)
    inst = g.node("GeometryNodeInstanceOnPoints", {"Points": dist.outputs["Points"], "Selection": sel,
                                                    "Instance": src.outputs[0], "Pick Instance": pick,
                                                    "Instance Index": idx, "Scale": s})
    # rotation: blend upright <-> surface-aligned, then random spin around local Z
    upright = g.combine(0.0, 0.0, 1.0)
    up = g.vmath("NORMALIZE", g.vmath("ADD", g.vmath("SCALE", upright, scale=g.math("SUBTRACT", 1.0, i_align)),
                                      g.vmath("SCALE", dist.outputs["Normal"], scale=i_align)))
    al = g.node("FunctionNodeAlignRotationToVector" if hasattr(bpy.types, "FunctionNodeAlignRotationToVector")
                else "FunctionNodeAlignEulerToVector", axis="Z")
    g.set(al, "Vector", up)
    g.set(inst, "Rotation", al.outputs[0])
    spin = g.combine(0.0, 0.0, g.random("FLOAT", 0.0, 2 * math.pi, seed=seed + 13))
    rot = g.node("GeometryNodeRotateInstances", {"Instances": inst.outputs["Instances"], "Rotation": spin,
                                                  "Local Space": True})
    g.finish(rot.outputs["Instances"])
    mod = g.attach(ob, "Scatter")
    if avoid is not None:
        compat.set_modifier_input(mod, "Avoid Object", avoid)
    return ob


def instance_grid(name, instance, count=(5, 5), spacing=(2.0, 2.0), jitter=0.0, seed=0, coll=None):
    """Regular grid of instances with optional jitter (crowds of props, columns, tiles)."""
    me = bpy.data.meshes.new(name)
    ob = _scene.add_object(name, me, coll)
    g = GN("GN_" + name)
    g.geometry_io()
    grid = g.node("GeometryNodeMeshGrid", {"Size X": spacing[0] * (count[0] - 1),
                                           "Size Y": spacing[1] * (count[1] - 1),
                                           "Vertices X": count[0], "Vertices Y": count[1]})
    pts = g.node("GeometryNodeMeshToPoints", {"Mesh": grid.outputs["Mesh"]})
    off = g.random("FLOAT_VECTOR", (-jitter, -jitter, 0.0), (jitter, jitter, 0.0), seed=seed)
    sp = g.node("GeometryNodeSetPosition", {"Geometry": pts.outputs["Points"], "Offset": off})
    src = g.node("GeometryNodeObjectInfo", {"Object": instance, "As Instance": True}, transform_space="ORIGINAL")
    inst = g.node("GeometryNodeInstanceOnPoints", {"Points": sp.outputs[0], "Instance": src.outputs["Geometry"]})
    g.finish(inst.outputs["Instances"])
    g.attach(ob, "Grid")
    return ob
