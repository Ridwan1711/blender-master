# Troubleshooting: symptom -> cause -> fix

Start with the facts: `bk.py` result JSON (`error.type`, `error.message`, `error.where`), the
full log path it prints, `bk.py inspect`, and a render/preview you have actually looked at.

## Script / API errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `bk run` FAILED, `where` points at your line | ordinary Python error | read message; inspect the data you assumed exists |
| `KeyError: bpy_prop_collection[key]: key "X" not found` | name differs (`.001` suffix, renamed, never created) | keep references to returned objects; `bk.py inspect` to list names |
| `... has no input 'Specular'` (socket KeyError) | renamed sockets (Principled 4.0) or wrong node | `compat.set_input/socket` (aliases); error lists available sockets |
| `enum "BLENDER_EEVEE" not found` | engine id differs by version | `compat.set_engine(scene, "EEVEE")` |
| `hasattr(bpy.types.X, "prop")` False though prop exists | RNA props/functions aren't class attributes | `compat.has_prop` / `compat.has_func` |
| enum list via `bl_rna...enum_items` shows 1 item | dynamic enums are stubs on bl_rna in background | probe by assignment: `compat.set_enum` |
| `Operator ... poll() failed, context is incorrect` | operator needs active object/selection/area | `with compat.override(active_object=o, selected_objects=[o], ...)`, or data API |
| poll fails even with override (e.g. `rigidbody.bake_to_keyframes`) | operator internally calls UI-only operators | use bkit data-API replacement (`physics.bake_to_keyframes`) |
| `RuntimeError` in edit-mode op | wrong mode / no active object | `rig._mode(ob, "EDIT")` pattern; return to OBJECT before save |
| Script "works" but nothing saved | no `--save` and no `save()` | add `--save out.blend` |
| `Refusing to overwrite` | safety guard | new path, `version=True`, or `--overwrite` only with user consent |
| Process TIMEOUT | heavy render/sim | lower res/samples, `render.estimate`, run in background with larger `--timeout` |
| No result marker, crash | Blender crashed (GPU OOM, segfault in addon) | read full log tail; retry with `BKIT_DEVICE=CPU`, factory startup |
| Files appear in `C:\something` | bare relative path resolved against drive root | absolute paths (`render.abspath`) |

## Geometry

| Symptom | Cause | Fix |
|---|---|---|
| Object jumped to origin after parenting | stale `matrix_world` | `scene.refresh()` first (bkit.parent does) |
| Dark smudges on flat faces | bad normals after booleans/bevel | `weighted_normals` last in stack; smooth shading; recalc normals |
| Inside-out look / black faces in EEVEE | inverted normals | `validate` GEO_NORMALS_INVERTED -> `mesh.recalc_normals` |
| Bevel looks wrong / huge | unapplied object scale | `mesh.apply_transform(ob)` |
| Doubles/zero faces after bevel | bevel width too large for features | width < 0.4 x smallest feature + Weld (`hard_surface_finish`) |
| Boolean did nothing | cutter not overlapping / non-manifold cutter / FAST solver | EXACT solver, closed cutter, check cutter location |
| Boolean cutter visible in render | not hidden | `mesh.boolean` hides; validate CUTTER_RENDERS |
| Texture stretched | missing/poor UVs | `box_uv`, `smart_uv`, or Object-coordinate procedural shaders |

## Look / render

| Symptom | Cause | Fix |
|---|---|---|
| Black render | no camera / no lights + black world / camera inside geometry | validate CAM_NONE/LIGHT_NONE; check camera clip/position |
| Flat grey image (imgcheck FLAT) | empty frame, camera pointing away | `camera.frame`, check `subject_fill` |
| Over/under exposed | guessed energies | `R.auto_exposure(grey_card)`; calibration table in rendering.md |
| Washed pastel colours | AgX on bright saturated colours | lower exposure, Punchy look, or Khronos PBR Neutral |
| Fireflies (imgcheck NOISY) | small bright lights, caustics, glossy paths | clamp indirect (bkit: 10), denoise, bigger lights, more samples |
| Glass black | full smooth shading on thin-walled glass (most likely), overlapping refractive volumes, too few bounces | isolate: flat-shade it; angle-limited smoothing; separate volumes; bounces >= 8 |
| Edge of backdrop visible | backdrop not built for this camera/path | `studio_backdrop(cam, objs, frames=...)` after camera setup |
| EEVEE first frame very slow | shader compilation | normal; following frames fast (S05: 38 s first, ~4 s/frame) |
| EEVEE looks different from Cycles | no Bevel-node wear, screen-space effects | accept or use Cycles for final; enable raytracing |
| Video encode fails | odd resolution for H.264 | even width/height (`render.output_video` checks) |
| Encoded video looks washed | sequence tone-mapped twice in the VSE scene | encode with view transform Standard (`video.encode_sequence` does) |
| Previews look hazy | compositor (mist/glare) applied to Workbench previews | previews disable compositing (bkit does) |

## Animation / rigging / physics

| Symptom | Cause | Fix |
|---|---|---|
| IK chain does not bend | straight rest pose | pre-bend joint toward pole |
| Mirrored limbs move differently | inconsistent bone rolls | deterministic rolls (`rig.armature`) |
| Skinned mesh tears / rotates around far point | mesh offset from rig (moved twice) | move the armature only; re-bind if needed |
| `Bone Heat Weighting: failed` in log | non-manifold/overlapping mesh | clean mesh, merge by distance, or manual `bind_groups` |
| Camera "pops" | keyframe mistakes, constraint flips | `anim.motion_report` -> pops_at_frames |
| Sim result differs between runs | not stepping from frame 1 / cache invalid | `physics.simulate(1, N)` then bake to keys |
| Cloth spikes | solidify even thickness on cloth | `even=False` |
| Objects "below floor" by several cm | bbox measurement on rotated bodies | `world_bounds(exact=True)` before concluding tunnelling |
| Real tunnelling | thin colliders, fast bodies | slab floors with BOX, more substeps, bigger margins |

## When stuck

1. Reduce: reproduce in a tiny `bk.py exec` against the saved `.blend`.
2. Measure the intermediate state (per modifier stage, per frame, per node) - see the debugging
   snippets in `python-api.md`.
3. Compare against the version matrix (`compatibility.md`) and the probe output.
4. Tell the user what you tried and what you measured if you cannot resolve it.
