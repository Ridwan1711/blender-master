"""T4 - Hard-surface walkie-talkie from a 3-view blueprint (front, side, top). Mode 2.

Selector: style=flat blueprint, category=equipment, 3 views -> Mode 2 (7) > Mode 1 (5).
Workflow:
  * scale anchor: the body is 160 mm tall (the blueprint's one dimension); all three views share
    the sheet scale - checked: body width front vs top, depth side vs top, height front vs side.
  * body: rounded box; the corner radius is FITTED in all three views (imageref.corner_radius).
  * turned parts (antenna, knob): front width == side width and the top view shows circles ->
    lathe of the measured row profile (steps and domed tips come for free).
  * belt clip: side view (Y, Z) + top view (X); PTT key: side view, protrusion limited by the front
    view (it shows none -> <= 1 px); grille holes, recessed screen, buttons: front view, depths
    limited the same way by the side view.
  * colour: the drawings are projected onto the model (recon.project_views); faces nobody drew
    (back, left, bottom) get the plain body colour (infer="plain") - no invented screen on the back.
"""
import colorsys
import math
import os

import bpy
import numpy as np
from bkit import compat, emit
from bkit import imageref as IR
from bkit import mesh as M
from bkit import recon as RC
from bkit import scene as S
import common

a = common.args()
t = common.Timer()
S.new_scene()
R_ = os.path.join(a.refs, "walkie_talkie")
views = {k: os.path.join(R_, k + ".png") for k in ("front", "side", "top")}
BODY_H = 0.160                     # scale anchor (blueprint dimension)
V = RC.load_views(views)
mF, mS, mT = V["front"]["mask"], V["side"]["mask"], V["top"]["mask"]


def classify(rgb):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if s > 0.12 and 0.2 < h < 0.45:
        return "screen"
    if v < 0.115:
        return "grille"
    if v < 0.155:
        return "part"       # knobs, antenna, buttons, clip
    if v < 0.21:
        return "panel"
    if v < 0.28:
        return "body"
    return "ptt"


CF = IR.class_map(V["front"]["img"], mF, classify)[0]
CS = IR.class_map(V["side"]["img"], mS, classify)[0]
CT = IR.class_map(V["top"]["img"], mT, classify)[0]


def body_rows(mask):
    w = mask.sum(1)
    ys = np.nonzero(w >= 0.6 * np.median(w[w > 0]))[0]    # median: the belt clip widens some rows
    return int(ys.min()), int(ys.max()) + 1


def row_extent(mask, row):
    xs = np.nonzero(mask[row])[0]
    return int(xs.min()), int(xs.max()) + 1


# ---------------------------------------------------------------- scale + body
fy0, fy1 = body_rows(mF)
PX = BODY_H / (fy1 - fy0)
fx0, fx1 = row_extent(mF, (fy0 + fy1) // 2)
W = (fx1 - fx0) * PX
cxF = (fx0 + fx1) / 2
sy0, sy1 = body_rows(mS)
sx0, sx1 = row_extent(mS, sy1 - int(0.25 * (sy1 - sy0)))      # lower quarter: below the belt clip
D = (sx1 - sx0) * PX
cxS = (sx0 + sx1) / 2
H_side = (sy1 - sy0) * PX
tb = IR.bbox(mT)
tx0, tx1 = row_extent(mT, tb[3] - 1 - int(0.25 * D / PX))      # a row inside the body footprint
W_top = (tx1 - tx0) * PX
cxT = (tx0 + tx1) / 2


def zF(y):
    return (fy1 - np.asarray(y, float)) * PX


def xF(x):
    return (np.asarray(x, float) - cxF) * PX


def zS(y):
    return (sy1 - np.asarray(y, float)) * PX


def yS(x):
    return (np.asarray(x, float) - cxS) * PX


def xT(x):
    return (np.asarray(x, float) - cxT) * PX


def yT(row):                       # top view: image down = front (-Y); the bottom edge is the front face
    return -D / 2 + (tb[3] - np.asarray(row, float)) * PX


body_only_F = mF.copy()
body_only_F[:fy0] = False
radii = {"front": IR.corner_radius(body_only_F, "bottom-left")[0] * PX,
         "side": IR.corner_radius(mS, "bottom-left")[0] * PX,
         "top": IR.corner_radius(mT, "bottom-left")[0] * PX}
R = float(np.median(list(radii.values())))
body = M.box("GEO_Body", (W, D, BODY_H), origin="BOTTOM", coll="Walkie")
M.bevel(body, width=R, segments=5, angle=30, harden=False)   # normals are set AFTER the booleans
M.apply_modifiers(body)
t.lap("measure_body_s")

# ---------------------------------------------------------------- turned parts above the body (lathe)
lathes = []
above_side = mS.copy()
above_side[sy0:] = False
side_rows_centre = {}
for y in range(sy0):
    xs = np.nonzero(above_side[y])[0]
    if len(xs):
        side_rows_centre[y] = (xs.min() + xs.max() + 1) / 2
top_parts = [{"x": float(xT(b["centroid_px"][0])), "y": float(yT(b["centroid_px"][1])),
              "d": float((b["bbox_px"][2] - b["bbox_px"][0]) * PX)} for b in IR.blobs(CT.get("part", mT & False), 30)]
above = mF.copy()
above[fy0:] = False
for i, b in enumerate(sorted(IR.blobs(above, 20), key=lambda b_: b_["bbox_px"][0])):
    x0, y0, x1, y1 = b["bbox_px"]
    prof, cents = [], []
    for y in range(y1 - 1, y0 - 1, -1):                      # bottom -> top
        xs = np.nonzero(above[y, x0:x1])[0]
        if not len(xs):
            continue
        r = (xs.max() + 1 - xs.min()) * PX / 2
        cents.append(x0 + (xs.min() + xs.max() + 1) / 2)
        prof.append((r, float(zF(y + 0.5))))
    # drop interior points of equal-radius runs (crisp steps, light mesh)
    keep = [p for j, p in enumerate(prof) if j in (0, len(prof) - 1)
            or abs(p[0] - prof[j - 1][0]) > 1e-6 or abs(p[0] - prof[j + 1][0]) > 1e-6]
    z_base = BODY_H - 0.003                                   # sunk 3 mm into the body (hidden)
    profile = [(0.0, z_base), (keep[0][0], z_base)] + keep + [(0.0, float(zF(y0)))]
    cx = float(xF(np.median(cents)))
    srows = [side_rows_centre[y] for y in range(y0, y1) if y in side_rows_centre]
    cy = float(yS(np.median(srows))) if srows else 0.0
    ob = M.lathe("GEO_Turned%d" % i, profile, segments=24, location=(cx, cy, 0.0), coll="Walkie")
    near = min(top_parts, key=lambda p: math.hypot(p["x"] - cx, p["y"] - cy)) if top_parts else None
    lathes.append({"x": round(cx, 4), "y": round(cy, 4), "height_m": round(float(zF(y0)) - BODY_H, 4),
                   "radii_mm": sorted({round(p[0] * 1000, 1) for p in keep if p[0] > 0.0015}),
                   "top_view_match_mm": round(1000 * math.hypot(near["x"] - cx, near["y"] - cy), 2) if near else None})

# ---------------------------------------------------------------- belt clip (side: Y/Z, top: X)
behind = mS & (np.arange(mS.shape[1])[None, :] >= sx1)
clip = None
cb = IR.blobs(behind, 20)
if cb:
    x0, y0, x1, y1 = cb[0]["bbox_px"]
    behind_top = mT & (np.arange(mT.shape[0])[:, None] < tb[3] - int(round(D / PX)))
    tcb = IR.bbox(behind_top)
    cxa, cxb = (float(xT(tcb[0])), float(xT(tcb[2]))) if tcb else (-W / 2, W / 2)
    ya, yb = D / 2 - 0.002, float(yS(x1))
    za, zb = float(zS(y1)), float(zS(y0))
    ob = M.box("GEO_Clip", (cxb - cxa, yb - ya, zb - za), location=((cxa + cxb) / 2, (ya + yb) / 2, (za + zb) / 2),
               coll="Walkie")
    M.bevel(ob, width=0.002, segments=2, harden=False)
    M.apply_modifiers(ob)
    clip = {"x": [round(cxa, 4), round(cxb, 4)], "y": [round(ya, 4), round(yb, 4)], "z": [round(za, 4), round(zb, 4)]}

# ---------------------------------------------------------------- front details
PROUD = 0.5 * PX                    # neither the side nor the front silhouette shows these: <= 1 px
holes = IR.blobs(CF.get("grille", mF & False), 6)
cut_parts = []
for i, b in enumerate(holes):
    x0, y0, x1, y1 = b["bbox_px"]
    cut_parts.append(M.cylinder("CUT_Hole%d" % i, radius=(x1 - x0) * PX / 2, depth=0.004, segments=12,
                                location=(float(xF((x0 + x1) / 2)), -D / 2, float(zF((y0 + y1) / 2))),
                                rotation=(math.radians(90), 0, 0)))
screen = IR.blobs(CF.get("screen", mF & False), 30)
if screen:
    x0, y0, x1, y1 = screen[0]["bbox_px"]
    cut_parts.append(M.box("CUT_Screen", ((x1 - x0) * PX, 0.002, (y1 - y0) * PX),
                           location=(float(xF((x0 + x1) / 2)), -D / 2, float(zF((y0 + y1) / 2)))))
if cut_parts:
    cutter = M.join(cut_parts, "CUT_Front")
    M.boolean(body, cutter, solver="EXACT")
    M.apply_modifiers(body)
    bpy.data.objects.remove(cutter, do_unlink=True)
# shading AFTER the booleans: sharp by angle + face-area weighted normals (custom normals made
# before cutting smeared dark streaks around every grille hole - found by inspection)
compat.shade_smooth(body, angle_deg=30)
M.weighted_normals(body)
M.apply_modifiers(body)
buttons = [b for b in IR.blobs(CF.get("part", mF & False), 30) if b["bbox_px"][1] > fy0 + R / PX]
for i, b in enumerate(buttons):
    x0, y0, x1, y1 = b["bbox_px"]
    ob = M.box("GEO_Button%d" % i, ((x1 - x0) * PX, 2 * PROUD, (y1 - y0) * PX),
               location=(float(xF((x0 + x1) / 2)), -D / 2, float(zF((y0 + y1) / 2))), coll="Walkie")
ptt = IR.blobs(CS.get("ptt", mS & False), 20)
if ptt:
    x0, y0, x1, y1 = ptt[0]["bbox_px"]
    M.box("GEO_PTT", (2 * PROUD, (x1 - x0) * PX, (y1 - y0) * PX),
          location=(W / 2, float(yS((x0 + x1) / 2)), float(zS((y0 + y1) / 2))), coll="Walkie")
t.lap("build_s")

parts = [o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith("CUT_")]
radio = M.join(parts, "GEO_WalkieTalkie")
proj = RC.project_views(radio, views, size=1024, infer="plain")
t.lap("join_project_s")
res = common.finish(radio, views, a.out, "walkie_talkie", t, height_m=None, preview_mode="texture",
                    ref_m_per_px=PX)
emit(case="walkie_talkie", mode="2 reference-based (3 views)",
     measurements={"mm_per_px": round(PX * 1000, 4), "W_mm": round(W * 1000, 2), "D_mm": round(D * 1000, 2),
                   "H_mm": round(BODY_H * 1000, 2), "corner_radius_mm": {k: round(v * 1000, 2) for k, v in radii.items()},
                   "turned_parts": lathes, "clip": clip, "grille_holes": len(holes),
                   "hole_d_mm": round(float(np.median([(b["bbox_px"][2] - b["bbox_px"][0]) * PX * 1000 for b in holes])), 2)
                   if holes else None, "screen": bool(screen), "buttons": len(buttons), "ptt": bool(ptt)},
     consistency={"W_front_vs_top_mm": [round(W * 1000, 2), round(W_top * 1000, 2)],
                  "H_front_vs_side_mm": [round(BODY_H * 1000, 2), round(H_side * 1000, 2)]},
     inferred=["grille hole depth 2 mm, screen recess 1 mm", "button/PTT protrusion %.2f mm (not visible in the "
               "perpendicular view -> <= 1 px)" % (PROUD * 1000), "clip sunk 2 mm into the body",
               "back/left/bottom faces: plain body colour"],
     projection=proj, **res)
