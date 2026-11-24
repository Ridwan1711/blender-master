# Image-to-3D: three-mode reconstruction (local-first)

Turn reference images (concept art, pixel sprites, elevations, blueprints, paintings, photos) into
clean, measured, engine-ready Blender assets. **No cloud API is ever required.** Three modes, an
evidence-based selector, hybrid plans, and one shared QA/export pipeline:

| Mode | What | Best for | Needs |
|---|---|---|---|
| 1 procedural | build from measured parts / grids | voxel & pixel art, low-poly, robots, furniture, props | nothing (any machine) |
| 2 reference-based | measure the drawings, model to them, compare silhouettes | buildings, hard-surface, anything with 2-3 orthographic views; single-image fallback | nothing (any machine) |
| 3 local AI | single-image neural reconstruction (TripoSR) run locally | organic, painted, one view only | install with the user's OK; CPU works, GPU optional |

Code: `bkit.imageref` (measuring images), `bkit.recon` (building / registering / comparing),
`bkit.gameprep` (cleanup, LOD, bake, export+verify), `scripts/analyze_image.py`,
`scripts/ai3d/*` (hardware check, install, run, selector). Tests: `tests/image_to_3d/`.

## 1. Workflow (always this order)

```bash
B="python SKILL_DIR/scripts/bk.py"
$B run SKILL_DIR/scripts/analyze_image.py -- front=f.png side=s.png [top=t.png] --out an.json --debug-dir dbg
python SKILL_DIR/scripts/ai3d/select_mode.py --analysis an.json --category robot [--style lowpoly] [--needs game,rig]
python SKILL_DIR/scripts/ai3d/check.py            # hardware + model verdicts (Mode 3 gate)
```
1. **Look at the images yourself** (Read them) and at `dbg/` (segments, masks). The selector's
   scores support the decision; they do not replace looking.
2. **State what will be inferred** before building (back side of a single view, hidden depths,
   unknown real size). Ask for the real size if it matters; otherwise assume and say so.
3. Build with the chosen mode (sections 3-5), then run the **common pipeline** (section 7).
4. **Inspect**: `compare_views` diff sheet + multi-view sheet + beauty render - READ them. A
   script that ran proves nothing; IoU alone missed every defect listed in section 9.
5. Report: mode + why, measurements, IoU per view, what is visible vs inferred, limitations.

**World convention** (every recon function): +Z up, the object faces **-Y**. Front image seen from
-Y; side image from +X with the object's front on the image's LEFT (else `flip_side=True`); back
from +Y; top from +Z with the front at the bottom of the image.

## 2. Mode selector (`select_mode.py`)

Inputs: the measured analysis (style hint: pixel grid / flatness / symmetry / palette), number of
views and their consistency (height agreement, shared palette - the top view is excluded from the
height check), the category (geometric vs organic sets), the requested style/fidelity/needs, and
the live `check.py` verdicts. Output: three scores with reasons, the recommendation or a hybrid
plan, and the list of surfaces that will be inferred.

| Evidence | Pushes toward |
|---|---|
| pixel grid detected / style voxel | Mode 1 (voxel at the native grid) |
| flat colours + geometric category | Mode 1 components or Mode 2 |
| 2-3 orthographic views, precise edges, hard-surface/building | Mode 2 |
| one painted/shaded view of an organic subject | Mode 3 if usable, else Mode 2 inflate |
| Mode 3 unusable (check.py "none") | Mode 3 scored n/a - never proposed |

Style "auto" never upgrades flat artwork to "lowpoly" - only the user's words do (defect found in
testing: flat 2-tone concept art was mislabelled low-poly).

## 3. Mode 1 - procedural

```python
from bkit import recon as RC
ob, info = RC.voxel_from_views({"front": f, "side": s}, height_m=1.8)          # pixel art
objs, table = RC.components_from_views(f, s, height_m=1.62, name="Robot")      # flat concept art
ob = RC.lathe_from_image(f, height_m=0.3)          # turned objects (vase, bottle, chess piece)
ob, info = RC.extrude_from_image(f, 0.5, depth=0.02)  # flat objects (sign, blade, emblem)
```
- **Voxels** use the art's own grid (`imageref.pixel_grid`); occupancy = front AND side (AND top);
  only exposed faces; per-face colours from the view that sees them; the unseen ones flagged in the
  `bk_inferred` face attribute (T1: 64% of faces inferred - normal for 2 views).
- **Components**: colour families -> parts matched across views by height overlap; roundness
  from empty bbox corners (ellipsoid), taper by a robust fit of row extents (shrinks the
  NARROWER end), decals become thin panels pushed proud of their container (no z-fighting).
  **Ambiguous** depths (an arm drawn over the torso in the side view) are FLAGGED - look at the
  images, then pass `overrides={part: {"depth": m, "y": m}}`.

## 4. Mode 2 - reference-based

```python
from bkit import imageref as IR, recon as RC
RC.setup_references(views, height_m)      # image empties at real size (GUI guides / documentation)
classes, info = IR.class_map(img, mask, classify)   # per-pixel semantic classes from a palette
IR.runs / IR.longest_runs / IR.straight_members      # posts, rails, bars (straight strokes)
IR.line_segments(mask)                    # braces/rafters at any angle (principal axes)
IR.blobs(mask) / IR.opening(mask, r)      # windows, holes, doors (opening removes thin strokes)
IR.corner_radius(mask, "bottom-left")     # fillet radius of a rounded body, px
rep = RC.compare_views([ob], views, out_dir, ref_m_per_px=PX)   # true-scale IoU + diff sheet
RC.project_views(ob, views, infer="plain")                      # texture from the drawings
ob, info = RC.inflate_from_image(img, height_m)                 # single-view organic fallback
```
**Measure like a modeller, from one scale anchor.** Take the anchor where nothing overhangs (a
house's width at ground level, a device's body height), and keep the sheet scale for the other
views - then **check it**: shared dimensions must agree across views (T3: stone height, roof edge
and roof top identical in both elevations; T4: width front vs top, height front vs side).
Prefer fits over single pixels: gable eave and ridge from a line fit of wall width per row,
corner radius by least squares on the outline, door arch from the opened blob's row widths.

**Depths no view shows** are bounded by the perpendicular view: a button the side view does not
show protrudes at most 1 px (T4: 0.28 mm). Positions one view lacks are derived from geometry
when possible (T3: the chimney's X from where it leaves the roof slope in the side elevation).
Unseen faces: `project_views(infer="plain")` paints them the dominant colour - no invented screen
on the back of a radio; `infer="mirror"` (back <- front) only for symmetric subjects.

**Comparison**: `compare_views` is scale-free by default (right for AI meshes of unknown size).
With a known drawing scale pass `ref_m_per_px` -> true-scale IoU (bottom-centre aligned), keeping
the scale-free value as `iou_shape`. Without it, one extra part in one view (T3: a chimney the
front elevation omits) rescales everything and reads as a 0.87 "mismatch" that is really 0.96.

**Reference sets disagree** more often than not. Report the disagreement, follow the majority of
views, never silently "fix" one view to match another.

**Single image, no AI** (`inflate_from_image`): the silhouette is inflated like a balloon (depth
follows a circle of the distance to the outline), voxel-remeshed to a closed manifold, the image
projected on the front, plain back. Faithful front (T5: IoU 0.92), but a slab from the side - say
so. Thickness is a guess (`thickness=0.75` = 3/4 as deep as wide).

## 5. Mode 3 - local AI (hardware-gated)

### 5.1 Models evaluated (2026-11; sources in `scripts/ai3d/models.json`)

| Model | Licence / commercial | GPU min | CPU | Texture | Install | Download | Skill adapter |
|---|---|---|---|---|---|---|---|
| **TripoSR** (Stability + VAST) | MIT / allowed | 6 GB, cc 5.0, CUDA 11.8 | **yes** (8 GB RAM) | vertex colours | medium | 2.3 GB | **yes** |
| SF3D (Stability) | Community licence, gated; free < USD 1M revenue | 6 GB, cc 7.0, CUDA 12.1 | experimental | UV texture + PBR params | high (C++ ext., Windows experimental) | 4 GB | no |
| InstantMesh (Tencent ARC) | Apache-2.0 + Zero123++ terms | 16 GB, cc 7.0 | no | textured | high (nvdiffrast) | 8 GB | no |
| Hunyuan3D-2 mini (Tencent) | Community licence, **excludes EU/UK/KR** | 5 GB shape / 12 GB paint | no | separate paint model | high | 10 GB | no |
| TRELLIS (Microsoft) | MIT / allowed | 16 GB, cc 8.0 | no | textured / gaussians | very high | 12 GB | no |
| TripoSG (VAST) | MIT / allowed | 8 GB, cc 7.0 | no | none (shape) | high | 6 GB | no |

TripoSR is the only one that runs on CPU, has a permissive licence for both code and weights,
and installs without compiling CUDA code - so it is the skill's supported Mode 3 model. Others are
in the registry so `check.py` can say *why* they cannot run here; add an adapter to support one.

### 5.2 Gate first, never retry what cannot work

`check.py` evaluates every model against the probed hardware: VRAM, compute capability, the
driver's CUDA ceiling, **PyTorch wheel support** (Maxwell/Pascal cc 5.x-6.x were dropped from the
CUDA 12.8+ wheels; CUDA 13 needs cc >= 7.5), RAM and disk. Verdict per model: `gpu`, `cpu` or
`none` with reasons. `install_model.py` refuses `none`; `run_model.py` re-checks before running.
If nothing is usable, Mode 3 is off: recommend Mode 2/1 - do not attempt installs or inference.

### 5.3 Install (only with the user's explicit OK - it downloads ~2.3 GB)

```bash
python SKILL_DIR/scripts/ai3d/install_model.py triposr          # dry run: lists every download + size
python SKILL_DIR/scripts/ai3d/install_model.py triposr --yes    # isolated venv, never Blender's Python
```
Home `~/.cache/blender-master/ai3d/<model>` on every OS (override `BKIT_AI3D_HOME`). **Not
`%LOCALAPPDATA%`**: packaged (MSIX) Windows apps silently redirect AppData writes to a private
folder, so a model installed from one app is invisible to others. `INSTALLED.json` records versions;
an import smoke test runs at the end (it caught a missing `imageio` the upstream list omits).
Uninstall = delete the folder. torchmcubes (needs a C++/CUDA build) is replaced by a PyMCubes shim.

### 5.4 Run (outside Blender - Blender's stability is never at risk)

```bash
python SKILL_DIR/scripts/ai3d/run_model.py triposr --image creature.png --out out/creature.glb --mc-res 256
```
Own process, below-normal priority, offline (`HF_HUB_OFFLINE=1`), timeout, background removal by
border flood fill (no rembg download), CPU threads capped, peak RAM / CPU time self-reported.
Measured here (Ryzen 7 1700, 8 threads, no usable GPU): **~73 s wall, ~430 CPU-s, 3.6 GB peak RAM**,
66k-vertex mesh with vertex colours. `--mc-res 128` roughly halves meshing time and RAM.

### 5.5 Into Blender

```python
ob = RC.import_mesh("out/creature.glb", height_m=1.0)       # join, apply, origin bottom, scale
al = RC.align_to_reference(ob, {"front": img}, out_dir)      # 24 orientations by silhouette IoU;
                                                              # near-ties (front/back) settled by colour
GP.cleanup(ob, min_part_ratio=0.01)                          # AI debris islands
GP.decimate(ob, target_tris=8000)
GP.bake_materials(ob, maps=("Base Color",), normal=False)   # vertex colours -> texture
```
AI output is a dense, smooth, single shell: soft edges, hallucinated back, painted (not modelled)
details, occasional non-manifold edges after decimation. Hard-surface/flat art comes out wobbly -
the selector scores Mode 3 down for those.

## 6. Hybrid workflows

`mode3 base -> gameprep cleanup/decimate -> mode2 compare (fix proportions) -> mode1 crisp details`.
T5 example: TripoSR body + procedural glossy eyes. **Where** a detail goes comes from the model's
own paint (flat `render_colour` of the front, find the eyes there); **proportions** come from the
sharp drawing (blurry AI paint shrinks dark cores - pupils came out 35% small). If the model has
no usable paint, `register_view` maps image pixels to the mesh by the centroid and area of the
**core** silhouette (ears/tails/antennas removed by an opening) - bounding boxes are skewed by
exactly the thin parts AI meshes get wrong. Place details by ray-casting onto the surface.

## 7. Common post-reconstruction pipeline (every mode)

`tests/image_to_3d/common.py:finish()` is the reference implementation:
1. `GP.normalize(ob, origin="BOTTOM")` - transforms applied, pivot at the bottom centre (joined
   parts otherwise keep the FIRST part's origin: T2's pivot sat on the antenna ball).
2. `RC.compare_views` - IoU per view + diff sheet (grey both, red model-only, blue reference-only).
3. Bake if any material is procedural / colour-attribute (`GP.needs_bake`) - emission bake per
   Principled input; Blender-only node trees do not survive glTF/FBX.
4. `GP.asset_report` - tris, dims, health (closed, boundary/non-manifold edges, inverted,
   zero-area, doubles), pivot, engine-safe materials.
5. `GP.export(ob, "x.glb", engine="godot")` and `engine="unity"` (FBX) - each **re-imported into
   an empty scene and verified**: triangle count, dimensions, textured materials.
6. Multi-view sheet (texture mode after a bake - material mode shows baked images flat grey) and a
   Cycles beauty render. Read both.

Engine notes: **Godot 4** imports `.glb` natively and generates LODs/collision on import - export
LOD0 only. **Unity**: FBX with `apply_scale_options=FBX_SCALE_ALL` + `bake_space_transform`
(arrives at scale 1, no -90 X on the root); `GP.make_lods(naming="unity")` names `_LOD0.._LOD2`
for a LODGroup; glTF in Unity needs a package (glTFast). **Rig-ready**: origin at the feet, scale
1, faces -Y (engine forward after the exporters' axis conversion), single mesh, applied modifiers.

## 8. Test campaign (tests/image_to_3d, run_i3d_tests.py)

Synthetic reference sets with known ground truth (`make_refs.py`), Blender 4.5.10, Ryzen 7 1700:

| Case | Selector | Built with | IoU | Tris | Time |
|---|---|---|---|---|---|
| voxel knight, 2 views | M1 7 > M2 1 | `voxel_from_views` | 0.980 / 0.996 | 386 | 13 s |
| low-poly robot, 2 views | M1 7 > M2 5 | `components_from_views` + overrides | 0.959 / 0.947 | 420 | 15 s |
| medieval house, 2 elevations | M2 6 > M1 5 | measured elevations | 0.961 / 0.992 (true scale) | 1262 | 16 s |
| walkie-talkie, 3-view blueprint | M2 7 > M1 5 | measured blueprint + projection | 0.988 / 0.990 / 0.990 | 2722 | 17 s |
| creature, 1 painting | M3 5 > M2 0 | TripoSR CPU + procedural eyes | 0.860 | 9504 | 63 s AI + 17 s |
| creature, no AI | M2 (M3 n/a) | `inflate_from_image` + eyes | 0.916 | 9504 | 18 s |

Measured vs drawn: house eave 4.24 m (4.2), ridge 7.63 (7.6), depth 8.99 (9.0); radio 70.3 x
40.4 mm (70 x 40), corner radius 8.2 mm (8) in all three views. Every export re-imports with
matching triangles and dimensions. Details and the defect log: `tests/TESTING.md`.

## 9. Defects found by inspection (fixed)

| # | Defect | Caught by | Fix |
|---|---|---|---|
| 1 | Flat concept art auto-labelled "lowpoly" | selector review | neutral "flat" style; lowpoly only on request |
| 2 | 3-view set flagged inconsistent (top view's "height" is the depth) | analysis | top view excluded from height agreement |
| 3 | Robot head built as an ellipsoid, arms tapered, torso taper missed | beauty render | empty-corner roundness; Theil-Sen on row extents |
| 4 | Visor z-fighting black; chest light buried | beauty render | decals = thin panels pushed proud of their container |
| 5 | Torso too wide (taper widened the top) | compare sheet | taper shrinks the narrower end, per axis |
| 6 | Pivot on the antenna ball after join | asset report | normalize in the common pipeline |
| 7 | House 2.3x too big: door split the stone base, the largest stone piece became the scale anchor | measurement table | anchor at the ground-level silhouette |
| 8 | Whole timber frame detected as one "door" (connected component) | beauty render | per-class masks + morphological opening for solid blobs, straight runs for members |
| 9 | Reference roof drawn as a self-crossing "bow-tie" (fixture bug) | compare sheet | fixture fixed |
| 10 | Front IoU 0.87 for a correct house | compare sheet | true-scale comparison (`ref_m_per_px`) |
| 11 | Antenna drawn as an opaque strip down the radio's body (fixture bug) swallowed a button | count check | fixture fixed |
| 12 | Dark streaks around grille holes | multi-view sheet | normals set AFTER booleans (sharp by angle + weighted) |
| 13 | Procedural eyes beside the AI's painted eyes | front view | positions from the model's own paint; core-silhouette registration fallback |
| 14 | Pupils 35% too small on AI paint | front view | proportions from the drawing |
| 15 | Inflated body non-manifold after decimation (knife-edge rim) | asset report | voxel remesh inside `inflate_from_image` |
| 16 | Mode 3 install landed in an MSIX-virtualised AppData folder | install log | home moved to `~/.cache` |
| 17 | AI run reported 3.6 MB, then 0 MB peak RAM (venv launcher; 64-bit handle truncation) | numbers vs reality | adapter self-reports with typed ctypes calls |
| 18 | TripoSR import failed: `imageio` missing upstream | first run | added + post-install import smoke test |
| 19 | Smoothly shaded cartoon classified "photo" (k-means flatness 0.57) | selector review | `imageref.texture_energy` (median Laplacian): 0.003 cartoon vs 0.038 with sensor noise |

## 10. Limits to state

- Single image: the back and all depth are inferred - always say so; offer Mode 2 views if the
  user can supply a side view.
- Mode 3 on CPU is minutes, not seconds; GPU acceleration needs a GPU + driver the current
  PyTorch wheels support (check.py explains). Texture is vertex colour (baked to an image).
- Unknown real size: ask, or assume and state it (T5 assumed 1.0 m).
- Photos: Mode 2 measurement assumes orthographic, flat-colour drawings; photos have perspective
  and lighting - use them for proportions and Mode 3, not for exact measurement.
