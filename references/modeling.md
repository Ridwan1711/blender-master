# Modeling & mesh engineering

## Principles

- **Metres, real sizes, object scale 1.** Build dimensions into mesh data (`bkit.mesh` builders do).
  Reference sizes: mug 0.095 h / 0.085 d; table top 0.74-0.76 m; chair seat 0.45; door 2.1 x 0.9;
  ceiling 2.5-3.0; person 1.75; car 4.5 x 1.8 x 1.45; A4 0.297 x 0.21.
- **Origin where it is used:** bottom-centre for things that stand (`origin="BOTTOM"`, `set_origin`),
  hinge points for things that rotate.
- **Non-destructive by default:** keep booleans/bevels/arrays live; apply only for export or when asked.
- **Name and file as you go:** `GEO_`, `CUT_`, collections per assembly (see scene-performance.md).

## Builder cheat sheet (`from bkit import mesh as M`)

| Need | Call |
|---|---|
| Box / slab / panel | `M.box(name, (x,y,z), location, origin="CENTER"/"BOTTOM")` |
| Cylinder, cone frustum, pipe stub | `M.cylinder(name, radius, depth, segments, radius_top=, cap=)` |
| Sphere | `M.sphere(name, radius, segments, rings)` / `ico=3` |
| Plane / grid | `M.plane(name, (x,y), subdivisions=)` |
| Torus / open arc (handles) | `M.torus(name, major, minor, arc=230, start_deg=-115)` |
| Turned objects (mug, vase, bottle, plate, glass) | `M.lathe(name, [(r,z), ...])` - walk outside up, inside down for wall thickness |
| Extruded outline (panels, logos, brackets, L-profiles) | `M.extrude_polygon(name, pts2d, depth)` + `M.rounded_rect(w,h,r)` |
| Pipes, cables, handles, rails | `M.curve_tube(name, points, radius, to_mesh=True)` |
| Many identical parts (bolts) | `M.linked_copy(src, name, location)` (shared mesh) or GN `instance_grid` |
| Measure | `M.world_bounds(objs[, exact=True])`, `M.stats(ob)` |

## Modifier stack order (hard-surface)

```
Mirror -> Array -> Boolean(s, EXACT) -> Bevel (angle) -> Weld -> [Subdivision] -> Weighted Normal (LAST)
```
`M.boolean(body, cutter)` hides the cutter (CUT_ prefix, Cutters collection, hide_render).
`M.hard_surface_finish(ob, bevel_width)` = Bevel(angle 35, harden normals, arc miter) + Weld + WeightedNormal.

**Bevel width rule (measured, S02):** width must stay below ~0.4 x the smallest feature (recess depth,
slot width, wall thickness). On an 8 mm recess, 3 mm was clean; 4 mm and up produced 96 duplicate
verts and 48 zero-area faces (opposite bevels clamping). Always check `mesh_health` after bevels.

## Hard-surface workflow

1. Blockout primary forms (boxes/cylinders), check proportions in `preview --mode clay`.
2. Secondary forms by boolean cutters (panel recesses, vents, holes). Arrays on cutters for repeats.
3. Finish stack; 3-6 mm bevels on 0.5-1 m objects read as manufactured edges.
4. Tertiary detail as separate parented parts (bolts, guards, handles, strips): parent to the body
   so the assembly moves together and intersection QA treats it as one unit.
5. `validate` (doubles, degenerate, intersections) + `preview --mode wire`.

## Organic / subdivision

- Quads, even spacing, support loops near creases; `M.subsurf(ob, 2)`; avoid poles on high-curvature areas.
- Lathe/skin modifier bases subdivide cleanly (S08 mannequin = skin modifier + subsurf).
- Sculpting is not practical headless; use displacement (Displace modifier with procedural textures,
  or `noise` jitter in bmesh like `bkit.assets.rock`) for organic surface variation.

## Topology & normals checks (`inspect.mesh_health`)

| Field | Meaning | Normal for |
|---|---|---|
| boundary_edges | open edges | planes, terrain, cloth (fine); solids should be 0 |
| multi_face_edges | >2 faces on an edge | never (internal faces) |
| inconsistent_normal_edges | neighbour faces flipped | never -> `recalc_normals` |
| inverted | closed mesh with inward normals | never |
| duplicate_verts, zero_area_faces | degenerate geometry | never (bevel/boolean issues) |
| ngons | faces > 4 verts | fine on flat boolean results with weighted normals; avoid under subdivision |

## UVs

- Procedural materials with Object/Generated coordinates need no UVs (wood, marble, concrete presets).
- Image textures need UVs: `M.box_uv(ob, scale)` (box projection by face normal, world-scaled, robust)
  or `M.smart_uv(ob)` (operator with override). Validate flags MAT_IMAGE_NO_UV.

## Known builder pitfalls (fixed in bkit, avoid in your own code)

- Full-radius rounded rectangles (slots/stadiums) create coincident arc endpoints -> dedupe points.
- Curve-to-mesh caps are not welded to the tube -> merge by distance after conversion.
- New bmesh faces have stale `.index` -> track with sets.
