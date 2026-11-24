"""Materials: Principled builder, node-graph helper, procedural presets, PBR texture loader.

Colour rule: Principled colour inputs are LINEAR. Designers' hex/sRGB values must be
converted with hex_color()/srgb() or they come out washed out.

    from bkit import materials as MT
    red = MT.principled("MAT_RedPlastic", MT.hex_color("#C0392B"), roughness=0.35)
    MT.assign(obj, red)
    oak = MT.wood("MAT_Oak")
"""
import os
import re

import bpy

from . import compat


# --------------------------------------------------------------------------- colour
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb(r, g, b, a=1.0):
    """sRGB 0-1 (what colour pickers show) -> linear RGBA for node inputs."""
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), a)


def hex_color(h, a=1.0):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return srgb(r, g, b, a)


# Measured linear base colours for metals (F0 reflectance)
METALS = {
    "gold": (1.000, 0.766, 0.336), "silver": (0.972, 0.960, 0.915), "copper": (0.955, 0.638, 0.538),
    "aluminium": (0.913, 0.922, 0.924), "iron": (0.560, 0.570, 0.580), "chrome": (0.550, 0.556, 0.554),
    "brass": (0.910, 0.778, 0.423), "titanium": (0.542, 0.497, 0.449), "steel": (0.63, 0.62, 0.60),
}


# --------------------------------------------------------------------------- graph helper
class Nodes:
    """Thin helper over a node tree: create nodes, link by socket name, auto-layout.

        nt = Nodes(mat.node_tree)
        noise = nt.new("ShaderNodeTexNoise", Scale=8.0, Detail=6.0)
        nt.link(noise, "Fac", nt.bsdf, "Roughness")
    """

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    @property
    def bsdf(self):
        return next((n for n in self.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)

    @property
    def output(self):
        for n in self.nodes:
            if n.bl_idname in ("ShaderNodeOutputMaterial", "ShaderNodeOutputWorld") and n.is_active_output:
                return n
        return next((n for n in self.nodes if n.bl_idname.startswith("ShaderNodeOutput")), None)

    def new(self, idname, label=None, props=None, **inputs):
        n = self.nodes.new(idname)
        if label:
            n.label = label
        for k, v in (props or {}).items():
            setattr(n, k, v)
        for k, v in inputs.items():  # From_Min=0.2 -> socket "From Min"
            compat.set_input(n, k, v)
        return n

    def link(self, a, a_out, b, b_in):
        """a_out/b_in: socket name, index, or socket object."""
        sa = a.outputs[a_out] if isinstance(a_out, int) else (
            a_out if hasattr(a_out, "links") else compat.socket(a, a_out, output=True))
        sb = b.inputs[b_in] if isinstance(b_in, int) else (
            b_in if hasattr(b_in, "links") else compat.socket(b, b_in))
        return self.links.new(sa, sb)

    def ramp(self, stops, interpolation="LINEAR"):
        """ColorRamp with [(pos, (r,g,b[,a])), ...] stops (colours linear)."""
        n = self.nodes.new("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = interpolation
        while len(cr.elements) > len(stops):
            cr.elements.remove(cr.elements[-1])
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = tuple(col) + (1.0,) * (4 - len(col))
        return n

    def mix_color(self, blend="MIX", fac=0.5, a=None, b=None):
        """Mix node in RGBA mode (4.x ShaderNodeMix). Returns (node, in_A, in_B, out)."""
        n = self.nodes.new("ShaderNodeMix")
        n.data_type = "RGBA"
        n.blend_type = blend
        ins = [s for s in n.inputs if s.type == "RGBA"]
        out = [s for s in n.outputs if s.type == "RGBA"][0]
        n.inputs["Factor"].default_value = fac
        if a is not None:
            ins[0].default_value = tuple(a) + (1.0,) * (4 - len(a))
        if b is not None:
            ins[1].default_value = tuple(b) + (1.0,) * (4 - len(b))
        return n, ins[0], ins[1], out

    def layout(self, dx=260, dy=190):
        """Arrange nodes in columns by distance from the output (readable for humans)."""
        out = self.output
        if out is None:
            return
        depth = {out: 0}
        frontier = [out]
        while frontier:
            nxt = []
            for n in frontier:
                for s in n.inputs:
                    for l in s.links:
                        m = l.from_node
                        d = depth[n] + 1
                        if depth.get(m, -1) < d:
                            depth[m] = d
                            nxt.append(m)
            frontier = nxt
        cols = {}
        for n, d in depth.items():
            cols.setdefault(d, []).append(n)
        for d, ns in cols.items():
            for i, n in enumerate(ns):
                n.location = (-d * dx, -i * dy + (len(ns) - 1) * dy / 2)


# --------------------------------------------------------------------------- core builders
def new_material(name, reuse=True):
    m = bpy.data.materials.get(name) if reuse else None
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m


def principled(name, color=(0.8, 0.8, 0.8), roughness=0.5, metallic=0.0, reuse=False, **inputs):
    """Material with one Principled BSDF. Extra inputs accept 4.x names or aliases:
    coat=1, coat_roughness=.05, transmission=1, ior=1.45, sss=.2, sheen=.5,
    emission=(1,.5,.2), emission_strength=4, alpha=.5, specular=.5, anisotropic=.6
    """
    m = new_material(name, reuse=reuse)
    nt = Nodes(m.node_tree)
    b = nt.bsdf
    if b is None:
        m.node_tree.nodes.clear()
        b = nt.new("ShaderNodeBsdfPrincipled")
        o = nt.new("ShaderNodeOutputMaterial")
        nt.link(b, "BSDF", o, "Surface")
    compat.set_input(b, "Base Color", color)
    compat.set_input(b, "Roughness", roughness)
    compat.set_input(b, "Metallic", metallic)
    for k, v in inputs.items():
        compat.set_input(b, k, v)
    if inputs.get("alpha", 1.0) < 1.0 or inputs.get("Alpha", 1.0) < 1.0:
        compat.set_blend_mode(m, "HASHED")
    _viewport_color(m, color, roughness, metallic)
    return m


def _viewport_color(m, color, roughness=0.5, metallic=0.0):
    """Solid/Workbench colour so clay previews still read the material."""
    c = tuple(color)[:3]
    m.diffuse_color = c + (1.0,)
    m.roughness = roughness
    m.metallic = metallic


def assign(ob, mat, slot=None, faces=None):
    """Append (or set slot) material; faces=list of polygon indices to assign to it."""
    mats = ob.data.materials
    if slot is None:
        idx = next((i for i, m in enumerate(mats) if m == mat), None)
        if idx is None:
            mats.append(mat)
            idx = len(mats) - 1
    else:
        while len(mats) <= slot:
            mats.append(None)
        mats[slot] = mat
        idx = slot
    if faces is not None:
        polys = ob.data.polygons
        for i in faces:
            polys[i].material_index = idx
    return idx


# --------------------------------------------------------------------------- presets
def metal(name, kind="steel", roughness=0.25, color=None, anisotropic=0.0):
    c = color or METALS.get(kind, METALS["steel"])
    return principled(name, c, roughness=roughness, metallic=1.0, anisotropic=anisotropic)


def brushed_metal(name, kind="aluminium", roughness=0.3, scale=60.0):
    """Anisotropic metal with streaky roughness (object-space stretched noise)."""
    m = metal(name, kind, roughness, anisotropic=0.7)
    nt = Nodes(m.node_tree)
    tc = nt.new("ShaderNodeTexCoord")
    mp = nt.new("ShaderNodeMapping", Scale=(scale * 0.01, scale * 4, scale * 4))
    nz = nt.new("ShaderNodeTexNoise", Scale=6.0, Detail=12.0, Roughness=0.7)
    mr = nt.new("ShaderNodeMapRange", From_Min=0.3, From_Max=0.7, To_Min=roughness * 0.85,
                To_Max=roughness * 1.15)
    nt.link(tc, "Object", mp, "Vector")
    nt.link(mp, "Vector", nz, "Vector")
    nt.link(nz, "Fac", mr, "Value")
    nt.link(mr, "Result", nt.bsdf, "Roughness")
    nt.layout()
    return m


def plastic(name, color=(0.8, 0.1, 0.1), roughness=0.35):
    return principled(name, color, roughness=roughness, specular=0.5)


def rubber(name, color=(0.02, 0.02, 0.02)):
    return principled(name, color, roughness=0.85, specular=0.3)


def ceramic(name, color=(0.9, 0.88, 0.82), roughness=0.12, coat=0.6):
    return principled(name, color, roughness=roughness, coat=coat, coat_roughness=0.03, sss=0.02)


def glass(name, color=(1, 1, 1), roughness=0.0, ior=1.45):
    m = principled(name, color, roughness=roughness, transmission=1.0, ior=ior)
    m.diffuse_color = (0.7, 0.85, 0.9, 0.35)
    compat.try_set(m, "use_screen_refraction", True)    # legacy EEVEE
    compat.try_set(m, "use_raytrace_refraction", True)  # EEVEE Next
    return m


def emissive(name, color=(1.0, 0.6, 0.2), strength=10.0, base=(0.02, 0.02, 0.02)):
    m = principled(name, base, roughness=0.5, emission=color, emission_strength=strength)
    m.diffuse_color = tuple(color[:3]) + (1.0,)
    return m


def car_paint(name, color=(0.5, 0.0, 0.02), metallic=0.5, roughness=0.35):
    return principled(name, color, roughness=roughness, metallic=metallic, coat=1.0,
                      coat_roughness=0.02)


def painted_metal(name, color=(0.7, 0.35, 0.02), wear=0.5, metal_kind="steel", roughness=0.45,
                  edge_width=0.006, grime=0.25):
    """Paint over metal with worn edges (Cycles Bevel-node edge mask; EEVEE shows clean paint)
    and subtle roughness/grime breakup. wear 0..1 controls how much metal shows.
    edge_width (m) should be ~1-2x the geometric bevel width."""
    m = principled(name, color, roughness=roughness)
    nt = Nodes(m.node_tree)
    b = nt.bsdf
    bev = nt.new("ShaderNodeBevel", Radius=edge_width)
    compat.try_set(bev, "samples", 8)
    geo = nt.new("ShaderNodeNewGeometry")
    dot = nt.new("ShaderNodeVectorMath", props={"operation": "DOT_PRODUCT"})
    # flat faces: dot = 1 ; near edges the rounded bevel normal diverges (dot < 1)
    edge = nt.new("ShaderNodeMapRange", From_Min=0.9995, From_Max=0.975, To_Min=0.0, To_Max=1.0)
    tc = nt.new("ShaderNodeTexCoord")
    nz = nt.new("ShaderNodeTexNoise", Scale=35.0, Detail=10.0, Roughness=0.7)
    mul = nt.new("ShaderNodeMath", props={"operation": "MULTIPLY"})
    lo = 0.05 + 0.3 * (1.0 - wear)
    thr = nt.new("ShaderNodeMapRange", From_Min=lo, From_Max=lo + 0.08)
    mixc, ca, cb, cout = nt.mix_color(a=color, b=METALS.get(metal_kind, METALS["steel"]))
    rgh = nt.new("ShaderNodeMapRange", To_Min=roughness, To_Max=0.28)
    gnz = nt.new("ShaderNodeTexNoise", Scale=6.0, Detail=6.0)
    gmix = nt.new("ShaderNodeMapRange", To_Min=1.0 - grime, To_Max=1.0)
    dark, da, db, dout = nt.mix_color("MULTIPLY", 1.0)
    nt.link(bev, "Normal", dot, 0)
    nt.link(geo, "Normal", dot, 1)
    nt.link(dot, "Value", edge, "Value")
    nt.link(tc, "Object", nz, "Vector")
    nt.link(edge, "Result", mul, 0)
    nt.link(nz, "Fac", mul, 1)
    nt.link(mul, "Value", thr, "Value")
    nt.link(thr, "Result", mixc, "Factor")
    nt.link(thr, "Result", b, "Metallic")
    nt.link(thr, "Result", rgh, "Value")
    nt.link(rgh, "Result", b, "Roughness")
    nt.link(tc, "Object", gnz, "Vector")
    nt.link(gnz, "Fac", gmix, "Value")
    nt.links.new(cout, da)
    nt.links.new(gmix.outputs["Result"], db)  # float -> colour socket = grey multiplier
    nt.links.new(dout, compat.socket(b, "Base Color"))
    nt.layout()
    return m


def fabric(name, color=(0.25, 0.3, 0.5), weave_scale=400.0):
    m = principled(name, color, roughness=0.85, sheen=1.0, sheen_roughness=0.4, specular=0.25)
    nt = Nodes(m.node_tree)
    tc = nt.new("ShaderNodeTexCoord")
    wv = nt.new("ShaderNodeTexWave", Scale=weave_scale, Distortion=1.0, Detail=1.0)
    wv2 = nt.new("ShaderNodeTexWave", Scale=weave_scale, Distortion=1.0, Detail=1.0)
    wv2.bands_direction = "Y"
    add = nt.new("ShaderNodeMath", props={"operation": "MULTIPLY"})
    bump = nt.new("ShaderNodeBump", Strength=0.25, Distance=0.002)
    nt.link(tc, "UV", wv, "Vector")
    nt.link(tc, "UV", wv2, "Vector")
    nt.link(wv, "Fac", add, 0)
    nt.link(wv2, "Fac", add, 1)
    nt.link(add, "Value", bump, "Height")
    nt.link(bump, "Normal", nt.bsdf, "Normal")
    nt.layout()
    return m


def wood(name, light=(0.45, 0.24, 0.10), dark=(0.18, 0.08, 0.03), scale=3.0, roughness=0.45,
         coord="Object", grain="BANDS", axis="X"):
    """Procedural wood, no UVs needed.

    grain="BANDS": plank grain along `axis` (tables, floors, boxes) - noise stretched ~25x along
    the grain gives IRREGULAR line spacing (a periodic wave read as ribbed plastic in S06).
    grain="RINGS": concentric end grain for turned objects (bowls, balls).
    scale ~2-3 = fine furniture grain; lower = coarser.
    """
    m = principled(name, light, roughness=roughness)
    nt = Nodes(m.node_tree)
    tc = nt.new("ShaderNodeTexCoord")
    s = scale * 8.0
    if grain == "BANDS":
        stretch = {"X": (s * 0.04, s, s), "Y": (s, s * 0.04, s), "Z": (s, s, s * 0.04)}[axis]
        mp = nt.new("ShaderNodeMapping", Scale=stretch)
        g = nt.new("ShaderNodeTexNoise", Scale=1.0, Detail=12.0, Roughness=0.62, Distortion=0.4)
        nt.link(tc, coord, mp, "Vector")
        nt.link(mp, "Vector", g, "Vector")
        grain_out = g.outputs["Fac"]
        # plank-scale colour variation (broad, soft)
        mp2 = nt.new("ShaderNodeMapping", Scale=tuple(v * 0.06 for v in stretch))
        broad = nt.new("ShaderNodeTexNoise", Scale=1.0, Detail=2.0)
        nt.link(tc, coord, mp2, "Vector")
        nt.link(mp2, "Vector", broad, "Vector")
        mix = nt.new("ShaderNodeMath", props={"operation": "MULTIPLY_ADD"})
        mix.inputs[1].default_value = 0.35
        nt.links.new(broad.outputs["Fac"], mix.inputs[0])
        nt.links.new(grain_out, mix.inputs[2])
        fac = nt.new("ShaderNodeMapRange", From_Min=0.45, From_Max=1.05)  # spread to 0..1
        nt.links.new(mix.outputs[0], compat.socket(fac, "Value"))
        pattern = compat.socket(fac, "Result", output=True)
    else:
        mp = nt.new("ShaderNodeMapping", Scale=(scale, scale, scale))
        nz = nt.new("ShaderNodeTexNoise", Scale=1.2, Detail=5.0, Roughness=0.55)
        warped = nt.new("ShaderNodeVectorMath", props={"operation": "ADD"})
        amp = nt.new("ShaderNodeVectorMath", props={"operation": "SCALE"})
        amp.inputs["Scale"].default_value = 0.06
        wv = nt.new("ShaderNodeTexWave", Scale=6.0, Distortion=3.0, Detail=3.0, Detail_Scale=1.5)
        wv.wave_type = "RINGS"
        wv.wave_profile = "SAW"
        nt.link(tc, coord, mp, "Vector")
        nt.link(mp, "Vector", nz, "Vector")
        nt.link(nz, "Color", amp, 0)
        nt.link(mp, "Vector", warped, 0)
        nt.link(amp, "Vector", warped, 1)
        nt.link(warped, "Vector", wv, "Vector")
        pattern = wv.outputs["Fac"]
    mid = tuple(0.5 * (a + b) for a, b in zip(dark, light))
    rp = nt.ramp([(0.0, dark), (0.3, mid), (0.6, light), (1.0, light)])
    rgh = nt.new("ShaderNodeMapRange", To_Min=roughness + 0.08, To_Max=roughness - 0.06)
    bump = nt.new("ShaderNodeBump", Strength=0.012, Distance=0.004)
    nt.links.new(pattern, compat.socket(rp, "Fac"))
    nt.link(rp, "Color", nt.bsdf, "Base Color")
    nt.links.new(pattern, compat.socket(rgh, "Value"))
    nt.link(rgh, "Result", nt.bsdf, "Roughness")
    nt.links.new(pattern, compat.socket(bump, "Height"))
    nt.link(bump, "Normal", nt.bsdf, "Normal")
    nt.layout()
    _viewport_color(m, light, roughness)
    return m


def marble(name, base=(0.85, 0.84, 0.82), vein=(0.18, 0.18, 0.2), scale=2.0, roughness=0.08):
    m = principled(name, base, roughness=roughness, coat=0.3)
    nt = Nodes(m.node_tree)
    tc = nt.new("ShaderNodeTexCoord")
    nz = nt.new("ShaderNodeTexNoise", Scale=scale, Detail=12.0, Roughness=0.65, Distortion=2.5)
    wv = nt.new("ShaderNodeTexWave", Scale=scale * 0.8, Distortion=12.0, Detail=8.0)
    rp = nt.ramp([(0.0, vein), (0.08, base), (1.0, base)], interpolation="EASE")
    nt.link(tc, "Object", nz, "Vector")
    nt.link(nz, "Color", wv, "Vector")
    nt.link(wv, "Fac", rp, "Fac")
    nt.link(rp, "Color", nt.bsdf, "Base Color")
    nt.layout()
    return m


def concrete(name, color=(0.42, 0.41, 0.39), roughness=0.85, scale=6.0):
    m = principled(name, color, roughness=roughness)
    nt = Nodes(m.node_tree)
    tc = nt.new("ShaderNodeTexCoord")
    nz = nt.new("ShaderNodeTexNoise", Scale=scale, Detail=10.0, Roughness=0.7)
    vr = nt.new("ShaderNodeTexVoronoi", Scale=scale * 8)
    c2 = tuple(x * 0.7 for x in color[:3])
    rp = nt.ramp([(0.3, c2), (0.7, color)])
    bump = nt.new("ShaderNodeBump", Strength=0.15, Distance=0.02)
    mul = nt.new("ShaderNodeMath", props={"operation": "MULTIPLY"})
    nt.link(tc, "Object", nz, "Vector")
    nt.link(tc, "Object", vr, "Vector")
    nt.link(nz, "Fac", rp, "Fac")
    nt.link(rp, "Color", nt.bsdf, "Base Color")
    nt.link(nz, "Fac", mul, 0)
    nt.link(vr, "Distance", mul, 1)
    nt.link(mul, "Value", bump, "Height")
    nt.link(bump, "Normal", nt.bsdf, "Normal")
    nt.layout()
    return m


def terrain(name, grass=(0.05, 0.12, 0.02), dirt=(0.13, 0.08, 0.04), rock=(0.22, 0.21, 0.2),
            snow=None, slope_start=0.75, slope_end=0.6, snow_height=None):
    """Slope/height-blended landscape shader (Geometry normal Z + Position Z), no UVs needed."""
    m = principled(name, grass, roughness=0.9)
    nt = Nodes(m.node_tree)
    geo = nt.new("ShaderNodeNewGeometry")
    sep = nt.new("ShaderNodeSeparateXYZ")
    nz = nt.new("ShaderNodeTexNoise", Scale=1.5, Detail=8.0)
    mixgd, ga, gb, gout = nt.mix_color(a=grass, b=dirt)
    slope = nt.new("ShaderNodeMapRange", From_Min=slope_start, From_Max=slope_end, To_Min=0.0, To_Max=1.0)
    mixr, ra, rb, rout = nt.mix_color(b=rock)
    nt.link(geo, "Normal", sep, "Vector")
    nt.link(nz, "Fac", mixgd, "Factor")
    nt.link(sep, "Z", slope, "Value")
    nt.link(slope, "Result", mixr, "Factor")
    nt.links.new(gout, ra)
    last = rout
    if snow is not None and snow_height is not None:
        pos = nt.new("ShaderNodeSeparateXYZ")
        nt.link(geo, "Position", pos, "Vector")
        sh = nt.new("ShaderNodeMapRange", From_Min=snow_height, From_Max=snow_height + 0.5)
        nt.link(pos, "Z", sh, "Value")
        mixs, sa, sb, sout = nt.mix_color(b=snow)
        nt.links.new(rout, sa)
        nt.link(sh, "Result", mixs, "Factor")
        last = sout
    nt.links.new(last, compat.socket(nt.bsdf, "Base Color"))
    bump = nt.new("ShaderNodeBump", Strength=0.3, Distance=0.05)
    nz2 = nt.new("ShaderNodeTexNoise", Scale=25.0, Detail=6.0)
    nt.link(nz2, "Fac", bump, "Height")
    nt.link(bump, "Normal", nt.bsdf, "Normal")
    nt.layout()
    return m


def water(name, color=(0.6, 0.8, 0.85), roughness=0.03, wave_scale=8.0):
    m = principled(name, color, roughness=roughness, transmission=1.0, ior=1.333)
    nt = Nodes(m.node_tree)
    nz = nt.new("ShaderNodeTexNoise", Scale=wave_scale, Detail=4.0)
    bump = nt.new("ShaderNodeBump", Strength=0.15, Distance=0.05)
    nt.link(nz, "Fac", bump, "Height")
    nt.link(bump, "Normal", nt.bsdf, "Normal")
    nt.layout()
    m.diffuse_color = (0.2, 0.4, 0.5, 0.6)
    return m


# --------------------------------------------------------------------------- PBR texture sets
_MAPS = {
    "base": r"(basecolor|base_color|albedo|diffuse|diff|_col|color)",
    "rough": r"(roughness|rough|_rgh)",
    "metal": r"(metallic|metalness|metal|_mtl)",
    "normal": r"(normal|_nor|_nrm|nor_gl|nor_dx)",
    "ao": r"(ambientocclusion|_ao|occlusion)",
    "height": r"(height|displacement|_disp|bump)",
    "alpha": r"(opacity|alpha|mask)",
    "emit": r"(emission|emissive)",
}


def find_texture_set(folder):
    """Map role -> file path by filename convention (Poly Haven, ambientCG, Substance)."""
    found = {}
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp")):
            continue
        low = fn.lower()
        for role, pat in _MAPS.items():
            if role not in found and re.search(pat, low):
                found[role] = os.path.join(folder, fn)
                break
    return found


def pbr(name, maps, scale=1.0, normal_dx=None, displacement=0.0, coord="UV"):
    """Image-texture material. maps: folder path or {role: path}. Sets colour spaces correctly.

    normal_dx: True for DirectX normal maps (green flipped); default: guessed from filename.
    displacement > 0 adds true displacement (Cycles; set material displacement_method).
    """
    if isinstance(maps, str):
        maps = find_texture_set(maps)
    missing = [p for p in maps.values() if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError("Missing texture files: %s" % missing)
    m = principled(name, (0.8, 0.8, 0.8), roughness=0.5)
    nt = Nodes(m.node_tree)
    b = nt.bsdf
    tc = nt.new("ShaderNodeTexCoord")
    mp = nt.new("ShaderNodeMapping", Scale=(scale, scale, scale))
    nt.link(tc, coord, mp, "Vector")

    def tex(path, non_color):
        n = nt.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(path, check_existing=True)
        n.image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        nt.link(mp, "Vector", n, "Vector")
        return n

    if "base" in maps:
        t = tex(maps["base"], False)
        if "ao" in maps:
            ao = tex(maps["ao"], True)
            mix, a, bb, out = nt.mix_color("MULTIPLY", 1.0)
            nt.links.new(t.outputs["Color"], a)
            nt.links.new(ao.outputs["Color"], bb)
            nt.links.new(out, compat.socket(b, "Base Color"))
        else:
            nt.link(t, "Color", b, "Base Color")
    if "rough" in maps:
        nt.link(tex(maps["rough"], True), "Color", b, "Roughness")
    if "metal" in maps:
        nt.link(tex(maps["metal"], True), "Color", b, "Metallic")
    if "alpha" in maps:
        nt.link(tex(maps["alpha"], True), "Color", b, "Alpha")
        compat.set_blend_mode(m, "HASHED")
    if "emit" in maps:
        nt.link(tex(maps["emit"], False), "Color", b, "Emission Color")
        compat.set_input(b, "Emission Strength", 1.0)
    if "normal" in maps:
        nm = nt.new("ShaderNodeNormalMap", Strength=1.0)
        t = tex(maps["normal"], True)
        dx = normal_dx if normal_dx is not None else bool(re.search(r"(_dx|directx)", maps["normal"].lower()))
        if dx:  # flip green channel
            sep = nt.new("ShaderNodeSeparateColor")
            inv = nt.new("ShaderNodeMath", props={"operation": "SUBTRACT"})
            inv.inputs[0].default_value = 1.0
            comb = nt.new("ShaderNodeCombineColor")
            nt.link(t, "Color", sep, "Color")
            nt.link(sep, "Red", comb, "Red")
            nt.link(sep, "Green", inv, 1)
            nt.link(inv, "Value", comb, "Green")
            nt.link(sep, "Blue", comb, "Blue")
            nt.link(comb, "Color", nm, "Color")
        else:
            nt.link(t, "Color", nm, "Color")
        nt.link(nm, "Normal", b, "Normal")
    if "height" in maps and displacement > 0:
        d = nt.new("ShaderNodeDisplacement", Scale=displacement, Midlevel=0.5)
        nt.link(tex(maps["height"], True), "Color", d, "Height")
        nt.link(d, "Displacement", nt.output, "Displacement")
        if not compat.try_set(m, "displacement_method", "BOTH"):      # 4.1+
            compat.try_set(getattr(m, "cycles", None), "displacement_method", "BOTH")  # older
    nt.layout()
    return m
