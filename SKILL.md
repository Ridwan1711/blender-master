---
name: blender-master
description: "Production Blender via Python: modeling, materials, Geometry Nodes, lighting, Cycles/EEVEE renders, animation, rigging, physics, QA, export. Use for .blend files, bpy scripts, 3D scenes."
---

# Blender Master

**Use this skill when** the user wants anything made, changed, rendered, animated, inspected,
debugged or exported in Blender: 3D objects and assets (hard-surface, products, props), materials
and shaders, Geometry Nodes / procedural environments, lighting and cameras, Cycles or EEVEE
renders and turntables, animation, rigging, physics (rigid body, cloth), fixing or auditing a
`.blend`, bpy scripting, or exports (GLB/FBX/OBJ/USD). Needs a local Blender install (tested on
4.5 LTS; other versions go through the `compat` layer - probe first) and a shell.

You operate Blender as a senior 3D generalist / technical artist. Everything runs through
`scripts/bk.py`, which launches Blender headless, injects the tested `bkit` library, returns
structured JSON and keeps full logs. `SKILL_DIR` below = the directory containing this file.

**Core belief: a script that exits 0 has proven nothing about the picture.** Every visual task
ends with measured QA (`validate`, `imgcheck`) **and** you looking at rendered images.

## 1. Session start (do once)

```bash
python SKILL_DIR/scripts/bk.py which          # finds Blender (or set BLENDER_PATH)
python SKILL_DIR/scripts/bk.py probe          # version, engines, GPU, features  (+ -- --bench)
```
- Version not 4.5.x? Read `references/compatibility.md` before writing code.
- No Blender found? Ask the user for the path; do not download installers without permission.
- Working on the user's existing `.blend`? `bk.py inspect file.blend` first. Never save over it:
  write `name_v001.blend` (`save(path, version=True)`) unless the user explicitly says overwrite.

## 2. The production loop (complex tasks)

1. **Brief** - restate the visual target: subject, style (photoreal/stylised), shot, deliverables.
2. **Constraints** - real-world scale, poly budget tier, engine, resolution, time budget, version.
3. **Plan** - list assets, materials, lights, camera(s), the order of build scripts and checks.
4. **Technique** - pick tools from the routing table (section 5); prefer tested `bkit` helpers.
5. **Build** - small scripts, one concern each, run with `bk.py run ... --save new.blend`.
6. **Inspect** - `bk.py validate` (data) + `bk.py preview` (multi-view contact sheet) + **Read the PNG**.
7. **Find defects** - geometry, scale, intersections, materials, light, composition (see
   `references/workflow-qa.md` checklist). Numbers and eyes; neither alone.
8. **Iterate** - fix causes, not symptoms; re-run the same checks.
9. **Validate final** - `validate` passes (0 errors, warnings fixed or justified), `imgcheck` OK.
10. **Deliver** - the `.blend` (+ renders/exports) with paths, what was verified, what was not.

Small tasks (one object, one fix) compress this loop but never skip 6 for visual work.

## 3. Commands

```bash
B="python SKILL_DIR/scripts/bk.py"
$B run build.py --save out/scene.blend [--blend in.blend] [--overwrite] [-- script args]
$B exec "import bpy; ..." --blend in.blend          # quick one-liners / probes
$B inspect  scene.blend [--health] [--intersections]  # what is really in the file
$B validate scene.blend [--tier mobile|game|hero|film] [--purpose preview|final] [--strict]
$B preview  scene.blend --out DIR [--views camera,persp,front,right,top] [--mode material|clay|random|wire] [--beauty]
$B render   scene.blend --out out/shot.png [--quality preview|draft|final] [--engine cycles|eevee] [--res WxH]
$B render   scene.blend --out out/frames/f_ --frames 1-96 --video out/shot.mp4
$B imgcheck out/shot.png                              # exposure, clipping, fireflies, flatness
python SKILL_DIR/scripts/pipeline.py spec.json --out OUT   # spec -> build -> QA -> render -> export
$B run SKILL_DIR/scripts/export_blend.py --blend s.blend -- --out out/model.glb --subjects
```
Exit codes: 0 ok, 1 error (JSON `error` has type, message, failing line), 2 timeout, 3 setup.
Long renders: run in the background; estimate first (`render.estimate`) on slow hardware.

## 4. Build-script template

```python
from bkit import scene as S, mesh as M, materials as MT, lighting as L, camera as C, render as R
from bkit import preview as P, validate as V, emit

S.new_scene()                                   # ONLY in new files - wipes objects
body = M.box("GEO_Body", (0.8, 0.5, 0.5), origin="BOTTOM", coll="Props")   # metres, scale stays 1
M.hard_surface_finish(body, bevel_width=0.003)  # bevel -> weld -> weighted normals
MT.assign(body, MT.painted_metal("MAT_Paint", MT.hex_color("#D9822B")))
body["bk_subject"] = True                       # tells framing/QA what must be in shot
cam = C.add("CAM_Main", lens=50); C.frame(cam, [body], azimuth=-35, elevation=20, margin=1.25)
L.studio_backdrop(cam, [body]); L.three_point([body], style="product")
R.configure(engine="CYCLES", quality="draft", resolution=(1280, 960), view="AgX")
emit(tris=M.stats(body)["tris"])                # appears in bk.py's result JSON
```
Then: `bk.py validate` -> `bk.py preview --mode wire` -> Read sheet -> `bk.py render` -> Read render.

## 5. Routing table

| Task | Read | bkit modules |
|---|---|---|
| Any scripting, errors, headless quirks | `references/python-api.md` | runtime, compat |
| Version differences, missing APIs | `references/compatibility.md` | compat |
| Objects, hard-surface, booleans, topology, UVs | `references/modeling.md` | mesh, scene |
| Shaders, PBR textures, colour, glass, procedural materials | `references/materials.md` | materials |
| Procedural assets/environments, scattering, Geometry Nodes | `references/geometry-nodes.md` | geonodes, assets |
| Lights, world/sky/HDRI, exposure, camera, composition | `references/lighting-camera.md` | lighting, camera, render.auto_exposure |
| Engines, samples, devices, compositor, output, video | `references/rendering.md` | render, video, preview |
| Keyframes, camera moves, rigs, IK, skinning, walk cycles | `references/animation-rigging.md` | anim, rig, camera |
| Rigid bodies, cloth, collisions, baking | `references/physics.md` | physics |
| Naming, collections, linking/appending, budgets, speed | `references/scene-performance.md` | scene, inspect |
| QA method, defect catalogue, definition of done | `references/workflow-qa.md` | inspect, validate, preview |
| Something is wrong (script or picture) | `references/troubleshooting.md` | - |
| Batch/declarative scenes, export with verification | this file s.3, `examples/spec_desk.json` | build_from_spec, pipeline |

## 6. Hard rules (each one cost a real defect during testing)

1. **Never overwrite or destroy user data without explicit permission.** No saving over the
   opened file, no `S.new_scene()`/purge/apply-modifiers on user files, no deleting their objects.
   Work on copies (`--save new.blend`), version files, keep modifier stacks live.
2. **Look at the result.** Read the contact sheet / render PNG after each significant step.
   Validation caught intersections and doubles; only eyes caught backdrop edges, mirrored arms,
   black glass, washed-out colours, blocked shots.
3. **Absolute paths only** when handing paths to Blender (bare relative paths resolve against
   the drive root on Windows). bkit absolutises; your own code must too.
4. **`matrix_world` is stale** after setting location/rotation until `S.refresh()` or a depsgraph
   evaluation. Parenting with keep-transform on stale matrices snaps objects to the origin.
5. **Dimensions in mesh data, object scale 1.** Bevel/solidify/booleans assume applied scale.
6. **Data API first; operators only with `compat.override(...)`**. Some operators cannot run
   headless at all (list in `python-api.md`) - bkit has data-API replacements.
7. **Probe, don't assume:** `compat.has_prop/has_func` (not `hasattr` on `bpy.types`), enums by
   assignment (`compat.set_enum`), engine ids via `compat.set_engine`.
8. **Meter exposure, don't guess light energy:** put a grey card in, `R.auto_exposure(card)`.
9. **Cameras that move need the set to cover the whole path** - check a frame strip
   (`preview.frames`) not just frame 1; `studio_backdrop(..., frames=(a, b))`.
10. **Seed every random choice** and expose it (scatter seeds, asset seeds) - results must be reproducible.
11. **Real-world scale** (metres): a mug is 0.095 m tall, a door 2.1 m. Lights, DOF, physics and
    bevels all depend on it.
12. **Report honestly:** what was verified (numbers + images), what was not, known limitations.

## 7. Definition of done (visual deliverable)

- [ ] `validate` -> 0 errors; every warning fixed or explicitly justified to the user
- [ ] Contact sheet reviewed: silhouette, proportions, scale, no floating/sunk/intersecting parts
- [ ] Final render reviewed at full size; `imgcheck` verdict OK (or intentional low/high key)
- [ ] Composition: subject fill sensible, no frame-edge accidents, horizon/headroom deliberate
- [ ] Materials read correctly under the chosen view transform (AgX vs Khronos for product colour)
- [ ] Animation: frame strip reviewed, `anim.motion_report` shows no pops, video decodes
- [ ] Files saved to new paths; user's originals untouched; deliverable paths reported

## 8. Limits to state up front

- Headless Blender cannot show the live viewport; inspection is via renders (Workbench previews
  take seconds). For GUI-only tasks use computer-use screenshots if available, else instruct the user.
- Procedural stand-in assets (`bkit.assets`) are stylised; photoreal organics need real assets
  (user libraries, Poly Haven with permission to download, or paid generators with cost approval).
- Tested on Blender 4.5.10 LTS (Windows). 5.x paths in `compat` follow release notes but are
  untested - probe and verify (`references/compatibility.md`).

## 9. Maintaining this skill

After changing `bkit` or a script: `python SKILL_DIR/tests/run_tests.py --quick` (API smoke test +
9 scenarios + pipeline, ~10 min) and look at `tests/output/run/overview.png`. New Blender version:
run the suite there and update `references/compatibility.md` with what the probe and tests show.
`tests/TESTING.md` records every defect the tests found - add new ones the same way.
