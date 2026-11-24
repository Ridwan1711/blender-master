# Geometry Nodes & procedural generation

## Builder (`from bkit import geonodes as G`)

```python
g = G.GN("GN_Wave")                       # new GeometryNodeTree, cleared
geo = g.geometry_io()                     # Geometry input + output on the interface
amp = g.input("Amplitude", "NodeSocketFloat", 0.3, 0.0, 5.0)   # exposed on the modifier
x, y, z = g.separate(g.position())
off = g.combine(0.0, 0.0, g.math("MULTIPLY", g.math("SINE", x), amp))
sp = g.node("GeometryNodeSetPosition", {"Geometry": geo, "Offset": off})
g.finish(sp.outputs["Geometry"])          # links to output + auto layout
mod = g.attach(obj)
G.set_inputs(mod, Amplitude=0.5)          # by interface NAME (identifiers are Socket_N)
```
- `g.node(idname, {input: value_or_socket}, **props)` - props (e.g. `data_type`, `operation`,
  `distribute_method`, `transform_space`) are set BEFORE inputs because they change which sockets exist.
- Helpers: `math`, `vmath`, `map_range`, `random(data_type, lo, hi, seed)`, `compare`, `bool_and`,
  `noise`, `position`, `separate`, `combine`.
- Object/collection inputs: `g.input("Target", "NodeSocketObject")`, then `compat.set_modifier_input`.

## Recipes (verified in S03)

| Recipe | What | Exposed inputs |
|---|---|---|
| `G.terrain(name, size, resolution, height, scale, seed, lake_center, lake_radius, lake_depth, mountain_height, material)` | fBm hills + smooth lake basin + ridged mountains toward +Y | all of them |
| `G.scatter(name, target, collection_or_object, density, seed, scale, max_slope_deg, min_height, max_height, align, clump_scale, clump_threshold, avoid, avoid_radius)` | instances on the evaluated target surface, separate object | Density, Seed, Scale Min/Max, Max Slope, Min/Max Height, Align, Clump Scale/Threshold, Avoid Object/Radius |
| `G.instance_grid(name, obj, count, spacing, jitter, seed)` | regular arrays of props | - |

Scatter design: Object Info (relative) -> Distribute Points on Faces (random, density factor from
clump noise) -> selection = slope AND height AND outside avoid radius -> Instance on Points (pick
random child of the collection, random scale) -> align to blended up/normal -> random spin (Rotate
Instances, local). Instances stay instances: S03 rendered 12.9k instances / 810k tris in 40 s.

## Procedural environment method (S03)

1. Asset library: `bkit.assets` variants into sub-collections of a render-hidden `Assets` collection
   (one collection per scatter layer: Pines, Broadleaf, Rocks, Grass, Bushes).
2. Terrain GN + slope/height material (`MT.terrain`).
3. Measure the generated world (raycast `evaluated_get(dg).ray_cast`) - water level from the lake
   floor, shoreline by walking outward - and place water, camera, clear zones from measurements.
4. Scatter layers with ecological rules: trees above water + margin, below tree line, slope < 30 deg,
   clumped; rocks on steep ground aligned to normals; grass dense, low; clear zone at the camera.
5. Camera at eye height on measured ground; horizon in the upper third; mist pass for depth.
6. Workbench preview (camera + top) before any Cycles time.

## Rules

- **Every random source takes a seed** and the seed is an input. Same seed = same world.
- Keep generation and instances separate objects so each layer can be toggled/re-seeded.
- Realize Instances only when exporting or when per-instance editing is required (memory x N).
- Debug GN by measuring evaluated output: `inspect.evaluated_tris()` (instances count), raycasts,
  `ev.to_mesh()` vertex stats, attribute values via `me.attributes[name].data.foreach_get`.
- Hidden source collections still instance (collection `hide_render` hides only the originals);
  `inspect.renderable()` understands this.

## Version notes

Interface API (`tree.interface`) 4.0+; Align Rotation to Vector 4.2+ (Align Euler to Vector before);
Switch node `input_type`; for-each zone 4.3+; closures 5.0 - see compatibility.md. The recipes
pick the available node names.
