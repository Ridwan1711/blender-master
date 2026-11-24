# Animation, rigging & character work

## Keyframes (`from bkit import anim as A`)

```python
A.keys(obj, "location", [(1, (0,0,0)), (48, (2,0,0))], interpolation="BEZIER")
A.keys(cam, "data.lens", [(1, 35), (96, 50)])            # "data." keys the datablock (camera/light)
A.keys(light, "data.energy", [(1, 5), (24, 120)])
A.key_socket(mat, "Principled BSDF", "Emission Strength", [(1, 0), (24, 12)])   # node inputs
A.ease(obj, "EASE_IN_OUT"); A.set_interpolation(obj, "LINEAR"); A.cycle(obj); A.noise(cam, strength=0.01, scale=25)
A.sample(obj, "location", frames); A.motion_report(cam, range(1, 97))   # numeric verification
```
- F-curve access goes through `compat.id_fcurves` (4.4+ layered/slotted actions; legacy before).
- `motion_report` returns path length, max/median step and `pops_at_frames` (step > 3x median).
  S05 camera: 1.96 m path, max step 0.042 vs median 0.031, no pops.
- Timing at 24 fps: 12 f = 0.5 s; a camera move under ~2 s feels rushed; ease in/out unless the cut
  hides the start/stop. Linear only for constant motion (turntables, conveyors).

## Camera moves (S05)

`camera.orbit` (pivot empty, linear or eased rotation) + keyed local location = orbit-and-dolly;
`track` constraint keeps aim; `dof` on the subject; `rack_focus` for focus pulls; `A.noise` for
handheld. After any camera animation: `preview.frames(out, [1, mid, end])` and check the set covers
the whole path (`studio_backdrop(..., frames=(a, b))`). Lights-up reveals: key `data.energy`.

## Rigging (`from bkit import rig as RG`)

```python
arm = RG.armature("RIG_Arm", [dict(name="base", head=(0,0,0), tail=(0,0,.25)),
                              dict(name="upper", head=(0,0,.25), tail=(0,.05,.85), parent="base", connect=True),
                              dict(name="fore", head=(0,.05,.85), tail=(0,0,1.35), parent="upper", connect=True)])
tgt = RG.ik(arm, "fore", target=(0.5,-0.3,0.6), chain=2, pole=(0,0.8,0.9))
RG.bind_rigid(part, arm, "upper")        # mechanical parts follow one bone, keep world transform
report = RG.bind_auto(mesh, arm)         # heat weights; report lists unweighted verts/bones
RG.bind_groups(mesh, arm, {"bone": [(vi, w), ...]})   # manual weights
RG.pose(arm, "knee.L", (28, 0, 0), frame=1); RG.bone_world_head(arm, "fore", frame=24)
body, rig, rep = RG.mannequin("Hero", location=(0.6, 0, 0)); RG.walk_cycle(rig, frames=24)
```

Verified rules (each was a real defect in S08):
1. **IK chains need a pre-bend** toward the pole. A straight chain stayed fully stretched and
   missed the target by 0.40 m; with a 5 cm elbow offset the error became 0.000 m.
2. **Deterministic bone rolls.** Blender's default rolls differ between mirrored bones, so the same
   rotation raised one arm and lowered the other. `RG.armature` aligns rolls (horizontal bones: local
   Z = up; vertical bones: local Z = forward/-Y). With these: X- lowers T-pose arms, X+ swings a leg forward.
3. **Move the rig root, not the parented mesh too.** Moving both doubled the offset; the mesh then
   deformed around bones 0.6 m away. `mannequin(location=...)` moves the armature only.
4. Check weights: `bind_auto` report must show `unweighted_vertices: 0` and no `bones_without_weights`;
   grep the log for "Bone Heat Weighting: failed".
5. Verify poses numerically (`bone_world_head`) and visually (`preview.frames`).

Bone naming in `mannequin`: a bone is named after the joint where it ends (`knee.L` = thigh,
`ankle.L` = shin, `elbow.L` = upper arm, `wrist.L` = forearm). Use `.L/.R` suffixes so Blender's
mirror tools work.

## Rigify / production rigs

Rigify is bundled (`addon_utils.enable("rigify")`); generating needs the metarig operators with a
context override - not covered by the tested helpers here. For mechanical rigs prefer bones +
constraints (IK, Copy Rotation, Limit Rotation, Damped Track) + `bind_rigid`. For characters from
external sources (Mixamo/FBX) import, then validate weights and rest pose.

## Shape keys & drivers (quick reference)

```python
ob.shape_key_add(name="Basis"); sk = ob.shape_key_add(name="Smile"); sk.data[i].co = ...
sk.value = 0.5; sk.keyframe_insert("value", frame=10)
d = ob.driver_add('["prop"]').driver  # or ('location', 2)
d.type = "SCRIPTED"; v = d.variables.new(); v.targets[0].id = other; v.targets[0].data_path = "location.x"; d.expression = "var * 2"
```
Python-expression drivers need auto-run scripts: avoid them in files meant for others; use
built-in driver types (SUM, AVERAGE, MIN, MAX) where possible.
