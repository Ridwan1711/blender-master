"""T3 - Medieval half-timbered house from two elevations (gable end + long side). Mode 2.

Selector: style=flat (elevation drawings), category=building -> Mode 2 (6) > Mode 1 (5).
Workflow, as a modeller works from an elevation set:
  1. classify every pixel (stone / plaster / timber / roof / window) - imageref.class_map
  2. ONE scale anchor (the brief: the gable end is 6 m wide), measured at ground level where
     nothing overhangs; the side elevation shares the drawing scale (checked, not assumed:
     stone height and roof eave edge must agree between the two views)
  3. measure: gable eave/ridge from a line fit of the wall width per row, roof edge/top/thickness/
     overhangs, stone plinth height, openings (blobs), door + arch (morphological opening),
     timber posts/rails (straight runs) and braces (principal axes of the remaining strokes)
  4. build: extruded gable walls, stone plinth, recessed openings (booleans), proud timber,
     roof slabs, chimney; procedural materials are BAKED for the engine export.
Inference policy (reported in the result, never hidden):
  * back gable and far long side are not drawn -> frame + windows mirrored from the visible
    facades (no door invented); flagged as inferred.
  * the chimney is in the side elevation only -> its X is derived from where it leaves the roof
    slope, its X size assumed square; the front elevation omits it (reference inconsistency).
"""
import colorsys
import math
import os

import bpy
import numpy as np
from bkit import emit
from bkit import imageref as IR
from bkit import materials as MT
from bkit import mesh as M
from bkit import recon as RC
from bkit import scene as S
import common

a = common.args()
t = common.Timer()
S.new_scene()
R = os.path.join(a.refs, "medieval_house")
views = {"front": os.path.join(R, "front.png"), "side": os.path.join(R, "side.png")}
WIDTH_M = 6.0      # the only real-world number given: the gable end is 6 m wide (scale anchor)
V = RC.load_views(views)


def classify(rgb):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    hd = h * 360
    if v < 0.25 and s < 0.35:
        return "window"
    if s < 0.12:
        return "stone"
    if v > 0.8 and s < 0.3:
        return "plaster"
    if (hd < 15 or hd > 345) and s > 0.5:
        return "roof"
    if 15 <= hd <= 40 and v < 0.45:
        return "timber"
    return "other"


CM = {v: IR.class_map(V[v]["img"], V[v]["mask"], classify)[0] for v in ("front", "side")}
F, SD = CM["front"], CM["side"]
mF, mS = V["front"]["mask"], V["side"]["mask"]


def cls(d, *names):
    out = np.zeros(next(iter(d.values())).shape, bool)
    for n in names:
        if n in d:
            out |= d[n]
    return out


def ground_extent(mask):
    b = IR.bbox(mask)
    band = mask[b[3] - max(2, (b[3] - b[1]) // 50): b[3]]
    xs = np.nonzero(band.any(0))[0]
    return int(xs.min()), int(xs.max()) + 1, b[3]


# ---------------------------------------------------------------- 2. scale
fx0, fx1, gyF = ground_extent(mF)
PX = WIDTH_M / (fx1 - fx0)                 # metres per pixel (both elevations: same sheet scale)
cxF = (fx0 + fx1) / 2
sx0, sx1, gyS = ground_extent(mS)
cxS = (sx0 + sx1) / 2
DEPTH = (sx1 - sx0) * PX


def zF(y):
    return (gyF - np.asarray(y, float)) * PX


def xF(x):
    return (np.asarray(x, float) - cxF) * PX


def zS(y):
    return (gyS - np.asarray(y, float)) * PX


def yS(x):                                 # side column -> world Y (image right = back = +Y)
    return (np.asarray(x, float) - cxS) * PX


# ---------------------------------------------------------------- 3. measure
# gable: wall width per row is W up to the eave, then falls linearly to 0 at the ridge
wallF = cls(F, "stone", "plaster", "timber", "window")
rows = np.arange(mF.shape[0])
zc = zF(rows + 0.5)
wid = wallF.sum(1) * PX
sel = (wid > 0.2 * WIDTH_M) & (wid < 0.85 * WIDTH_M) & (zc > 1.0)
k_, c_ = np.polyfit(zc[sel], wid[sel], 1)
EAVE, RIDGE = float((WIDTH_M - c_) / k_), float(-c_ / k_)
# roof (front: eave edge, top, vertical slab thickness, eave overhang; side: gable overhang)
bF = IR.bbox(mF)
roofF, roofS = F["roof"], SD["roof"]
ROOF_TOP = float(zF(bF[1]))
ROOF_EDGE = float(zF(np.nonzero(roofF.any(1))[0].max() + 1))
XE = float(max(abs(xF(bF[0])), abs(xF(bF[2]))))
lr = IR.longest_runs(roofF, axis=0)
TV = float(np.median([lr[x][0] for x in range(bF[0], bF[2]) if 0.15 * XE < abs(xF(x + 0.5)) < 0.75 * XE])) * PX
rbS = IR.bbox(roofS)
OVER_Y = ((rbS[2] - rbS[0]) * PX - DEPTH) / 2


def stone_top(stone, zmap, x0, x1):
    cov = stone[:, x0:x1].mean(1)
    return float(zmap(np.nonzero(cov >= 0.5)[0].min()))


STONE_TOP_F, STONE_TOP_S = stone_top(F["stone"], zF, fx0, fx1), stone_top(SD["stone"], zS, sx0, sx1)


def frame(T, zmap, umap):
    """Door (solid timber blob), posts, rails and braces of one facade, in metres (u, z)."""
    blob = IR.opening(T, max(3, int(round(0.2 / PX))))
    door = None
    for b in IR.blobs(blob, min_px=int((0.5 / PX) ** 2)):
        x0, y0, x1, y1 = b["bbox_px"]
        if zmap(y1) < 0.1:                                   # standing on the ground
            widths = blob[y0:y1, x0:x1].sum(1)
            spring_row = y0 + int(np.nonzero(widths >= 0.95 * widths.max())[0].min())
            w = (x1 - x0) * PX
            top = float(zmap(y0))
            rise = top - float(zmap(spring_row))
            door = {"u": [float(umap(x0)), float(umap(x1))], "z": [0.0, top],
                    "arch": "semicircular" if rise > 0.25 * w else None, "rise_m": round(rise, 3)}
            break
    L = int(round(1.5 / PX))
    wmax = int(round(0.3 / PX))
    vm = IR.straight_members(T, L, axis=0, max_width_px=wmax)
    hm = IR.straight_members(T, L, axis=1, max_width_px=wmax)
    posts = [{"u": [float(umap(m["across"][0])), float(umap(m["across"][1]))],
              "z": [float(zmap(m["along"][1])), float(zmap(m["along"][0]))]} for m in vm]
    rails = [{"u": [float(umap(m["along"][0])), float(umap(m["along"][1]))],
              "z": [float(zmap(m["across"][1])), float(zmap(m["across"][0]))]} for m in hm]
    cover = IR.dilate(blob, 2)
    for m in vm:
        cover[m["along"][0]:m["along"][1], m["across"][0]:m["across"][1]] = True
    for m in hm:
        cover[m["across"][0]:m["across"][1], m["along"][0]:m["along"][1]] = True
    rest = T & ~IR.dilate(cover, 3)
    near = IR.dilate(cover, 7)
    braces = []
    for sgm in IR.line_segments(rest, min_px=40, min_elong=4.0):
        p0, p1 = np.array(sgm["p0"]) + 0.5, np.array(sgm["p1"]) + 0.5
        d = (p1 - p0) / max(1e-6, np.linalg.norm(p1 - p0))
        ends = []
        for i, p in enumerate((p0, p1)):                      # re-attach ends trimmed off at joints
            yy, xx = int(min(max(p[1], 0), T.shape[0] - 1)), int(min(max(p[0], 0), T.shape[1] - 1))
            ends.append(p + (d * 4 if i else -d * 4) if near[yy, xx] else p)
        p0, p1 = ends
        braces.append({"a": [float(umap(p0[0])), float(zmap(p0[1]))], "b": [float(umap(p1[0])), float(zmap(p1[1]))],
                       "w": max(0.08, sgm["width_px"] * PX)})
    return door, posts, rails, braces


def windows(Wm, zmap, umap):
    return [{"u": [float(umap(b["bbox_px"][0])), float(umap(b["bbox_px"][2]))],
             "z": [float(zmap(b["bbox_px"][3])), float(zmap(b["bbox_px"][1]))]}
            for b in IR.blobs(IR.opening(Wm, 1), min_px=int((0.2 / PX) ** 2))]


doorF, postsF, railsF, bracesF = frame(F["timber"], zF, xF)
_, postsS, railsS, bracesS = frame(SD["timber"], zS, yS)
winF, winS = windows(F["window"], zF, xF), windows(SD["window"], zS, yS)
# the sill beam sits on the stone plinth: snap the plinth top to its centre line
STONE_H = STONE_TOP_F
for r in railsF:
    if 0 <= (r["z"][0] + r["z"][1]) / 2 - STONE_TOP_F < 0.15:
        STONE_H = (r["z"][0] + r["z"][1]) / 2
# chimney: stone above the roof edge in the side view; X from where it leaves the near roof slope
chim = None
for b in IR.blobs(SD["stone"], min_px=50):
    x0, y0, x1, y1 = b["bbox_px"]
    if zS(y1) > ROOF_EDGE + 0.5:
        z_vis, z_top = float(zS(y1)), float(zS(y0))
        x_face = (ROOF_TOP - z_vis) / (ROOF_TOP - (ROOF_EDGE + TV)) * XE
        w = (x1 - x0) * PX
        chim = {"y": [float(yS(x0)), float(yS(x1))], "z_visible": [round(z_vis, 3), round(z_top, 3)],
                "x": [round(x_face - w, 3), round(x_face, 3)], "x_inferred": True}
        break
meas = {"px_per_m": round(1 / PX, 2), "width": WIDTH_M, "depth": round(DEPTH, 3), "eave": round(EAVE, 3),
        "ridge": round(RIDGE, 3), "stone_h": round(STONE_H, 3), "roof_top": round(ROOF_TOP, 3),
        "roof_edge": round(ROOF_EDGE, 3), "roof_thickness_v": round(TV, 3),
        "overhang_eaves": round(XE - WIDTH_M / 2, 3), "overhang_gables": round(OVER_Y, 3), "door": doorF,
        "chimney": chim}
checks = {"stone_top_front_vs_side": [round(STONE_TOP_F, 3), round(STONE_TOP_S, 3)],
          "roof_edge_front_vs_side": [round(ROOF_EDGE, 3), round(float(zS(rbS[3])), 3)],
          "roof_top_front_vs_side": [round(ROOF_TOP, 3), round(float(zS(rbS[1])), 3)]}
checks["scale_consistent"] = all(abs(p - q) < 0.1 for p, q in checks.values())
RC.setup_references(views, height_m=ROOF_TOP)
t.lap("measure_s")

# ---------------------------------------------------------------- materials
stone = MT.concrete("MAT_Stone", MT.hex_color("#807E78"), roughness=0.9, scale=3.0)
plaster = MT.principled("MAT_Plaster", MT.hex_color("#ECE0C4"), roughness=0.9)
timber = MT.wood("MAT_Timber", light=MT.hex_color("#6A4428"), dark=MT.hex_color("#3E2716"), scale=4.0, axis="Z")
roof_m = MT.principled("MAT_RoofTiles", MT.hex_color("#8B2E1E"), roughness=0.75)
nt = MT.Nodes(roof_m.node_tree)
tc = nt.new("ShaderNodeTexCoord")
wv = nt.new("ShaderNodeTexWave", Scale=6.0, Distortion=0.5)
wv.bands_direction = "Z"
bump = nt.new("ShaderNodeBump", Strength=0.4, Distance=0.05)
ramp = nt.ramp([(0.0, MT.hex_color("#6E2216")[:3]), (0.6, MT.hex_color("#8B2E1E")[:3]), (1.0, MT.hex_color("#9C3A26")[:3])])
nt.link(tc, "Object", wv, "Vector")
nt.link(wv, "Fac", bump, "Height")
nt.link(wv, "Fac", ramp, "Fac")
nt.link(ramp, "Color", nt.bsdf, "Base Color")
nt.link(bump, "Normal", nt.bsdf, "Normal")
dark = MT.principled("MAT_Openings", MT.hex_color("#23262C"), roughness=0.4)
door_m = MT.wood("MAT_Door", light=MT.hex_color("#6B4527"), dark=MT.hex_color("#47301C"), scale=3.0, axis="Z")

# ---------------------------------------------------------------- 4. build
W2, D2, TD, PROUD, RECESS = WIDTH_M / 2, DEPTH / 2, 0.12, 0.10, 0.25
FACADES = {"front": ("x", -1), "back": ("x", 1), "right": ("y", 1), "left": ("y", -1)}
walls = M.extrude_polygon("GEO_Walls", [(-W2, 0.0), (W2, 0.0), (W2, EAVE), (0.0, RIDGE), (-W2, EAVE)], DEPTH,
                          rotation=(math.radians(90), 0, 0), coll="House", center_z=True)
M.apply_transform(walls)
MT.assign(walls, plaster)
plinth = M.box("GEO_Plinth", (WIDTH_M + 0.06, DEPTH + 0.06, STONE_H), origin="BOTTOM", coll="House")
MT.assign(plinth, stone)


def on_facade(name, facade, u0, u1, z0, z1, depth, normal_off, mat):
    """Axis-aligned box on a facade; normal_off = centre distance outside the wall plane."""
    axis, sgn = FACADES[facade]
    off = sgn * ((D2 if axis == "x" else W2) + normal_off)
    uc, w, h = (u0 + u1) / 2, u1 - u0, z1 - z0
    if axis == "x":
        size, loc = (w, depth, h), (uc, off, (z0 + z1) / 2)
    else:
        size, loc = (depth, w, h), (off, uc, (z0 + z1) / 2)
    ob = M.box(name, size, location=loc, coll="House")
    if mat:
        MT.assign(ob, mat)
    return ob


def brace(name, facade, A, B, w):
    axis, sgn = FACADES[facade]
    off = sgn * ((D2 if axis == "x" else W2) + PROUD - TD / 2)
    L, phi = math.hypot(B[0] - A[0], B[1] - A[1]), math.atan2(B[1] - A[1], B[0] - A[0])
    uc, zc_ = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
    if axis == "x":
        ob = M.box(name, (L, TD, w), location=(uc, off, zc_), rotation=(0, -phi, 0), coll="House")
    else:
        ob = M.box(name, (TD, L, w), location=(off, uc, zc_), rotation=(phi, 0, 0), coll="House")
    MT.assign(ob, timber)
    return ob


cutters, n_members, inferred_parts = [], 0, 0
plan = [("front", winF, postsF, railsF, bracesF, False), ("right", winS, postsS, railsS, bracesS, False),
        ("back", winF, postsF, railsF, bracesF, True), ("left", winS, postsS, railsS, bracesS, True)]
for facade, wins, posts, rails, braces, inferred in plan:
    tag = facade[0].upper()
    for i, wn in enumerate(wins):
        cutters.append(on_facade("CUT_Win%s%d" % (tag, i), facade, *wn["u"], *wn["z"], 2 * RECESS, 0.0, None))
        on_facade("GEO_Pane%s%d" % (tag, i), facade, *wn["u"], *wn["z"], 0.03, -RECESS + 0.015, dark)
    for i, m in enumerate(posts + rails):
        u0, u1 = m["u"]
        z0, z1 = m["z"]
        if facade in ("right", "left") and i < len(posts) and z1 > ROOF_EDGE - 0.15:
            z1 = max(z1, EAVE)                       # continues hidden under the eaves
        on_facade("GEO_Beam%s%d" % (tag, i), facade, u0, u1, z0, z1, TD, PROUD - TD / 2, timber)
    for i, b in enumerate(braces):
        brace("GEO_Brace%s%d" % (tag, i), facade, b["a"], b["b"], b["w"])
    n_members += len(posts) + len(rails) + len(braces)
    if inferred:
        inferred_parts += len(wins) + len(posts) + len(rails) + len(braces)
if doorF:
    u0, u1 = doorF["u"]
    w = u1 - u0
    spring = doorF["z"][1] - (w / 2 if doorF["arch"] else 0.0)
    cutters.append(on_facade("CUT_Door", "front", u0, u1, 0.0, spring, 2 * RECESS, 0.0, None))
    on_facade("GEO_DoorLeaf", "front", u0, u1, 0.0, spring, 0.06, -RECESS + 0.03, door_m)
    if doorF["arch"]:
        cutters.append(M.cylinder("CUT_DoorArch", radius=w / 2, depth=2 * RECESS, segments=24,
                                  location=((u0 + u1) / 2, -D2, spring), rotation=(math.radians(90), 0, 0)))
        arch = M.cylinder("GEO_DoorArch", radius=w / 2, depth=0.059, segments=24,
                          location=((u0 + u1) / 2, -D2 + RECESS - 0.03, spring), rotation=(math.radians(90), 0, 0),
                          coll="House")
        MT.assign(arch, door_m)
for host in (walls, plinth):
    for c in cutters:
        M.boolean(host, c, solver="EXACT")
    M.apply_modifiers(host)
for c in cutters:
    bpy.data.objects.remove(c, do_unlink=True)

# roof: two slabs, underside parallel to the measured slope, overhanging eaves + gables
right = [(0.0, ROOF_TOP - TV), (XE, ROOF_EDGE), (XE, ROOF_EDGE + TV), (0.0, ROOF_TOP)]
for nm, prof in (("GEO_RoofR", right), ("GEO_RoofL", [(-x, z) for x, z in reversed(right)])):
    slab = M.extrude_polygon(nm, prof, DEPTH + 2 * OVER_Y, rotation=(math.radians(90), 0, 0), coll="House",
                             center_z=True)
    M.apply_transform(slab)
    MT.assign(slab, roof_m)
if chim:
    (x0, x1), (y0, y1) = chim["x"], chim["y"]
    c = M.box("GEO_Chimney", (x1 - x0, y1 - y0, chim["z_visible"][1] - EAVE),
              location=((x0 + x1) / 2, (y0 + y1) / 2, EAVE), origin="BOTTOM", coll="House")
    MT.assign(c, stone)
t.lap("build_s")

parts = [o for o in bpy.data.objects if o.type == "MESH"]
house = M.join(parts, "GEO_MedievalHouse")
t.lap("join_s")
res = common.finish(house, views, a.out, "medieval_house", t, height_m=None, ref_m_per_px=PX)
emit(case="medieval_house", mode="2 reference-based", measurements=meas, consistency=checks,
     openings={"front": len(winF), "side": len(winS), "door": bool(doorF)},
     frame={"front_posts_rails_braces": [len(postsF), len(railsF), len(bracesF)],
            "side_posts_rails_braces": [len(postsS), len(railsS), len(bracesS)]},
     timber_members=n_members, inferred_parts=inferred_parts,
     inferred=["back gable + far long side: timber frame and windows mirrored from the drawn facades (no door)",
               "chimney X position from where it leaves the roof slope; X size assumed = Y size",
               "side posts continue under the eaves (hidden)"],
     reference_issues=["front elevation omits the chimney the side elevation shows (top %.2f m above the roof)"
                       % ((chim["z_visible"][1] - ROOF_TOP) if chim else 0)], **res)
