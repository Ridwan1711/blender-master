"""Analyse reference images for image-to-3D (runs inside Blender via bk.py).

python bk.py run scripts/analyze_image.py -- front=a.png side=b.png [top=c.png] [--out analysis.json] [--debug-dir DIR]
(plain paths without view= are accepted too and labelled view1, view2, ...)

Per image: size, object bbox/aspect, style hint (pixel-art / flat / illustration / photo),
pixel grid, flatness, symmetry, palette, colour segments with pixel boxes, hole count.
Across views: are they the same object at the same scale? (height agreement, shared palette).
Feed the JSON to scripts/ai3d/select_mode.py.
"""
import json
import os
import sys

import numpy as np
from bkit import emit
from bkit import imageref as IR

args = sys.argv[1:]
out = args[args.index("--out") + 1] if "--out" in args else None
dbg = args[args.index("--debug-dir") + 1] if "--debug-dir" in args else None
items = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--out", "--debug-dir"))]
views = {}
for i, a in enumerate(items):
    k, _, p = a.partition("=") if "=" in a and not os.path.exists(a) else ("view%d" % (i + 1), "", a)
    views[k] = p
res = {"views": {}}
for k, p in views.items():
    a = IR.analyze(p, debug_png=os.path.join(dbg, "dbg_%s.png" % k) if dbg else None)
    a["segments"] = a["segments"][:20]
    res["views"][k] = a
# cross-view consistency (orthographic views of one object share height and palette)
# top views show DEPTH, not height: leave them out of the height agreement
ks = [k for k in res["views"] if "bbox_px" in res["views"][k] and k != "top"]
if len(ks) > 1:
    hs = {k: res["views"][k]["bbox_px"][3] - res["views"][k]["bbox_px"][1] for k in ks}
    hmax = max(hs.values())
    pal = {k: np.array([c["rgb"] for c in res["views"][k]["palette"][:5]]) for k in ks}
    base = ks[0]
    shared = {}
    for k in ks[1:]:
        d = np.min(np.linalg.norm(pal[base][:, None] - pal[k][None], axis=2), axis=1)
        shared[k] = round(float((d < 0.08).mean()), 2)
    height_agree = round(min(hs.values()) / hmax, 3)
    res["consistency"] = {"heights_px": hs, "height_agreement": height_agree, "palette_overlap_vs_%s" % base: shared,
                          "same_object_likely": height_agree > 0.9 and all(v >= 0.4 for v in shared.values()),
                          "note": "orthographic views of one object should agree in height (top views excepted)"}
res["n_views"] = len(views)
if out:
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
emit(analysis={k: {kk: v[kk] for kk in ("style_hint", "object_aspect_w_over_h", "symmetry_lr", "flatness",
                                        "pixel_art", "holes") if kk in v} | {"palette": [c["hex"] for c in v.get("palette", [])[:6]],
                                                                             "segments": len(v.get("segments", []))}
               for k, v in res["views"].items()},
     consistency=res.get("consistency"), written=out)
