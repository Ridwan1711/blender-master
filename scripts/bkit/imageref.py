"""Reference-image analysis for image-to-3D (pure numpy; runs inside Blender).

Pixel coordinates are TOP-DOWN (row 0 = top of the picture), like any image editor.
All analysis is measurement, not guessing: use it to set proportions, then LOOK at the image.

    from bkit import imageref as IR
    img = IR.load("front.png")
    m = IR.foreground_mask(img)                 # alpha, else border flood fill
    a = IR.analyze("front.png", debug_png="front_dbg.png")   # summary + labelled debug image
    segs = IR.segments(img, m, k=8)              # colour regions with pixel boxes
    prof = IR.row_profile(m)                     # widths per row (lathe objects)
    loops = IR.contours(m)                       # outlines (extrusion)
    IR.silhouette_iou(mask_a, mask_b)            # shape similarity, scale/position invariant
"""
import math
import os
from collections import deque

import bpy
import numpy as np


# --------------------------------------------------------------------------- io
def load(path):
    """RGBA float32 array (H, W, 4), top-down, values as stored (sRGB for PNG/JPG)."""
    path = os.path.abspath(path)
    im = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        if im.channels == 4:
            im.pixels.foreach_get(px)
            px = px.reshape(h, w, 4)
        else:
            tmp = np.empty(w * h * im.channels, np.float32)
            im.pixels.foreach_get(tmp)
            tmp = tmp.reshape(h, w, im.channels)
            px = np.ones((h, w, 4), np.float32)
            px[..., :3] = tmp[..., :3]
    finally:
        bpy.data.images.remove(im)
    return np.ascontiguousarray(px[::-1])


def save(arr, path):
    """Save an (H, W, 3|4) float array (top-down) as PNG."""
    path = os.path.abspath(path)
    a = np.asarray(arr, np.float32)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    h, w = a.shape[:2]
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :a.shape[2]] = a[..., :4]
    im = bpy.data.images.new("bk_imageref_save", w, h, alpha=True)
    im.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    return path


# --------------------------------------------------------------------------- masks
def foreground_mask(img, tol=0.12, use_alpha=True):
    """Foreground = alpha > 0.5 if the image has transparency, otherwise everything NOT reachable
    from the border through pixels within `tol` of the median border colour (plain backgrounds)."""
    if use_alpha and img[..., 3].min() < 0.99:
        return img[..., 3] > 0.5
    rgb = img[..., :3]
    h, w = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    near = np.linalg.norm(rgb - bg, axis=2) < tol
    seen = np.zeros((h, w), bool)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return ~seen


def bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def crop(mask_or_img, box):
    x0, y0, x1, y1 = box
    return mask_or_img[y0:y1, x0:x1]


def resample_mask(mask, out_w, out_h):
    """Nearest-neighbour resize of a boolean mask."""
    h, w = mask.shape
    ys = np.minimum((np.arange(out_h) + 0.5) * h / out_h, h - 1).astype(int)
    xs = np.minimum((np.arange(out_w) + 0.5) * w / out_w, w - 1).astype(int)
    return mask[ys][:, xs]


def resample_img(img, out_w, out_h):
    h, w = img.shape[:2]
    ys = np.minimum((np.arange(out_h) + 0.5) * h / out_h, h - 1).astype(int)
    xs = np.minimum((np.arange(out_w) + 0.5) * w / out_w, w - 1).astype(int)
    return img[ys][:, xs]


# --------------------------------------------------------------------------- colour
def kmeans(colors, k=8, iters=12, seed=0):
    """Tiny k-means for palettes. colors (N, 3). Returns (centers (k, 3), labels (N,))."""
    rng = np.random.default_rng(seed)
    n = len(colors)
    if n == 0:
        return np.zeros((0, 3)), np.zeros(0, int)
    k = min(k, n)
    sample = colors if n <= 20000 else colors[rng.choice(n, 20000, replace=False)]
    # k-means++ init
    centers = [sample[rng.integers(len(sample))]]
    for _ in range(1, k):
        d = np.min(((sample[:, None] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        if d.sum() == 0:
            break
        centers.append(sample[rng.choice(len(sample), p=d / d.sum())])
    c = np.array(centers)
    for _ in range(iters):
        lab = np.argmin(((sample[:, None] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([sample[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(len(c))])
        if np.allclose(new, c, atol=1e-4):
            break
        c = new
    labels = np.empty(n, int)
    for s in range(0, n, 200000):
        labels[s:s + 200000] = np.argmin(((colors[s:s + 200000, None] - c[None]) ** 2).sum(-1), axis=1)
    return c, labels


def to_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(max(0, min(1, v)) * 255)) for v in rgb[:3])


def palette(img, mask, k=8):
    """Dominant colours inside the mask: [{hex, rgb, fraction}] (sRGB values, as in the file)."""
    cols = img[..., :3][mask]
    c, lab = kmeans(cols, k)
    frac = np.bincount(lab, minlength=len(c)) / max(1, len(lab))
    order = np.argsort(-frac)
    return [{"hex": to_hex(c[i]), "rgb": [round(float(v), 4) for v in c[i]], "fraction": round(float(frac[i]), 4)}
            for i in order if frac[i] > 0]


def flatness(img, mask, k=8, tol=0.04):
    """Share of foreground pixels within `tol` of one of k palette colours. ~1 = flat-shaded art,
    pixel art, blueprints; low = photo / painted / textured."""
    cols = img[..., :3][mask]
    if len(cols) == 0:
        return 0.0
    c, lab = kmeans(cols, k)
    d = np.linalg.norm(cols - c[lab], axis=1)
    return round(float((d < tol).mean()), 3)


# --------------------------------------------------------------------------- regions
def _components(binary):
    """Connected components (4-neighbour). Returns label image (-1 background) and count."""
    h, w = binary.shape
    lab = -np.ones((h, w), np.int32)
    n = 0
    ys, xs = np.nonzero(binary)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0] >= 0:
            continue
        q = deque([(y0, x0)])
        lab[y0, x0] = n
        while q:
            y, x = q.popleft()
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and binary[ny, nx] and lab[ny, nx] < 0:
                    lab[ny, nx] = n
                    q.append((ny, nx))
        n += 1
    return lab, n


def segments(img, mask, k=8, min_frac=0.002, max_side=400):
    """Colour regions: k-means palette, then connected components per colour.

    Returns [{id, hex, bbox_px (x0,y0,x1,y1 top-down), rel (bbox relative to the object's bbox,
    0..1, y down), area_frac, centroid_px}] sorted by area. Large images are analysed downscaled
    (coordinates are reported in ORIGINAL pixels).
    """
    h, w = mask.shape
    s = max(1.0, max(h, w) / max_side)
    sh, sw = int(round(h / s)), int(round(w / s))
    m2 = resample_mask(mask, sw, sh) if s > 1 else mask
    i2 = resample_img(img, sw, sh) if s > 1 else img
    cols = i2[..., :3][m2]
    c, lab = kmeans(cols, k)
    labimg = -np.ones(m2.shape, int)
    labimg[m2] = lab
    ob = bbox(mask)
    ow, oh = ob[2] - ob[0], ob[3] - ob[1]
    out = []
    total = m2.sum()
    for ci in range(len(c)):
        comp, n = _components(labimg == ci)
        for j in range(n):
            ys, xs = np.nonzero(comp == j)
            if len(ys) < max(4, min_frac * total):
                continue
            x0, y0 = int(xs.min() * s), int(ys.min() * s)
            x1, y1 = int(math.ceil((xs.max() + 1) * s)), int(math.ceil((ys.max() + 1) * s))
            out.append({"hex": to_hex(c[ci]), "rgb": [round(float(v), 4) for v in c[ci]],
                        "bbox_px": [x0, y0, x1, y1],
                        "rel": [round((x0 - ob[0]) / ow, 4), round((y0 - ob[1]) / oh, 4),
                                round((x1 - ob[0]) / ow, 4), round((y1 - ob[1]) / oh, 4)],
                        "area_frac": round(len(ys) / total, 4),
                        "centroid_px": [round(float(xs.mean() * s), 1), round(float(ys.mean() * s), 1)]})
    out.sort(key=lambda r: -r["area_frac"])
    for i, r in enumerate(out):
        r["id"] = i
    return out


# --------------------------------------------------------------------------- measuring (Mode 2)
def class_map(img, mask, classify, k=12):
    """Per-pixel semantic classes for flat-colour drawings (elevations, blueprints, concept art).

    classify(rgb) -> name, rgb in 0..1 sRGB. A k-means palette is named class by class, so
    anti-aliased edge pixels fall into the nearest colour. Returns ({name: bool mask}, info) where
    info = [{name, hex, fraction}]. Unlike segments(), regions of one class are NOT split into
    connected pieces - measure them with the run / morphology helpers below.
    """
    cols = img[..., :3][mask]
    c, lab = kmeans(cols, k)
    labimg = -np.ones(mask.shape, int)
    labimg[mask] = lab
    out, info = {}, []
    tot = max(1, int(mask.sum()))
    for i, rgb in enumerate(c):
        name = classify(tuple(float(v) for v in rgb))
        m = labimg == i
        out[name] = (out[name] | m) if name in out else m
        info.append({"name": name, "hex": to_hex(rgb), "fraction": round(float(m.sum() / tot), 4)})
    return out, info


def _window_sum(m, rx, ry=None):
    """Sum of m over (2rx+1) x (2ry+1) windows (zero padded) via an integral image."""
    ry = rx if ry is None else ry
    h, w = m.shape
    a = np.pad(m.astype(np.int32), ((ry + 1, ry), (rx + 1, rx)))
    ii = a.cumsum(0).cumsum(1)
    return (ii[2 * ry + 1:2 * ry + 1 + h, 2 * rx + 1:2 * rx + 1 + w] - ii[0:h, 2 * rx + 1:2 * rx + 1 + w]
            - ii[2 * ry + 1:2 * ry + 1 + h, 0:w] + ii[0:h, 0:w])


def erode(m, r):
    """Binary erosion with a (2r+1)^2 square."""
    return _window_sum(m, r) == (2 * r + 1) ** 2 if r > 0 else m.copy()


def dilate(m, r):
    """Binary dilation with a (2r+1)^2 square."""
    return _window_sum(m, r) > 0 if r > 0 else m.copy()


def opening(m, r):
    """Removes strokes thinner than 2r+1 px and keeps solid blobs (doors, panels)."""
    return dilate(erode(m, r), r)


def runs(flags, min_len=1):
    """[(start, end)] runs of True in a 1-D boolean array (end exclusive)."""
    f = np.concatenate(([0], np.asarray(flags).astype(np.int8), [0]))
    d = np.diff(f)
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a >= min_len]


def longest_runs(binary, axis=0):
    """Longest run of True per column (axis=0) or per row (axis=1): [(length, start, end)]."""
    b = binary if axis == 0 else binary.T
    out = []
    for j in range(b.shape[1]):
        r = runs(b[:, j])
        if not r:
            out.append((0, 0, 0))
            continue
        s, e = max(r, key=lambda t: t[1] - t[0])
        out.append((e - s, s, e))
    return out


def straight_members(binary, min_len_px, axis=0, max_width_px=None):
    """Straight vertical (axis=0) or horizontal (axis=1) strokes - posts, rails, frame bars.

    Adjacent columns (rows) whose longest run is >= min_len_px are grouped into one member.
    Returns [{across: (lo, hi) px, along: (start, end) px, width_px, length_px}] where `across` is
    the column (row) range and `along` the median run extent.
    """
    lr = longest_runs(binary, axis)
    ok = np.array([l >= min_len_px for l, _, _ in lr])
    out = []
    for lo, hi in runs(ok):
        if max_width_px and hi - lo > max_width_px:
            continue
        st = int(np.median([lr[j][1] for j in range(lo, hi)]))
        en = int(np.median([lr[j][2] for j in range(lo, hi)]))
        out.append({"across": (lo, hi), "along": (st, en), "width_px": hi - lo, "length_px": en - st})
    return out


def corner_radius(mask, corner="bottom-left", max_r=None):
    """Radius (px) of a rounded silhouette corner (hard-surface bodies, panels, screens): least-
    squares fit of the outline's per-row inset near that corner to a circular arc. Returns
    (radius_px, rms_px); radius ~0 = sharp corner."""
    b = bbox(mask)
    m = crop(mask, b)
    if corner.startswith("bottom"):
        m = m[::-1]
    h, w = m.shape
    max_r = max_r or max(2, min(h, w) // 3)
    e = []
    for row in m[:max_r]:
        xs = np.nonzero(row)[0]
        if not len(xs):
            break
        e.append(xs.min() if corner.endswith("left") else w - 1 - xs.max())
    e = np.array(e, float)
    d = np.arange(len(e)) + 0.5
    best = (0.0, float(np.sqrt((e ** 2).mean())) if len(e) else 0.0)
    for r in np.arange(1.0, max_r + 0.01, 0.25):
        model = np.where(d < r, r - np.sqrt(np.clip(r * r - (r - d) ** 2, 0, None)), 0.0)
        rms = float(np.sqrt(((e - model) ** 2).mean()))
        if rms < best[1]:
            best = (float(r), rms)
    return round(best[0], 2), round(best[1], 3)


def blobs(binary, min_px=20):
    """Connected regions of one class (windows, panels, decals): [{bbox_px (x0, y0, x1, y1;
    end exclusive, top-down), area_px, centroid_px}] sorted by area."""
    lab, n = _components(binary)
    out = []
    for j in range(n):
        ys, xs = np.nonzero(lab == j)
        if len(xs) < min_px:
            continue
        out.append({"bbox_px": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                    "area_px": int(len(xs)), "centroid_px": [float(xs.mean()), float(ys.mean())]})
    out.sort(key=lambda b: -b["area_px"])
    return out


def line_segments(binary, min_px=20, min_elong=3.0):
    """Thin straight strokes of any angle (braces, rafters) as segments via principal axes.

    Returns [{p0, p1 (x, y px, top-down), length_px, width_px, angle_deg (0 = horizontal, +ve
    rising to the right in world terms)}] for components that are elongated enough.
    """
    lab, n = _components(binary)
    out = []
    for j in range(n):
        ys, xs = np.nonzero(lab == j)
        if len(xs) < min_px:
            continue
        pts = np.stack([xs, ys], 1).astype(float)
        c = pts.mean(0)
        u, s_, vt = np.linalg.svd(pts - c, full_matrices=False)
        d = vt[0]
        t = (pts - c) @ d
        perp = (pts - c) @ vt[1]
        L, wid = float(t.max() - t.min()), float(perp.std() * math.sqrt(12))
        if wid <= 0 or L / max(wid, 1e-6) < min_elong:
            continue
        p0, p1 = c + d * t.min(), c + d * t.max()
        if p0[0] > p1[0]:
            p0, p1 = p1, p0
        ang = math.degrees(math.atan2(-(p1[1] - p0[1]), p1[0] - p0[0]))
        out.append({"p0": [float(p0[0]), float(p0[1])], "p1": [float(p1[0]), float(p1[1])],
                    "length_px": round(L, 1), "width_px": round(wid, 2), "angle_deg": round(ang, 2)})
    return out


def row_profile(mask, samples=None):
    """Per-row extent of the silhouette (top-down): [(y, x_left, x_right)] for rows with pixels.
    Feed widths to mesh.lathe for turned objects; samples=N picks N evenly spaced rows."""
    ys = np.nonzero(mask.any(axis=1))[0]
    if samples and len(ys) > samples:
        ys = ys[np.linspace(0, len(ys) - 1, samples).round().astype(int)]
    out = []
    for y in ys:
        xs = np.nonzero(mask[y])[0]
        out.append((int(y), int(xs.min()), int(xs.max()) + 1))
    return out


def symmetry(mask):
    """Left-right mirror IoU of the silhouette about its own bbox centre (1.0 = perfectly symmetric)."""
    b = bbox(mask)
    if b is None:
        return 0.0
    m = crop(mask, b)
    f = m[:, ::-1]
    return round(float((m & f).sum() / max(1, (m | f).sum())), 3)


def pixel_grid(img, mask, max_cell=64, tol=0.02):
    """Detect upscaled pixel art: the largest cell size s such that every s x s block (aligned to
    the object's bbox) is a single colour. Returns {cell, cols, rows} or None."""
    b = bbox(mask)
    if b is None:
        return None
    x0, y0, x1, y1 = b
    rgb = img[..., :3]
    for s in range(min(max_cell, (x1 - x0), (y1 - y0)), 1, -1):
        cols, rows = int(round((x1 - x0) / s)), int(round((y1 - y0) / s))
        if cols < 2 or rows < 2 or abs(cols * s - (x1 - x0)) > 1 or abs(rows * s - (y1 - y0)) > 1:
            continue
        blk = rgb[y0:y0 + rows * s, x0:x0 + cols * s].reshape(rows, s, cols, s, 3)
        spread = blk.max(axis=(1, 3)) - blk.min(axis=(1, 3))
        if float(spread.max()) <= tol:
            return {"cell": s, "cols": cols, "rows": rows, "origin": [x0, y0]}
    return None


def sample_grid(img, mask, cols, rows, box=None):
    """Downsample the object's bbox to a cols x rows grid: (colours (rows, cols, 3), filled (rows, cols)).
    Row 0 = top. Uses the cell centre (exact for pixel art, majority-like for drawings)."""
    box = box or bbox(mask)
    x0, y0, x1, y1 = box
    xs = (x0 + (np.arange(cols) + 0.5) * (x1 - x0) / cols).astype(int)
    ys = (y0 + (np.arange(rows) + 0.5) * (y1 - y0) / rows).astype(int)
    xs, ys = np.clip(xs, 0, mask.shape[1] - 1), np.clip(ys, 0, mask.shape[0] - 1)
    return img[ys][:, xs, :3], mask[ys][:, xs]


# --------------------------------------------------------------------------- contours
def contours(mask, simplify_px=1.5):
    """Outer + hole outlines of a mask via marching squares, simplified (Douglas-Peucker).
    Returns list of loops [(x, y), ...] in pixel coordinates (top-down), outer loops first."""
    m = np.pad(mask.astype(np.uint8), 1)
    # crack following: directed pixel-boundary edges, consistently clockwise (top-down coords)
    edges = []
    right = (m[:, :-1] == 1) & (m[:, 1:] == 0)   # filled at (y,x), empty at (y,x+1): edge x+1 vertical
    left = (m[:, :-1] == 0) & (m[:, 1:] == 1)
    down = (m[:-1, :] == 1) & (m[1:, :] == 0)
    up = (m[:-1, :] == 0) & (m[1:, :] == 1)
    for y, x in zip(*np.nonzero(right)):
        edges.append(((x + 1, y), (x + 1, y + 1)))
    for y, x in zip(*np.nonzero(left)):
        edges.append(((x + 1, y + 1), (x + 1, y)))
    for y, x in zip(*np.nonzero(down)):
        edges.append(((x + 1, y + 1), (x, y + 1)))
    for y, x in zip(*np.nonzero(up)):
        edges.append(((x, y + 1), (x + 1, y + 1)))
    nxt_map = {}
    for a, b in edges:
        nxt_map.setdefault(a, []).append(b)
    loops = []
    used = set()
    for a, b in edges:
        if (a, b) in used:
            continue
        loop = [a]
        cur, nx = a, b
        while True:
            used.add((cur, nx))
            loop.append(nx)
            cands = [c for c in nxt_map.get(nx, []) if (nx, c) not in used]
            if not cands:
                break
            cur, nx = nx, cands[0]
            if nx == loop[0]:
                used.add((cur, nx))
                break
        if len(loop) > 3:
            pts = [(px - 1, py - 1) for px, py in loop]  # undo padding
            loops.append(_dp(pts, simplify_px))
    loops.sort(key=lambda L: -abs(_area(L)))
    return loops


def _area(pts):
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


def _dp(pts, eps):
    if len(pts) < 4:
        return pts
    P = np.array(pts, float)

    def rec(i, j):
        a, b = P[i], P[j]
        if j <= i + 1:
            return [i]
        ab = b - a
        L = np.hypot(*ab) or 1e-9
        d = np.abs(np.cross(ab, P[i + 1:j] - a)) / L
        k = int(np.argmax(d))
        if d[k] > eps:
            return rec(i, i + 1 + k) + rec(i + 1 + k, j)
        return [i]

    idx = rec(0, len(P) - 1) + [len(P) - 1]
    out = [tuple(P[i]) for i in idx]
    if out[0] == out[-1]:
        out.pop()
    return out


# --------------------------------------------------------------------------- similarity
def normalized(mask, height=256):
    """Crop to bbox and scale to a fixed height (aspect kept) -> comparable silhouettes."""
    b = bbox(mask)
    m = crop(mask, b)
    h, w = m.shape
    nw = max(1, int(round(w * height / h)))
    return resample_mask(m, nw, height)


def _scaled(mask, factor):
    m = crop(mask, bbox(mask))
    h, w = m.shape
    return resample_mask(m, max(1, int(round(w * factor))), max(1, int(round(h * factor))))


def silhouette_iou(a, b, height=256, metric=None):
    """Shape similarity of two silhouettes, invariant to position and scale (both normalised to the
    same height, centred). Also returns aspect ratios so proportion errors are visible.

    metric=(metres_per_px_a, metres_per_px_b): compare at TRUE scale instead - both resampled to
    the same metres per pixel and aligned bottom-centre. Use it when the real size is known
    (Mode 2 with a scale anchor): a wrong overall size, or a part one view lacks (e.g. a chimney
    missing from one elevation), then shows up where it is instead of rescaling everything.
    """
    if metric:
        hb = bbox(b)
        target = (hb[3] - hb[1]) * metric[1] / height
        na, nb = _scaled(a, metric[0] / target), _scaled(b, metric[1] / target)
        Hc = max(na.shape[0], nb.shape[0])
        na = np.pad(na, ((Hc - na.shape[0], 0), (0, 0)))
        nb = np.pad(nb, ((Hc - nb.shape[0], 0), (0, 0)))
    else:
        na, nb = normalized(a, height), normalized(b, height)
    W = max(na.shape[1], nb.shape[1])

    def pad(m):
        p = (W - m.shape[1]) // 2
        return np.pad(m, ((0, 0), (p, W - m.shape[1] - p)))
    pa, pb = pad(na), pad(nb)
    inter = (pa & pb).sum()
    union = (pa | pb).sum()
    ba, bb = bbox(a), bbox(b)
    asp = lambda bx: (bx[2] - bx[0]) / max(1, (bx[3] - bx[1]))  # noqa: E731
    return {"iou": round(float(inter / max(1, union)), 4),
            "precision": round(float(inter / max(1, pa.sum())), 4),   # model pixels that match the reference
            "recall": round(float(inter / max(1, pb.sum())), 4),      # reference pixels covered by the model
            "aspect_model": round(asp(ba), 3), "aspect_ref": round(asp(bb), 3),
            "_pa": pa, "_pb": pb}


def overlay(pa, pb):
    """Diff image of two normalised silhouettes: grey=both, red=model only, blue=reference only."""
    h, w = pa.shape
    out = np.full((h, w, 3), 0.08, np.float32)
    out[pa & pb] = (0.75, 0.75, 0.75)
    out[pa & ~pb] = (0.9, 0.2, 0.2)
    out[~pa & pb] = (0.2, 0.4, 0.95)
    return out


# --------------------------------------------------------------------------- summary
def texture_energy(img, mask):
    """Fine-detail energy inside the object: median |Laplacian| of luminance (outline excluded).
    ~0 for flat AND smoothly shaded artwork (cartoons, renders, gradients - linear ramps have no
    Laplacian); photos and textured paintings carry noise/texture (sensor noise alone ~0.02+).
    Separates a shaded illustration from a photo, which k-means flatness cannot (T5: a cartoon
    creature with gradient shading scored flatness 0.57 and was labelled 'photo')."""
    g = img[..., :3] @ np.array([0.2126, 0.7152, 0.0722])
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    inner = erode(mask, 2)[1:-1, 1:-1]
    return round(float(np.median(lap[inner])), 4) if inner.any() else 0.0


def analyze(path, k=8, debug_png=None):
    """One-call analysis used by the mode selector and by Claude before modelling."""
    img = load(path)
    m = foreground_mask(img)
    b = bbox(m)
    if b is None:
        return {"path": path, "error": "no foreground found"}
    h, w = m.shape
    grid = pixel_grid(img, m)
    segs = segments(img, m, k=k)
    res = {
        "path": os.path.abspath(path), "size": [w, h], "bbox_px": list(b),
        "object_aspect_w_over_h": round((b[2] - b[0]) / (b[3] - b[1]), 4),
        "fill_of_frame": round(float(m.sum()) / (w * h), 4),
        "alpha": bool(img[..., 3].min() < 0.99),
        "symmetry_lr": symmetry(m), "flatness": flatness(img, m, k),
        "pixel_art": grid, "palette": palette(img, m, k), "segments": segs[:40],
        "texture_energy": texture_energy(img, m),
        "holes": max(0, len(contours(resample_mask(m, min(w, 200), min(h, 200)))) - 1),
    }
    res["style_hint"] = ("pixel-art/voxel" if grid else "flat-shaded/blueprint" if res["flatness"] > 0.9
                         else "illustration" if res["flatness"] > 0.6
                         else "illustration (smooth shading)" if res["texture_energy"] < 0.01
                         else "photo/textured painting")
    if debug_png:
        dbg = img[..., :3].copy() * 0.55 + 0.45 * m[..., None] * img[..., :3]
        for s in segs[:40]:
            x0, y0, x1, y1 = s["bbox_px"]
            col = np.array([1.0, 0.1, 0.6])
            dbg[y0:y1, max(0, x0):x0 + 2] = col
            dbg[y0:y1, max(0, x1 - 2):x1] = col
            dbg[y0:y0 + 2, x0:x1] = col
            dbg[max(0, y1 - 2):y1, x0:x1] = col
        save(dbg, debug_png)
        res["debug_png"] = os.path.abspath(debug_png)
    return res
