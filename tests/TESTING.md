# Testing the Blender Master skill

## Method

The skill is only "done" where a capability was executed in a real Blender, measured, and
looked at. Each scenario in `tests/scenarios/` builds a scene in a fresh headless Blender process;
`tests/run_tests.py` then runs validation, scenario-specific numeric assertions, a render and an
exposure check, and tiles all renders into `overview.png` for visual review.

```bash
python tests/run_tests.py --quick            # ~5-8 min on the reference machine (small renders)
python tests/run_tests.py                    # full renders (S06 alone ~7 min on CPU)
python tests/run_tests.py --only s02,s05     # dependent scenarios pull their inputs (s05<-s02, s06<-s01)
```
Reference machine: Windows 11, Blender 4.5.10 LTS, Ryzen 7 1700 (16 threads), GTX 750 Ti 2 GB
(CUDA, no OptiX). Probe output: `tests/output/probe_4.5.json` (when present).

## Scenarios and pass criteria

| ID | Capability (mission test) | Numeric assertions | Visual review focus |
|---|---|---|---|
| s01 | basic 3D object (glazed mug) | validate >= 95, tris > 5k | proportions, handle seat, seamless studio |
| s02 | complex hard-surface (sci-fi crate) | validate = 100 (no doubles/degenerate/intersections) | bevel quality, recesses, part placement |
| s03 | procedural environment (GN terrain + 5 scatter layers) | > 5k instances, 0 errors | composition, ecology, clear shot |
| s04 | material-rich scene (12 presets + calibration cards) | grey card within 0.03 of target | each material reads correctly |
| s05 | cinematic animation (on top of s02's file) | no camera pops, EEVEE | frame strip: coverage, timing, cropping |
| s06 | photorealistic render (window-lit interior) | validate = 100, metered | realism: glass, wood, light, shadows |
| s07 | complete automated project (spec -> pipeline) | all stages ok, GLB re-import tris match | preview sheet |
| s08 | rigging & character animation | IK error < 1 cm, 0 unweighted verts | walk cycle strip |
| s09 | physics (rigid + cloth) | tower fell, no tunnelling, cloth on sphere, no spikes | rest state plausibility |

## Defects found by the tests (and fixed)

Each row was found by a validation number or by looking at a render - the reason the skill makes
both mandatory.

| # | Found in | How found | Root cause | Fix (where) |
|---|---|---|---|---|
| 1 | probe | probe output | `hasattr(bpy.types.X, prop)` false for RNA props/functions; dynamic enums stubbed | `compat.has_prop/has_func/set_enum` |
| 2 | s01 | validator: coffee/handle intersect floor | stale `matrix_world` in keep-transform parenting | `scene.parent` refreshes depsgraph |
| 3 | s01 | files appeared in `C:\tests\...` | Blender resolves bare relative paths against the drive root | absolute paths everywhere (`render.abspath`) |
| 4 | s01 | contact sheet: top view rotated 180 deg | `to_track_quat` ambiguous straight down | explicit top/bottom rotations in `camera.frame` |
| 5 | s01 | eyes: dark blob in frame corner | backdrop not sized/oriented for the camera | `lighting.studio_backdrop(cam, objs)` |
| 6 | s02 | validator: 24 then 96 doubles, 48 zero faces | bevel width >= half the 8 mm recess wall (measured per width) | `hard_surface_finish` + rule < 0.4 x feature |
| 7 | s02 | validator: 24 doubles on handles | curve fill caps not welded | merge after curve-to-mesh |
| 8 | s02 | validator: guards sunk 6 mm into floor | modelling mistake | fixed placement |
| 9 | s02 | eyes: pastel orange | AgX highlight desaturation (compared AgX/Punchy/Khronos/Filmic side by side) | Khronos PBR Neutral for product colour |
| 10 | s03 | eyes: camera inside a tree | scatter ignores camera | `scatter(avoid=, avoid_radius=)` |
| 11 | s03 | eyes: previews washed grey | mist compositor applied to Workbench | previews disable compositing |
| 12 | s03 | eyes: top view framed 5.5 m of nothing | hidden asset collection counted as subject | collection render-visibility check |
| 13 | s03 | eyes: bark colour bands on foliage | stale `BMFace.index` for new faces | track faces by set |
| 14 | s03 | eyes: lake not visible, mountains filling frame | camera placed by guess; layout | raycast shoreline placement, relayout |
| 15 | s03 | validator false positives on GN instancers | rules counted instances as own geometry / no material | `is_instancer`, own-vs-instanced tris |
| 16 | s04 | metric: grey card 0.68 (+1.6 EV) | rig energy guessed | calibrated rig + `render.auto_exposure` |
| 17 | s04 | validator: cards intersect floor | backdrop floor taken from the balls' lowest point | `studio_backdrop(floor_z=0)` |
| 18 | s04 | eyes: smeared brushed metal, burl wood, hidden labels | parameters / layout | tuned presets, row spacing |
| 19 | s05 | eyes: backdrop edge on the orbit; handle cropped at end | backdrop sized for one frame; dolly too close | `studio_backdrop(frames=)`; shorter push-in |
| 20 | s08 | metric: IK miss 0.40 m | straight rest chain | pre-bend (error 0.000 m) |
| 21 | s08 | eyes: one arm overhead | measured bone axes -> mesh offset twice (rig and child both moved) | `mannequin(location=)` moves the rig only; deterministic rolls |
| 22 | s09 | error: `rigidbody.bake_to_keyframes` poll fails headless | operator calls UI-only operator internally | data-API bake |
| 23 | s09 | metric: cloth spikes on single frames | Solidify even thickness on folds (not the sim) | `solidify(even=False)` |
| 24 | s09 | metric: ball "sinks" 5-10 cm | rotated bounding boxes overstate extent | `world_bounds(exact=True)` |
| 25 | s06 | eyes: glass renders black | full smooth shading on a thin wall (isolated with 4 A/B renders) | lathe angle-limited smoothing |
| 26 | s06/s09 | eyes: camouflage, then corrugated/ribbed wood (3 iterations) | noise colour fed into a wave; then a periodic wave reads as ribbed plastic | `MT.wood` BANDS = noise stretched ~25x along the grain + plank-scale variation; RINGS kept for turned wood |

| 27 | s09 | validator: 13 "deep" intersections in a settled pile (score 44) | plane-straddle depth is meaningless for perpendicular faces crossing in a thin sliver; then nearest-normal inside test misfired at box edges | sample intersecting faces, inside test by ray parity (closed) / normal sign (open); depth = distance to surface; size-relative contact tolerance. Guard cases in s00 |
| 28 | run_tests | eyes: overview sheet mostly empty cells | one large image set the cell size | `contact_sheet` normalises heights |

Wrong first hypotheses that measurement disproved (kept as a reminder to measure before fixing):
cloth quality (#23), floor tunnelling (#24), bone rolls alone (#21), overlapping liquid (#25).

## Measured reference data (Blender 4.5.10)

Display value of scene-linear 0.18 (grey card): AgX 0.459, Khronos PBR Neutral 0.408, Filmic 0.498,
Standard 0.459. Full table (0.02..4.0) in `references/lighting-camera.md` / `render.GREY_TARGET`.

| Engine timing (this machine) | |
|---|---|
| Workbench view 480x360 | 0.5-2 s |
| EEVEE Next 960x540, DOF + motion blur | first frame 26-38 s (shader compile), then 4.2-4.3 s/frame |
| Cycles CPU 1280x960, 128 spp (s01) | 34 s |
| Cycles CPU 1280x720, 810k tris / 12.9k instances (s03) | 40 s |
| Cycles CPU 1280x854, 256 spp closed interior (s06) | ~7 min |
| Cycles CPU vs CUDA (GTX 750 Ti) on small scenes | about equal |

## Known limitations

- Only Blender 4.5.10 was available; 5.x branches in `compat` follow release notes and are untested.
- Procedural stand-in assets are stylised; photoreal vegetation/characters need real assets.
- Rigify generation, fluids, smoke, particles-hair and GN simulation zones have reference notes
  but no tested helpers.
- Visual judgement is Claude's: the suite produces the images, a reviewer must still look.
- `inspect.intersections` skips meshes over 150k tris and treats coplanar contact as contact
  (not penetration) - very thin overlaps below 0.1 mm are not reported.

## Latest run (2026-11-24, quick mode, reference machine)

| id | scenario | result | validate | build s | render s |
|---|---|---|---|---|---|
| s00 | API smoke (16 cases incl. intersection guards) | PASS 16/16 | - | 4.6 | - |
| s01 | basic object | PASS | 100 | 2.1 | 4.5 |
| s02 | hard-surface | PASS | 100 | 1.4 | 4.1 |
| s03 | procedural environment | PASS | 100 | 2.5 | 4.7 |
| s04 | material showcase (grey card 0.448-0.455 vs 0.459) | PASS | 100 | 10.1 | 4.1 |
| s05 | cinematic animation | PASS | 100 | 1.0 | 5.0 |
| s06 | photoreal interior | PASS | 100 | 16.5 | 7.2 |
| s08 | rigging (IK error 0.000 m, 0 unweighted) | PASS | 100 | 1.2 | 2.9 |
| s09 | physics (deepest overlap 0.16 mm) | PASS | 100 | 17.3 | 3.8 |
| s07 | spec pipeline (GLB re-import tris match) | PASS | 100 | 14.4 | - |

10/10 passed in 124 s. Full-quality renders made during development: s01 34 s, s02 43 s, s03 40 s,
s04 60 s, s05 72 frames EEVEE 311 s + MP4, s06 ~7.5 min. Regenerate with `run_tests.py`
(outputs in `tests/output/run/`: RESULTS.md, results.json, overview.png - generated, not versioned).
