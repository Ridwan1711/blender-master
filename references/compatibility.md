# Blender version compatibility

**Rule:** run `bk.py probe` in every new environment and believe it over this file.
Status legend: **V** = verified by this skill's tests on 4.5.10 LTS; **RN** = from release notes,
not executed here - confirm with the probe or a 3-line `bk.py exec` before relying on it.

## Probing techniques (V)

```python
from bkit import compat
compat.has_prop(bpy.types.Action, "layers")          # RNA property  (hasattr on the class is WRONG)
compat.has_func(bpy.types.Mesh, "set_sharp_from_angle")  # RNA function (hasattr on the class is WRONG)
hasattr(bpy.types, "GeometryNodeRepeatInput")        # node/operator/type classes: hasattr is fine
compat.set_enum(scene.view_settings, "view_transform", ["AgX", "Filmic"])  # dynamic enums: assign
compat.set_engine(scene, "EEVEE")                    # engine ids differ by version
bpy.app.version >= (4, 2, 0)                          # coarse gates only; prefer feature probes
```
Dynamic enums (`render.engine`, `view_transform`, `look`, `cycles.denoiser`, ...) report stub
items through `bl_rna...enum_items` in background mode - never enumerate them that way. (V)

## API change matrix

| Area | <=3.6 | 4.0-4.1 | 4.2-4.5 LTS | 5.0+ | bkit handles via |
|---|---|---|---|---|---|
| EEVEE engine id | `BLENDER_EEVEE` | `BLENDER_EEVEE` | `BLENDER_EEVEE_NEXT` (V) | `BLENDER_EEVEE` (RN) | `compat.set_engine` |
| Principled sockets | Subsurface, Specular, Transmission, Clearcoat, Sheen, Emission | renamed: Subsurface Weight, Specular IOR Level, Transmission Weight, Coat Weight, Sheen Weight, Emission Color (V on 4.5) | same | same | `compat.set_input` aliases |
| Node group interface | `tree.inputs/outputs.new` | `tree.interface.new_socket` (V on 4.5) | same | same | `compat.new_interface_socket` |
| GN modifier inputs | `mod["Input_2"]` | `mod["Socket_2"]` identifiers | same (V) | same | `compat.set_modifier_input(mod, "Name", v)` |
| Auto smooth | `mesh.use_auto_smooth` | removed in 4.1 (RN); `Mesh.set_sharp_from_angle` / Smooth by Angle | same | same | `compat.shade_smooth(ob, angle)` |
| Transparency | `material.blend_method` | same | `surface_render_method` DITHERED/BLENDED (V present) | same | `compat.set_blend_mode` |
| EEVEE bloom/SSR/GTAO | scene.eevee props | same | removed/replaced (bloom -> compositor Glare) (RN) | same | `render.glare`, `try_set` |
| Context override | dict arg (removed 4.0) | `context.temp_override(**kw)` (3.2+) (V) | same | same | `compat.override` |
| Actions / F-curves | `action.fcurves` | same | 4.4+: layered/slotted actions; `fcurves` still proxied (V layers present) | legacy `action.fcurves` removed (RN) | `compat.action_fcurves/id_fcurves` |
| VSE collection | `sequence_editor.sequences` | same | 4.4+: `.strips` (V path used) | `.sequences` removed (RN) | `video.encode_sequence` |
| Compositor tree | `scene.node_tree` + Composite node | same | same (V) | node group `scene.compositing_node_group`, Group Output (RN, **untested**) | `compat.compositor_tree`, `render._comp_base` |
| Compositor node options | properties | properties | 4.4/4.5 moved many to input sockets (RN) | sockets | `render._cset` tries both |
| OBJ export | `export_scene.obj` (old) / `wm.obj_export` (3.2+) | old removed 4.0 | `wm.obj_export` (V present) | same | `export_blend.py` |
| Align to vector node | `FunctionNodeAlignEulerToVector` | same | `FunctionNodeAlignRotationToVector` (4.2+, V) | same | `geonodes.scatter` picks |
| GN zones | - | repeat (4.0) | for-each element (4.3), bake node (4.1) (V present) | closures (5.0, RN) | probe |
| Grease Pencil | GPencil v2 (`GPENCIL`) | same | GP v3 4.3+ (`GREASEPENCIL`) (RN) | same | `scene.PREFIX` covers both |
| Add-ons | `addon_utils` modules | same | 4.2+ extensions (`bl_ext.<repo>.<name>`) (V: Meshy add-on seen as bl_ext.user_default.meshy) | same | enable by full module name |
| Light temperature | colour only | same | colour only | check probe | `lighting.kelvin()` (works everywhere) |

## Known behaviour on 4.5.10 (V, Windows, GTX 750 Ti 2 GB, Ryzen 7 1700)

- Headless rendering works for Workbench, EEVEE Next and Cycles (CPU and CUDA). OptiX: no device.
- EEVEE Next: first render in a process compiles shaders (26-38 s on this GPU), later frames ~4 s at 960x540.
- Cycles CPU vs CUDA on a 2 GB Maxwell card: about equal for small scenes; CPU is the safe default
  (`BKIT_DEVICE=CPU`) because large scenes exceed VRAM.
- `bpy.ops.rigidbody.bake_to_keyframes` fails headless (internal UI-only operator). Use `physics.bake_to_keyframes`.
- `object.parent_set(type="ARMATURE_AUTO")` (automatic weights) works headless with an override.
- Edit-mode switching for armatures works headless with an override (`rig._mode`).
- Cloth memory cache is stored in the saved `.blend` and used when rendering a later frame.
- Bare relative render paths resolve against the drive root, not the CWD.

## Porting checklist (moving a script to another version)

1. `bk.py probe` on the target; diff `features` against 4.5 output (tests/TESTING.md lists it).
2. Search the script for: `.fcurves`, `node_tree` on scene, `BLENDER_EEVEE`, Principled socket names,
   `inputs.new`/`outputs.new` on node groups, `use_auto_smooth`, `blend_method`, `sequences`,
   `export_scene.obj`, dict context overrides. Replace with the `compat` helpers.
3. Run the test scenarios (`python tests/run_tests.py --quick`) and inspect the sheets.
