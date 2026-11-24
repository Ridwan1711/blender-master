"""Stub for `rembg` (an optional ~200 MB dependency of TripoSR's demo utilities).

Background removal is done by the bkit adapter (border flood-fill or the image's alpha).
Install the real rembg into the model venv if you need it; this stub is only used when absent.
"""


def new_session(*args, **kwargs):
    return None


def remove(*args, **kwargs):
    raise RuntimeError("rembg is not installed; the bkit adapter removes backgrounds itself "
                       "(or pass an RGBA PNG with a transparent background).")
