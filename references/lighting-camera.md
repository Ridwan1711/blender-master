# Lighting & cinematography

## Conventions

- Azimuth: 0 = in front of the subject (camera on -Y looking +Y), 90 = +X side, 180 = behind.
  Elevation in degrees above the horizon. Used by `camera.frame`, `camera.direction`, `lighting.sun`,
  `world_sky`, `three_point`.
- Lights and cameras aim down their local -Z: `camera.look_at(ob, target)` works for both.

## Camera (`from bkit import camera as C`)

```python
cam = C.add("CAM_Main", lens=50)
C.frame(cam, objs, azimuth=-30, elevation=18, margin=1.2)   # exact projection, binary search
C.dof(cam, focus=hero_or_point, fstop=4)                    # point -> CTL_Focus empty
C.orbit(cam, center, radius, height, frames=(1,120), start_azimuth=-60, sweep=90)
C.dolly(cam, start, end, frames=(1,96), aim=target)          # eased
C.rack_focus(cam, [(1, 1.2), (48, 3.5)], fstop=2.0)
```
- Tag what must be in shot: `obj["bk_subject"] = True` (children included). `validate` checks frame
  status and `subject_fill`; `preview` uses subjects for its inspection views.

| Lens (full frame) | Use |
|---|---|
| 14-24 mm | interiors, vistas, dramatic perspective (distortion at edges) |
| 28-35 mm | environments, establishing, walk-and-talk |
| 50 mm | natural, products in context |
| 85-135 mm | portraits, hero products (flattering, compressed background) |

Composition: subject on thirds or deliberately centred; horizon on a third (S03: aiming 6 m above
water put it in the upper third); leave lead room in the direction of motion/gaze; avoid tangents
(object edges just touching the frame edge or each other); check edges for set ends.

DOF: f/1.4-2.8 strong separation (portrait, macro), f/4-8 products (everything on the subject
sharp), f/11+ architecture. Focus on an empty at the point of interest, not the object origin.

## Light rigs (`from bkit import lighting as L`)

```python
L.three_point(objs, style="product"|"soft"|"dramatic"|"portrait", intensity=1.0)
L.studio_backdrop(cam, objs, color, floor_z=0.0, frames=None)   # after the camera; frames for moving cameras
L.world_sky(sun_elevation, sun_azimuth, strength=0.3, sun_strength=4.0)   # Nishita sky + matching Sun lamp
L.world_gradient(top, bottom, strength); L.world_color(color, strength); L.world_hdri(path, strength, rotation_deg)
L.sun(name, elevation, azimuth, strength, angle); L.light("AREA"|"POINT"|"SPOT", ...); L.kelvin(5600)
```
- Rig placement is relative to the camera and scaled to the subject size (energy ~ distance^2), so
  the same rig works for a 10 cm mug and a 1 m crate.
- Ratios (key:fill:rim): product 1:0.35:0.7, soft 1:0.55:0.4, dramatic 1:0.08:1.3.
- Colour temperature: key warm (5200 K), fill neutral, rim cool (7000 K) gives separation.
- Metals and glossy materials need something to reflect: gradient world or large cards.

## Exposure: meter, don't guess

```python
card = M.box("CTL_TmpGreyCard", (0.08, 0.005, 0.08), location=subject_point)   # albedo 0.18
MT.assign(card, MT.principled("MAT_TmpGrey18", (0.18,)*3, roughness=0.95, specular=0.0))
C.look_at(card, cam.location); card.rotation_euler.x += math.radians(90)
R.auto_exposure(card)          # binary-searches view exposure with tiny renders
bpy.data.objects.remove(card, do_unlink=True); S.purge_orphans()
```
Target display values for an 18% card (measured, Blender 4.5): AgX 0.459, Khronos PBR Neutral
0.408, Filmic 0.498, Standard 0.459. S04 before metering: card 0.68 (+1.6 EV over); after: 0.455.
Metering on a sunlit spot makes shadows dark (S06): meter where the important tones are, or add a
deliberate offset (+0.5..1 EV for airy interiors) and say so.

## Motivated lighting (environments / interiors)

- Interiors: close the room (walls, ceiling, floor) so light enters only through windows/practicals;
  sun lamp aligned with the sky (`world_sky(sun_lamp=True)` does it); expect more noise - raise
  samples, keep denoising, clamp indirect.
- Exteriors: low sun (10-25 deg) gives long shadows and warm light; side or back light reads shape;
  front light (sun behind the camera) is flat. Add mist for depth (`render.mist`).
- Do not light an exterior with a three-point rig; do not light a product with only a sky.

## Defects to look for

Backdrop/floor edge in frame; subject merging with background (no rim/contrast); crushed shadows;
clipped highlights; double shadows from mismatched sun/sky; lights visible in reflections in ugly
ways; colour casts from coloured bounce.
