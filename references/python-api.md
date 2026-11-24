# Blender Python (bpy) for production automation

## Execution model

- `bk.py` launches `blender -b [file] --factory-startup --python-exit-code 1 --python _bootstrap.py`.
  Factory startup = user add-ons/prefs can't change results; `--user-prefs` opts in (needed when a
  file depends on an add-on). Scripts embedded in `.blend` files never auto-run (keep it that way for
  files you didn't create).
- The bootstrap puts `scripts/` on `sys.path` (so `import bkit` works), runs your script with
  `sys.argv = [script] + args-after--`, catches every exception into JSON (`type`, `message`,
  `where` = your failing line, traceback tail), and optionally saves with the no-overwrite guard.
- `emit(key=value)` adds to the result JSON; `warn(msg)` collects warnings; `save(path, version=True)`.
- One Blender process per step = clean state and crash isolation. Chain steps through `.blend` files.

## Data API first, operators second

| Want | Data API (headless-safe) | Operator (needs context) |
|---|---|---|
| Create mesh | `bmesh` / `mesh.from_pydata` (`bkit.mesh`) | `bpy.ops.mesh.primitive_*` |
| Add modifier | `ob.modifiers.new(name, type)` | `object.modifier_add` |
| Apply modifiers | `bpy.data.meshes.new_from_object(ob.evaluated_get(dg))` (`mesh.apply_modifiers`) | `object.modifier_apply` |
| Apply transform | `ob.data.transform(m)` (`mesh.apply_transform`) | `object.transform_apply` |
| Delete object | `bpy.data.objects.remove(ob, do_unlink=True)` | `object.delete` |
| Link to collection | `coll.objects.link(ob)` | `object.move_to_collection` |
| Keyframe | `id.keyframe_insert(path, frame=f)` | `anim.keyframe_insert*` |
| Rigid bake | `physics.bake_to_keyframes` (records matrices) | `rigidbody.bake_to_keyframes` **fails headless** |

When an operator is unavoidable (UV unwrap, join, parent_set auto weights, rigid body add, mode set):
```python
from bkit import compat
with compat.override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
    bpy.ops.object.mode_set(mode="EDIT")
```
Also set `view_layer.objects.active = ob` and `ob.select_set(True)` - some polls read the view layer,
not the override. Operators needing a 3D View region (`view3d.*`, viewport screenshots) cannot run
headless at all: use renders (`bkit.preview`) instead.

## Traps verified in testing

1. **Stale `matrix_world`.** After `ob.location = ...` the world matrix updates only on depsgraph
   evaluation. `bkit.scene.refresh()` (= `view_layer.update()`) or `context.evaluated_depsgraph_get()`
   before reading `matrix_world`, bounds or parenting with keep-transform.
2. **Relative paths.** `render.filepath = "out/a.png"` wrote to `C:\out\a.png`. Use absolute paths,
   or `//` for blend-relative.
3. **`hasattr(bpy.types.X, "prop")` is False for RNA props/functions** -> `compat.has_prop/has_func`.
4. **Dynamic enum lists are stubs in background** -> probe by assignment.
5. **`BMFace.index` of newly created elements is stale** until `bm.faces.index_update()`; track new
   geometry with sets (`before = set(bm.faces)`).
6. **Names are not identities.** Creating "Cube" when one exists yields "Cube.001"; names cap at 63
   chars. Keep the returned object reference; look up by name only for loaded files.
7. **Moving a parent moves children.** Moving a parented child *and* its parent doubles the offset.
8. **`bpy.data.*.remove` invalidates Python references** to that ID - drop them.
9. **`evaluated_get(...).to_mesh()` must be paired with `to_mesh_clear()`**.
10. **Python exceptions inside Blender exit 0** unless `--python-exit-code` is set (bk.py sets it).

## Fast data access

```python
import numpy as np
co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3); co[:, 2] += 0.1; me.vertices.foreach_set("co", co.ravel()); me.update()
```
Use `foreach_get/set` for anything over a few thousand elements (attributes, UVs, pixels:
`img.pixels.foreach_get(arr)`). Blender ships numpy.

## Evaluated data (what renders)

```python
dg = bpy.context.evaluated_depsgraph_get()
ev = ob.evaluated_get(dg)            # modifiers + GN applied
me = ev.to_mesh(); ...; ev.to_mesh_clear()
for inst in dg.object_instances:      # includes GN / collection instances
    inst.is_instance, inst.object, inst.matrix_world
```
`bkit.inspect.evaluated_tris()` counts rendered triangles including instances.

## Debugging recipes

```bash
# what is in the file
python bk.py inspect scene.blend --health
# value at each modifier stage (toggle show_viewport k by k)  -> see S02 notes in tests/TESTING.md
# per-frame trace
python bk.py exec "import bpy; from bkit import emit; sc=bpy.context.scene; ob=bpy.data.objects['X'];
out=[]
for f in range(1,91): sc.frame_set(f); out.append(round(ob.matrix_world.translation.z,3))
emit(z=out)" --blend scene.blend
```
Measure first, then change one thing.

## Error catalogue (Python side)

| Message | Meaning |
|---|---|
| `bpy_prop_collection[key]: key "X" not found` | wrong name / not created / `.001` suffix |
| `bpy_struct: item.attr = val: enum "X" not found in (...)` | invalid enum for this version/context |
| `Operator bpy.ops.X.poll() failed, context is incorrect` | missing active object/selection/mode/area |
| `AttributeError: 'X' object has no attribute 'y'` | API differs by version -> compatibility.md |
| `ReferenceError: StructRNA of type X has been removed` | using a reference after `remove()` / file reload |
| `RuntimeError: Error: Cannot ... in edit mode` / mode errors | switch to OBJECT mode first |
| `TypeError: bpy_struct: item.attr = val: sequence expected ... got float` | colour needs 4 values (RGBA) |
