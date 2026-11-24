# Rendering & post-processing

## Engine choice

| Engine | Use | Measured here (Ryzen 7 1700 / GTX 750 Ti 4 GB) |
|---|---|---|
| Workbench | geometry/layout previews, contact sheets | ~0.5-2 s per view |
| EEVEE Next (`compat.set_engine(sc, "EEVEE")`) | animation, stylised, fast look-dev | 1st frame 26-38 s (shader compile), then ~4.2 s/frame 960x540 with DOF + motion blur (S05) |
| Cycles | photoreal, glass, interiors, final stills | S01 34 s (1280x960, 128 spp), S03 40 s (1280x720, 810k tris), S04 60 s (1440x900), S06 7 min (1280x854, 256 spp, closed interior) |

EEVEE lacks Cycles-only nodes (Bevel node edge wear, some light paths); check the look in the
engine you will deliver with.

## One-call setup

```python
R.configure(engine="CYCLES", quality="preview"|"draft"|"final", resolution=(1920,1080),
            device="AUTO"|"CPU"|"GPU", view="AgX", look="None", exposure=0.0,
            transparent=False, motion_blur=False, samples=None)
```
| Tier | Cycles spp (adaptive threshold) | bounces | EEVEE samples |
|---|---|---|---|
| preview | 32 (0.1) | 4 | 16 |
| draft | 128 (0.03) | 8 | 32 + raytracing |
| final | 512 (0.01) | 12 | 128 + raytracing |
Always: OIDN denoise (albedo+normal), indirect clamp 10, caustics off, filter glossy 1.0.

Device: AUTO picks a GPU if present (env `BKIT_DEVICE=CPU|GPU` overrides). On cards with <= 4 GB
VRAM prefer CPU for large scenes; run `bk.py probe -- --bench` to measure instead of guessing.

## View transforms (colour management)

| View | When | Measured behaviour |
|---|---|---|
| AgX (4.0+ default) | photoreal scenes with bright lights/sun | graceful highlights; bright saturated colours go pastel |
| Khronos PBR Neutral (4.2+) | product/e-commerce colour fidelity | keeps hues; harder highlight roll-off |
| Filmic (3.x) | legacy matching | hue skew (bright orange -> yellow) |
| Standard | UI, graphics, previews | clips at 1.0 |
Looks: `"Punchy"`, `"Medium High Contrast"` etc. (`look=` is prefixed with the view name for you).
Grey-card targets per view: lighting-camera.md.

## Compositor (`render.mist`, `render.glare`)

- `R.mist(start, depth, color, strength)` - aerial perspective via the Mist pass (cheap; S03).
- `R.glare(kind="BLOOM", threshold, strength)` - bloom/glow (EEVEE Next has no built-in bloom).
- 4.4/4.5 moved several node options to sockets; 5.0 makes the compositor a node group with a
  Group Output (handled by `compat.compositor_tree`, untested on 5.x).
- Inspection previews disable compositing (otherwise mist washes them grey).

## Output

- Stills: PNG 8-bit for review, 16-bit PNG / EXR (multilayer) for grading.
- Animation: render a PNG sequence (crash-safe, resumable, parallelisable), then encode:
  `bk.py render s.blend --out out/f_ --frames 1-72 --video out/shot.mp4`
  (`video.encode_sequence`: VSE scene with **Standard** view - frames are already tone-mapped; AgX
  again would wash them out). H.264 needs even width/height.
- Verify videos: load as a movie clip and check frame count/size/fps (done in S05: 72 f, 960x540, 24).
- Transparent background: `transparent=True` + PNG RGBA.

## Time management

- `R.estimate(scene, scale=0.25)` renders at quarter resolution and extrapolates (pixels scale ~linearly).
- Long renders: run `bk.py render` in the background; never block on a 30-minute render without telling the user.
- Animations on slow hardware: EEVEE or Cycles at preview tier + denoise; check a frame strip first.

## Post-render QA (`bk.py imgcheck` / `inspect.image_stats`)

Reports mean/median/p05/p95 luminance, clipped %, crushed %, fireflies, saturation and a verdict:
FLAT (empty frame), DARK, BRIGHT, CRUSHED, NOISY. Intentional low-key/high-key images trigger
DARK/BRIGHT - judge with your eyes and tell the user it is intentional.
`inspect.sample_object(png, obj)` reads the rendered value at an object (grey-card checks).
