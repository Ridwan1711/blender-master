# Physics & simulation

## Rigid bodies (`from bkit import physics as P`)

```python
P.rigid_world(frame_start=1, frame_end=120, substeps=10, iterations=10)
P.rigid(floor_slab, "PASSIVE", shape="BOX", friction=0.8)
for b in blocks: P.rigid(b, "ACTIVE", mass=0.8, shape="BOX")
P.rigid(ball, "ACTIVE", mass=25, shape="SPHERE")
P.remember_start(blocks)                 # for the 'moved' metric
P.simulate(1, 120)                       # step frames in order (fills the cache) - headless safe
rep = P.settle_report(blocks + [ball], floor_z=0.0, tol=0.02)
P.bake_to_keyframes(blocks + [ball], 1, 120)   # deterministic file; removes rigid bodies
```
- Shapes: primitives (BOX/SPHERE/CAPSULE/CYLINDER) are fastest and most stable; CONVEX_HULL for
  irregular movers; MESH only for passive concave colliders (terrain).
- Floors: a slab with thickness + BOX.
- Mass in kg, real sizes in metres; very light or very heavy contrasts (25 kg ball vs 0.8 kg blocks)
  need more substeps.
- **Never jump to frame N of an unbaked sim**; step from the start frame.
- `bpy.ops.rigidbody.bake_to_keyframes` fails headless (internal UI-only operator) - bkit records
  matrices per frame and keys them with Euler continuity instead.
- Kinematic start (e.g. thrown objects): animate with `rigid_body.kinematic = True` keys, then switch off.

## Cloth

```python
P.collision(sphere); P.collision(floor)
sheet = M.plane("GEO_Cloth", (1.6, 1.6), location=(x, y, 1.4), subdivisions=40)
P.cloth(sheet, mass=0.3, frame_start=1, frame_end=90)     # quality 10, collision quality 4
M.solidify(sheet, 0.004, even=False); M.subsurf(sheet, 1)   # AFTER cloth in the stack
```
- **Solidify with even thickness after Cloth throws single-frame spikes at sharp folds** (S09: 9 of
  14k vertices jumped 1.2 m on random frames; the simulation itself was fine). Use `even=False`.
- Pin with a vertex group (`pin_group=`); self-collision costs a lot - only when folds touch.
- Memory caches are saved inside the `.blend` and used when a later frame is rendered (verified).

## Verification (always numeric + visual)

| Check | How |
|---|---|
| Nothing tunnelled | `settle_report` (uses exact vertex bounds; bbox corners of rotated bodies overstate extent - S09 phantom 7 cm "sink") |
| Something actually happened | `moved` count vs expected |
| Stable cloth | max/min vertex Z every frame after settling, no spikes |
| Rest state plausible | render final frame; look for interpenetration, floating, jitter |
| Determinism | bake to keys; re-open and compare positions |

S09 results: 15/15 blocks displaced, deepest sink 0.2 mm, cloth top 0.914 m on a 0.90 m sphere,
no spike frames; 90 frames simulated in ~16 s on CPU.

## Other systems (not covered by tested helpers)

Fluids (Mantaflow), smoke/fire, soft bodies, particles (hair), Geometry Nodes simulation zones
(4.0+). They follow the same rules: real scale, step frames in order or bake, measure, look.
Bake heavy sims to disk caches in a project folder and report cache size.
