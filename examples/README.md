# Workflow examples

Every example is a runnable, tested script. Copy the closest one and adapt it.

| Example | Workflow it demonstrates | Run |
|---|---|---|
| `tests/scenarios/s01_basic_object.py` | single product: lathe body, open-torus handle, per-face materials, assembly parenting, camera-aware cyclorama, three-point rig | `bk.py run ... --save out/mug.blend` |
| `tests/scenarios/s02_hard_surface.py` | hard-surface asset: boolean recesses + arrayed vent cutters, finishing stack (bevel/weld/weighted normals), L-profile guards, curve handles, linked-copy bolts, edge-wear paint, Khronos view for product colour | same |
| `tests/scenarios/s03_procedural_environment.py` | procedural world: GN terrain, asset library, 5 scatter layers with ecological rules, raycast-measured water level/shoreline/camera, clear zone, sky + sun, mist pass. `-- --seed N` for a new world | same |
| `tests/scenarios/s04_material_showcase.py` | look-dev: every material preset, labels (text objects), grey/white calibration cards, grey-card auto exposure | same |
| `tests/scenarios/s05_cinematic_animation.py` | augmenting an existing .blend (opened with `--blend`, saved under a new name): orbit+dolly, lights-up reveal, pulsing emission, DOF, motion blur, EEVEE, path-aware backdrop, motion check | `bk.py run ... --blend out/crate.blend --save out/cine.blend`, then `bk.py render out/cine.blend --out out/f/f_ --frames 1-72 --video out/cine.mp4` |
| `tests/scenarios/s06_photoreal_interior.py` | photoreal interior: appended asset from another file, room with boolean window, sun through window, glass, shallow DOF, temporary grey card metering, final-tier Cycles | `... -- --mug out/mug.blend` |
| `tests/scenarios/s08_rigging.py` | mechanical IK rig with rigid parts + character (skin-modifier mannequin, auto weights, walk cycle) with numeric IK check | same |
| `tests/scenarios/s09_physics.py` | rigid-body tower + wrecking ball, cloth drape, every-frame stability checks, bake to keyframes | same |
| `examples/spec_desk.json` + `scripts/pipeline.py` | fully automated production from a declarative spec: build -> validate -> preview -> render -> GLB export with re-import verification -> report | `python scripts/pipeline.py examples/spec_desk.json --out out/desk` |

## Typical requests -> starting point

- "Make me a <product> render" -> s01 / s02 pattern + `view="Khronos PBR Neutral"` if colour matters.
- "Build a forest / landscape / city block" -> s03 (swap assets, adjust scatter rules).
- "Animate a camera around X" -> s05 (works on any existing file).
- "Photoreal interior shot" -> s06 (closed room, window light, metering).
- "Rig this / make it walk" -> s08 helpers; validate weights; frame strip.
- "Simulate X falling / cloth over Y" -> s09.
- "Generate 20 variations" -> spec JSON + pipeline, or a scenario with `--seed` argument in a loop.
- "Fix my file" -> `bk.py inspect --health`, `bk.py validate`, preview sheets, then targeted scripts
  that open the file and save a new version.
