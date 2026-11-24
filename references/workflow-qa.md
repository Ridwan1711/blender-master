# Workflow & Quality Assurance

## 1. Planning template (write it in your head or to the user for big jobs)

```
Target     : what the final image/asset/animation shows, style (photoreal | stylised | technical)
Deliverable: .blend? stills (res, count)? video (length, fps)? exports (GLB/FBX)? turnaround?
Scale      : real dimensions of the hero + environment (metres)
Budget     : tier (mobile/game/hero/film), render time per frame, hardware (bk.py probe)
Assets     : list -> source (model in bkit / user file append / library) -> owner script
Look       : materials list, light plan (key/fill/rim or motivated sun/sky), view transform
Shots      : camera(s), lens, azimuth/elevation, motion, DOF
Checks     : what proves each part works (validate tier, metrics, which views to inspect)
```

## 2. Build in stages, each verified

| Stage | Build | Verify (always) |
|---|---|---|
| Blockout | proportions with primitives | `preview --mode clay` front/right/top: scale, silhouette |
| Detail | bevels, booleans, small parts | `validate` (doubles, degenerate, intersections), `preview --mode wire` |
| Materials | presets / textures | `preview --mode material` + beauty at low samples |
| Light & camera | rig, world, framing | `render --quality preview`, `imgcheck`, grey-card metering |
| Final | quality tier, output | full render, Read it at full size, `imgcheck`, `validate --purpose final` |

Keep each stage a separate script that opens the previous `.blend` and saves a new one
(`--blend v002.blend --save v003.blend`). Failed step = rerun one script, not the whole job.

## 3. Visual inspection protocol (read the PNG, then answer these)

Geometry (contact sheet, wire/clay):
- Silhouette and proportions plausible from front/side/top? Real-world scale (check ortho widths in labels)?
- Anything floating, sunk into the floor, or passing through another part?
- Shading artifacts: dark smears on flat faces (normals), pinching, faceting where it should be smooth?
- Topology density sensible (wire): no dense mess on flat areas, enough on curves?

Materials (material sheet / beauty):
- Each surface reads as its intended material at this distance? Metals need something to reflect.
- Colour as intended (AgX desaturates bright saturated colours; compare to hex intent)?
- Textures: stretched, tiled obviously, wrong scale, blotchy (wrong grain type)?

Light & exposure (beauty + `imgcheck`):
- Subject separated from background (rim/contrast)? Shadows readable, not crushed? Highlights not clipped?
- Light direction motivated (window, sun, practical)? Grey card near target value?

Composition (camera view):
- Subject fill (validate reports `subject_fill`), thirds, horizon placement, headroom.
- Nothing accidental at the frame edges: set edges, cropped handles, half-objects.
- Background clean: no visible end of backdrop/floor/world.

Animation (`preview.frames` strip + `anim.motion_report`):
- Smooth motion (no pops), correct timing, set coverage over the whole camera path, deforming meshes intact.

## 4. Defect catalogue (all observed during testing - check these first)

| Symptom | Cause | Fix |
|---|---|---|
| Parented part at world origin | stale `matrix_world` during keep-transform parenting | `S.refresh()` before reading matrices (bkit.parent does) |
| Dark blob at frame corner | backdrop edge / end of floor visible | `studio_backdrop(cam, objs)` after framing; for moving cams `frames=(a,b)` |
| Bevel leaves doubles / zero-area faces | bevel width >= half a feature (recess wall, slot) | width < 0.4 x smallest feature; `hard_surface_finish` adds Weld |
| Duplicate verts on tube ends | curve caps not welded | `curve_tube(..., to_mesh=True)` merges |
| Glass renders black | smooth shading across a thin wall's sharp corners (isolated in S06: flat = clear) | angle-limited smoothing (`lathe` default 30 deg) |
| Wood looks like camouflage or ribbed plastic | noise colour fed into a wave / perfectly periodic grain | `MT.wood` (stretched-noise grain, irregular spacing) |
| Pastel / washed colours | AgX compresses bright saturated colours | lower exposure, `look="Punchy"`, or `view="Khronos PBR Neutral"` for product |
| Yellow shift on bright orange | Filmic hue skew | use AgX or Khronos |
| Blotchy wood on boards | ring grain on flat parts | `wood(grain="BANDS")` (default) |
| Crushed shadows | metered on a sunlit spot | meter in average light or add +0.5..1 EV; add bounce/fill |
| Overexposed render | light energy guessed | grey card + `R.auto_exposure` |
| Shot blocked by a tree/prop | scatter at camera | `scatter(..., avoid=empty, avoid_radius=r)` |
| Lake/subject not visible | camera placed by guess | raycast terrain/shoreline; place camera from measurements |
| Low-poly toy look on foliage | over-saturated, SSS/sheen too high | darker, less saturated greens, low SSS |
| IK arm stays straight | perfectly straight rest chain | pre-bend joint toward the pole |
| One arm up, one down | different default bone rolls | `rig.armature` sets deterministic rolls |
| Mesh deforms around wrong pivot | moved both rig and parented mesh | move the armature only |
| Cloth spikes for one frame | Solidify even-thickness after cloth | `solidify(..., even=False)` |
| "Fell through floor" false alarm | rotated bbox corners overstate extent | `world_bounds(..., exact=True)` |
| Bark colour on foliage faces | stale `BMFace.index` on new faces | track faces by set, or `index_update()` |
| Preview images washed grey | compositor (mist) applied to Workbench | previews disable compositing (bkit does) |
| Preview frames tiny/empty | hidden asset collection counted as subject | collection render visibility checked (bkit does) |

## 5. Validation severities and what to do

- `error` - must fix before delivery (missing textures, no camera, no light, subject outside frame,
  cutter visible, inverted normals, UV-less image textures, odd H.264 resolution).
- `warn` - fix, or tell the user why it is intentional (intersections of kitbash parts -> parent them
  into one assembly or set `obj["bk_allow_intersect"]=True`; budgets; cropped subject in a close-up).
- `info` - hygiene (default names, orphans, absolute paths).
Score = 100 - 15/error - 4/warn - 0.5/info. Report the score and remaining items.

Intersections are measured, not just detected: each pair reports `depth_mm` (deepest sample of
one surface inside the other: ray-parity for closed meshes, normal sign for open ones) and a
size-relative tolerance (>= 0.5 mm, 0.2% of the smaller object). Resting contact and solver-margin
overlaps (settled rigid bodies: 0.16 mm in S09) are "contact" and not flagged; a box sunk 50 mm or a
beam piercing a wall is "penetration". Validation runs at the file's current frame - set the frame
you care about before saving animated/simulated files.

## 6. Iteration discipline

- Change one thing, re-render the same view, compare (`preview.contact_sheet([before, after], ...)`).
- Measure before/after when a metric exists (grey card value, fill, tris, doubles, IK error).
- When a check fails, find the cause (trace values per frame / per stage) before changing parameters.
  In testing, four "obvious" explanations were wrong: cloth quality (real cause: solidify), floor
  tunnelling (real cause: bounding boxes), mannequin rolls (real cause: double offset), black glass
  from overlapping liquid (real cause: smoothing). Controlled A/B renders settle it in seconds.

## 7. Reporting to the user

Give: what was built, file paths, renders (send images if a file-send tool exists), validation
score, measured facts (tris, render time, exposure), visual review notes, known limitations and
what was not verified. Do not claim photoreal/production-ready unless you looked and it is.
