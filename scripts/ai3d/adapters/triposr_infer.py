"""TripoSR inference - runs INSIDE the model's isolated venv (started by run_model.py).

Preprocessing follows TripoSR's recipe: foreground on a 50% grey square, object filling
`fg_ratio` of the frame. Background removal: the image's alpha if present, otherwise a flood
fill from the borders over pixels close to the median border colour (works for studio /
plain backgrounds; for busy photos supply an RGBA cut-out).
Prints one line `@@AI3D@@ {json}` with timings and mesh stats.
"""
import argparse
import inspect
import json
import os
import sys
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))


def flood_background(rgb, tol):
    import numpy as np
    h, w, _ = rgb.shape
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    near = np.linalg.norm(rgb - bg, axis=2) < tol
    seen = np.zeros((h, w), bool)
    q = deque((y, x) for y in range(h) for x in (0, w - 1) if near[y, x])
    q.extend((y, x) for x in range(w) for y in (0, h - 1) if near[y, x])
    for y, x in q:
        seen[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and near[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return ~seen  # foreground mask


def preprocess(path, fg_ratio=0.85, size=512, tol=0.12):
    import numpy as np
    from PIL import Image
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
    rgb, alpha = im[..., :3], im[..., 3]
    if alpha.min() < 0.99:
        mask = alpha > 0.5
        how = "alpha"
    else:
        mask = flood_background(rgb, tol)
        how = "border flood fill (tol %.2f)" % tol
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        raise SystemExit("no foreground found in %s" % path)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = rgb[y0:y1, x0:x1]
    m = mask[y0:y1, x0:x1, None].astype(np.float32)
    fg = crop * m + 0.5 * (1 - m)
    side = int(max(y1 - y0, x1 - x0) / fg_ratio)
    canvas = np.full((side, side, 3), 0.5, np.float32)
    oy, ox = (side - (y1 - y0)) // 2, (side - (x1 - x0)) // 2
    canvas[oy:oy + (y1 - y0), ox:ox + (x1 - x0)] = fg
    img = Image.fromarray((canvas * 255).astype("uint8")).resize((size, size), Image.LANCZOS)
    return img, {"mask_source": how, "foreground_px": int(mask.sum()), "crop": [int(x0), int(y0), int(x1), int(y1)]}


def self_stats():
    """Peak RAM / CPU time of THIS interpreter (on Windows a venv python.exe is only a launcher,
    so the parent cannot measure the real process)."""
    out = {"cpu_seconds": round(time.process_time(), 1)}
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] +                            [(n, ctypes.c_size_t) for n in ("a", "b", "c", "d", "e", "f")]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE          # 64-bit pseudo-handle: without
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,   # explicit types ctypes truncates it
                                                   ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            out["peak_ram_mb"] = round(pmc.PeakWorkingSetSize / 1024 ** 2, 1)
        else:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out["peak_ram_mb"] = round(r / (1024 ** 2 if sys.platform == "darwin" else 1024), 1)
    except Exception as e:  # noqa: BLE001
        out["stats_error"] = str(e)[:80]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True, help=".glb or .obj")
    ap.add_argument("--mc-res", type=int, default=256)
    ap.add_argument("--chunk", type=int, default=8192)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--fg-ratio", type=float, default=0.85)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(HERE, "shims"))
    sys.path.insert(0, a.src)
    t = {}
    t0 = time.time()
    import torch
    if a.threads:
        torch.set_num_threads(a.threads)
    from tsr.system import TSR
    model = TSR.from_pretrained(a.weights, config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(a.chunk)
    model.to(a.device)
    t["load_s"] = round(time.time() - t0, 1)
    t1 = time.time()
    img, pre = preprocess(a.image, a.fg_ratio)
    prep_path = os.path.splitext(a.out)[0] + "_input.png"
    img.save(prep_path)
    with torch.no_grad():
        codes = model([img], device=a.device)
    t["encode_s"] = round(time.time() - t1, 1)
    t2 = time.time()
    params = inspect.signature(model.extract_mesh).parameters
    with torch.no_grad():
        if "has_vertex_color" in params:
            meshes = model.extract_mesh(codes, True, resolution=a.mc_res)
        else:
            meshes = model.extract_mesh(codes, resolution=a.mc_res)
    mesh = meshes[0]
    t["mesh_s"] = round(time.time() - t2, 1)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    mesh.export(a.out)
    rep = {"ok": True, "out": os.path.abspath(a.out), "preprocessed": prep_path, "pre": pre,
           "verts": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
           "threads": torch.get_num_threads(), "torch": torch.__version__, "device": a.device,
           "mc_res": a.mc_res, "timings": t, "total_s": round(time.time() - t0, 1), "process": self_stats()}
    print("@@AI3D@@ " + json.dumps(rep), flush=True)


if __name__ == "__main__":
    main()
