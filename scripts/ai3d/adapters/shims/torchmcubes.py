"""Drop-in replacement for `torchmcubes.marching_cubes` (which needs a C++/CUDA build).

Backed by PyMCubes (pip wheel) or scikit-image. torchmcubes returns vertices ordered
(last axis, middle, first axis); TripoSR swizzles them back with [..., [2, 1, 0]], so we
return the same ordering. Face winding may differ - Blender recalculates normals on import.
"""
import numpy as np
import torch


def marching_cubes(vol, thresh):
    v = vol.detach().cpu().numpy().astype(np.float32)
    try:
        import mcubes
        verts, faces = mcubes.marching_cubes(v, float(thresh))
    except ImportError:
        from skimage.measure import marching_cubes as _mc
        verts, faces, _, _ = _mc(v, float(thresh))
    verts = np.ascontiguousarray(verts[:, [2, 1, 0]], dtype=np.float32)
    return torch.from_numpy(verts), torch.from_numpy(np.ascontiguousarray(faces, dtype=np.int64))
