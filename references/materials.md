# Materials & shader development

## Colour discipline

- Node colour inputs are **scene-linear**. Designers give sRGB (hex, picker values): convert with
  `MT.hex_color("#C0392B")` / `MT.srgb(r,g,b)`. Raw `(0.75, 0.22, 0.17)` typed from a hex reads washed out.
- Albedo ranges: charcoal 0.04, dark paint 0.05-0.1, mid-grey card 0.18, concrete 0.25-0.35, white
  paint 0.8-0.9. Avoid pure 0 or 1 base colours.
- Metals: base colour = measured F0 (`MT.METALS`: gold, silver, copper, aluminium, iron, chrome,
  brass, titanium, steel), metallic = 1. Metals look flat without an environment to reflect
  (gradient world, HDRI, or bright cards).
- The view transform changes how colours read (measured on S02): AgX desaturates bright saturated
  colours to pastel; Filmic shifts bright orange toward yellow; **Khronos PBR Neutral keeps product
  hues**. Choose deliberately (rendering.md).

## Presets (`from bkit import materials as MT`) - all verified in S04 renders

| Preset | Notes |
|---|---|
| `principled(name, color, roughness, metallic, **inputs)` | any Principled input by 4.x name or alias: `coat`, `transmission`, `ior`, `sss`, `sheen`, `emission`, `emission_strength`, `alpha`, `specular`, `anisotropic` |
| `metal(name, kind, roughness)` / `brushed_metal(...)` | brushed: anisotropic + gentle streak roughness |
| `plastic`, `rubber`, `ceramic` (coat), `car_paint` (metallic base + clear coat) | |
| `glass(name, color, roughness, ior)` | transmission 1; see glass rules |
| `emissive(name, color, strength)` | emission strength in W/m^2-ish units; 5-25 for glowing parts |
| `fabric(name, color, weave_scale)` | sheen + UV weave bump (needs UVs) |
| `wood(name, light, dark, scale, grain="BANDS"|"RINGS", axis="X")` | BANDS: stretched-noise plank grain along `axis` (irregular spacing - a periodic wave reads as ribbed plastic); RINGS: turned objects |
| `marble`, `concrete`, `terrain` (slope/height blend), `water` | Object/Geometry coordinates, no UVs |
| `painted_metal(name, color, wear, edge_width)` | Cycles Bevel-node edge wear (EEVEE shows clean paint) |
| `pbr(name, folder_or_maps, scale, normal_dx, displacement)` | image sets by filename convention |

Every preset also sets the viewport colour (`diffuse_color`) so Workbench previews read the material.

## Node graph helper

```python
m = MT.principled("MAT_X", MT.hex_color("#888888"))
nt = MT.Nodes(m.node_tree)
nz = nt.new("ShaderNodeTexNoise", Scale=8.0, Detail=6.0)      # inputs by name; From_Min -> "From Min"
mr = nt.new("ShaderNodeMapRange", To_Min=0.3, To_Max=0.6)
nt.link(nz, "Fac", mr, "Value"); nt.link(mr, "Result", nt.bsdf, "Roughness")
ramp = nt.ramp([(0.0, (0.1, 0.1, 0.1)), (1.0, (0.8, 0.8, 0.8))])
mix, a, b, out = nt.mix_color("MULTIPLY", 1.0)                 # 4.x ShaderNodeMix in RGBA mode
nt.layout()                                                    # readable columns for humans
```
Sockets with duplicate names (Mix, Map Range, Random Value) resolve to the enabled one; set
`data_type` before setting inputs. Use indices for Math node inputs (`nt.link(a, "Value", math, 0)`).

## Texture sets (`MT.pbr`)

- Colour space: base colour / emission = sRGB; roughness, metallic, normal, AO, height, opacity = Non-Color.
- Normal maps: OpenGL (Blender) vs DirectX (green flipped) - `normal_dx=True` or `_dx` in the filename.
- AO multiplies base colour (subtle); displacement needs geometry density and `displacement_method="BOTH"` (Cycles).
- Missing files raise immediately; validate flags missing/absolute paths; pack or make paths relative before delivery.

## Glass, liquids, transparency

- Glass needs real wall thickness (lathe: outside up, inside down) and transmission bounces >= 8.
- **Thin-walled glass must NOT be smoothed across its corners.** S06's tumbler rendered solid BLACK:
  smooth shading interpolated normals from the rim/base corners over the whole wall -> wrong
  refraction + total internal reflection. Isolation test: flat-shaded = clear, Glass BSDF = still
  black, more bounces = still black. Fix: angle-limited smoothing (`M.lathe` default 30 deg, or
  `compat.shade_smooth(ob, angle_deg=30)`), or bevelled corners with enough profile points.
- Liquids in glass: avoid overlapping refractive volumes; use an air gap, or the glass-liquid
  interface technique (liquid slightly larger than the inner wall, interface IOR 1.33/1.5).
- Alpha/cutouts: `compat.set_blend_mode(mat, "HASHED")` (EEVEE Next: DITHERED).

## Procedural coordinate choice

| Coordinates | Use |
|---|---|
| Object | stays attached when the object moves; scale-dependent; default in bkit presets |
| Generated | 0..1 over the bounding box; stretches on non-cube objects |
| UV | image textures, fabric weave, decals |
| World position (Geometry > Position) | terrain blends, snow lines, things that should stay in world space |
