# Blender Master Skill — Architecture

Status: v1.1 (v1.0 + image-to-3D), built and tested on Blender 4.5.10 LTS (Windows 11, Ryzen 7 1700, GTX 750 Ti 4 GB).

## Design goals

1. **Execution over documentation.** Every technique the docs recommend is backed by
   a tested helper in `bkit` or a tested scenario in `tests/`.
2. **Closed loop.** Build -> inspect (data) -> look (render) -> fix. A script that
   exits 0 has proven nothing about the picture.
3. **Headless first, reproducible.** Blender runs as a subprocess against `.blend`
   files. Every step is a script you can re-run. The GUI is optional.
4. **Version-aware.** A probe reports what this Blender actually supports; `bkit.compat`
   hides known API breaks (3.6 -> 4.x -> 5.0) behind one call.
5. **Non-destructive.** Never overwrite a user file. Saves go to new versioned files.
6. **Small context footprint.** SKILL.md routes; references load only when the task needs them.

## Layers

```
SKILL.md                      orchestrator: loop, hard rules, routing table, CLI cheat sheet
│
├── references/               knowledge, loaded on demand (one file per discipline)
│   ├── workflow-qa.md        production loop, inspection protocol, defect catalogue, definition of done
│   ├── compatibility.md      version matrix, API breaks, probing rules
│   ├── python-api.md         bpy patterns, data API vs operators, headless pitfalls, error catalogue
│   ├── modeling.md           hard-surface, bmesh, modifier stacks, topology, booleans
│   ├── materials.md          Principled BSDF v2, procedural recipes, PBR texture sets, colour
│   ├── geometry-nodes.md     building node trees from Python, scatter/array/terrain recipes
│   ├── lighting-camera.md    light rigs, world, exposure, composition, lenses, DOF
│   ├── rendering.md          Cycles vs EEVEE Next, budgets per hardware, compositor, output, animation
│   ├── animation-rigging.md  keyframes, slotted actions, constraints, armatures, skinning, camera moves
│   ├── physics.md            rigid body, cloth, particles, baking headless
│   ├── scene-performance.md  naming, collections, linking, files, polycount budgets, optimisation
│   ├── image-to-3d.md        Mode 1/2/3 reconstruction, selector, local AI matrix + gating, game prep
│   └── troubleshooting.md    symptom -> cause -> fix, for scripts and for pictures
│
├── scripts/
│   ├── bk.py                 CLI (system Python, stdlib only): which | probe | run | exec | inspect |
│   │                         validate | preview | render | imgcheck
│   ├── _bootstrap.py         runs inside Blender: sys.path, args, exception capture, result protocol, safe save
│   ├── probe_env.py          capability probe -> JSON (+ --bench device benchmark)
│   ├── inspect_blend.py      scene report -> JSON
│   ├── validate_blend.py     QA rules -> issues with severity + fix hints
│   ├── preview_blend.py      multi-view contact sheets (clay/material/random/wire) + beauty shot
│   ├── render_blend.py       quality presets, stills, frame ranges, MP4 encode, post-render imgcheck
│   ├── imgcheck.py           exposure/clipping/noise/flatness analysis
│   ├── build_from_spec.py    declarative JSON scene -> .blend
│   ├── export_blend.py       GLB/glTF/FBX/OBJ/USD export + re-import verification
│   ├── pipeline.py           spec -> build -> validate -> preview -> render -> export -> report
│   ├── package_skill.py      ZIP for claude.ai upload (folder as top-level entry)
│   ├── procstats.py          peak RAM / CPU time of a finished child process (Windows + POSIX)
│   ├── analyze_image.py      reference images -> style, grid, palette, segments, cross-view consistency
│   ├── ai3d/                 Mode 3, standard library only, NEVER inside Blender's Python
│   │   ├── hwprobe.py        GPU (nvidia-smi / registry), VRAM, compute capability, driver CUDA ceiling, RAM, disk
│   │   ├── models.json       researched registry: licence, commercial terms, VRAM, CUDA, CPU, texture, sources
│   │   ├── check.py          per-model verdict gpu | cpu | none with reasons (the gate)
│   │   ├── install_model.py  dry run by default; isolated venv in ~/.cache/blender-master/ai3d
│   │   ├── run_model.py      own process, low priority, offline, timeout, stats -> GLB
│   │   ├── select_mode.py    Mode 1/2/3 scores with reasons, hybrid plans, inferred-surface list
│   │   └── adapters/         triposr_infer.py (runs in the venv) + shims (torchmcubes, rembg)
│   └── bkit/                 helper library imported by every build script
│       ├── runtime.py        emit/warn/save (no-overwrite guard, versioned saves)
│       ├── compat.py         version gates, engine ids, socket aliases, enum probing, overrides
│       ├── scene.py          reset, collections, naming, parenting, refresh, append/link, purge
│       ├── mesh.py           builders (box/cyl/sphere/torus/lathe/extrude/tube), modifiers, finish stack,
│       │                     transforms, normals, UVs, exact bounds, stats
│       ├── materials.py      colour conversion, Principled builder, node helper, 15 presets, PBR loader
│       ├── geonodes.py       GN builder + terrain / scatter / instance_grid recipes
│       ├── assets.py         seeded procedural stand-ins (rocks, trees, bushes, grass)
│       ├── lighting.py       lights, three-point rig, sky/HDRI/gradient worlds, camera-aware cyclorama
│       ├── camera.py         look-at, exact auto-framing, DOF, orbit/dolly/rack focus
│       ├── render.py         engines/devices/tiers, colour management, compositor, output,
│       │                     auto_exposure (grey-card metering), estimate
│       ├── video.py          PNG sequence -> MP4 via the sequencer (no double tone-mapping)
│       ├── preview.py        contact sheets, isolated inspection views, frame strips, beauty shots
│       ├── anim.py           keys (incl. data./node sockets), easing, cycles, noise, motion_report
│       ├── rig.py            armatures (deterministic rolls), IK, binding, weight report, mannequin, walk
│       ├── physics.py        rigid/cloth/collision, frame stepping, headless bake, settle report
│       ├── inspect.py        scene report, mesh health, intersections, camera coverage, image stats
│       ├── validate.py       rule engine used by validate_blend.py
│       ├── imageref.py       image measuring (numpy): masks, palettes, segments, class maps,
│       │                     morphology, straight members, line segments, corner radius, IoU
│       ├── recon.py          voxel / components / hull / lathe / extrude / inflate builders, reference
│       │                     planes, projection texturing, registration, silhouette compare, AI import+align
│       └── gameprep.py       cleanup, normalize, decimate, LODs, material baking, engine export + verify
│
├── examples/                 spec_desk.json + README (which example to start from)
└── tests/
    ├── scenarios/            s01..s09 build scripts (one capability each)
    ├── image_to_3d/          make_refs.py (reference sets), t1..t5 cases, common.py (QA/export),
    │                         run_i3d_tests.py (selector -> build -> acceptance -> overview.png)
    ├── run_tests.py          build -> validate -> assertions -> render -> imgcheck -> RESULTS.md + overview.png
    └── TESTING.md            method, results, defects found and fixed, limitations
```

## Runtime model

```
Claude ──writes──> build_step.py ──python bk.py run──> blender -b [in.blend] --python _bootstrap.py
                                                          │  sys.path += scripts/  (bkit importable)
                                                          │  runpy(build_step.py)   exceptions -> structured error
                                                          │  optional safe save (never overwrites)
                                                          └─ prints @@BKIT_RESULT@@ {json}
Claude <──JSON result + filtered log── bk.py
Claude ──bk.py validate / preview──> PNG contact sheet ──Read tool──> visual critique ──> next fix
```

* `--python-exit-code 1` makes Python exceptions fail the process (Blender exits 0 otherwise).
* `--factory-startup` by default so user add-ons and prefs cannot change results;
  `--user-prefs` opts back in when a file needs an add-on.
* Auto-run of scripts embedded in `.blend` files stays disabled (security).

## Quality gates (enforced by `validate`)

| Gate | Check |
|---|---|
| References | missing images / libraries, absolute paths outside project |
| Geometry | non-manifold, loose parts, zero-area faces, inverted normals, unapplied / negative scale |
| Intersections | BVH overlap between distinct objects (warn; whitelisted for intentional kitbash) |
| Budget | evaluated triangle count per object and per scene vs target tier |
| Materials | objects without material, legacy/unsupported settings, missing UVs on image-mapped meshes |
| Camera | scene camera exists, subject inside frame, subject fills a sensible share of frame |
| Lighting | world/lights present, rendered image not under/over-exposed (imgcheck) |
| Render | engine/device/samples/denoise sensible for the requested tier, colour management |
| Organisation | default names (`Cube.001`), empty collections, orphan data |

## Hardware-aware defaults (this machine)

| Engine | 640x360 default cube | Note |
|---|---|---|
| Workbench | 2.1 s | geometry previews |
| EEVEE Next | 26 s first render | shader compile dominates; later frames are fast |
| Cycles CPU 64 spp + OIDN | 2.5 s | 16 threads |
| Cycles CUDA 64 spp + OIDN | 2.1 s | 4 GB VRAM (Maxwell): heavy scenes must fall back to CPU |

## Image-to-3D process model

```
reference images ──analyze_image.py (Blender)──> analysis.json ──select_mode.py──> Mode 1 | 2 | 3 | hybrid
                                                          check.py (hardware gate) ─┘
Mode 3: run_model.py ──separate venv process (low priority, offline)──> GLB ──recon.import_mesh/align──┐
Mode 1/2: recon + imageref builders inside Blender ───────────────────────────────────────────────────┤
                                       common pipeline: normalize -> compare_views -> bake -> report ─┘
                                       -> GLB (Godot) + FBX (Unity), each re-imported and verified
```
AI inference never runs inside Blender: a crash, an out-of-memory kill or a hung model cannot take
the Blender session down, and Blender's Python never receives PyTorch.

## Extension points (not in v1)

* Live bridge add-on (socket server inside a GUI session) for interactive work on an open file.
* Asset sources: Poly Haven / user asset libraries; Meshy (AI mesh generation, paid credits,
  needs explicit cost confirmation) — an add-on for it is installed on this machine.
