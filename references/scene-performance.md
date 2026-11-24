# Scene management & performance

## Organisation

| Prefix | Type | Prefix | Type |
|---|---|---|---|
| GEO_ | renderable geometry | CUT_ | boolean cutters (hidden in render) |
| LGT_ | lights | CTL_ | empties, controllers, targets |
| CAM_ | cameras | RIG_ | armatures |
| MAT_ | materials | GN_ | node groups |
| FX_ | sims, scatter systems | | |

- Collections per logical unit: `Props`, `Environment`, `Lighting`, `Cameras`, `Cutters`, `Assets`
  (render-hidden sources), `Rig`, `Character`. Environment-like collection names (environment,
  background, ground, sky, backdrop, terrain, set) are excluded from automatic subject detection.
- Assemblies: parent parts to a root (crate body, lamp base). Validation treats one assembly as
  one unit for intersections; moving the root moves everything.
- `scene.apply_naming()` adds missing prefixes; `validate` reports default names (`Cube.001`).
- `scene.purge_orphans()` before delivery (temporary cards/materials leave orphans).

## Files

- Never overwrite the user's file: `--save new.blend`, `save(path, version=True)` -> `name_v001.blend`.
- Reuse assets: `S.append(path, objects=[...])` (copy, editable) or `link=True` (reference, read-only;
  library overrides to edit). Children are not implied - list them or append the collection.
  S06 appended the S01 mug (3 objects, parenting preserved).
- Paths: make external files relative (`bpy.ops.file.make_paths_relative()`) or pack
  (`bpy.ops.file.pack_all()`) before handing a file to someone else. `validate` flags missing and
  absolute paths.
- Exports: `scripts/export_blend.py` (GLB/glTF, FBX, OBJ, USD) re-imports the result into an empty
  scene and compares triangle counts (S07 GLB: match). Game engines: GLB with applied modifiers,
  Y-up, metres; FBX with `apply_scale_options="FBX_SCALE_ALL"`.

## Polygon budgets (validate tiers, evaluated triangles)

| Tier | per object (own geometry) | whole scene |
|---|---|---|
| mobile | 5 k | 150 k |
| game | 40 k | 2 M |
| hero (default) | 400 k | 8 M |
| film | 3 M | 60 M |
Instances count toward the scene total, not the object budget (GN scatter objects).

## Performance levers

| Problem | Lever |
|---|---|
| Many copies | instancing: linked copies, collection instances, GN Instance on Points (S03: 12.9 k instances) |
| Heavy subdivision | viewport levels < render levels; adaptive subdivision (Cycles experimental) |
| Huge terrain | lower GN Resolution input for previews, raise for final |
| Slow Cycles | adaptive sampling + denoise, fewer bounces, clamp indirect, smaller render for look-dev, `R.estimate` |
| GPU out of memory | `BKIT_DEVICE=CPU`, simplify textures (`scene.render.use_simplify`, `simplify_subdivision_render`), texture size limits |
| EEVEE first frame slow | shader compilation; keep one process for the whole sequence |
| Slow Python | `foreach_get/set` + numpy, avoid per-element RNA access in big loops, bmesh for topology work |

## Measuring

`bk.py inspect scene.blend` -> counts, tris (incl. instances), images and their status, collections,
engine settings, per-object info. `inspect.evaluated_tris()` -> total / per object / own / instances.
