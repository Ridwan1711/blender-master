"""bkit - tested helpers for driving Blender from Python (blender-master skill).

Import submodules explicitly:

    from bkit import scene, mesh, materials as mat, lighting, camera, render, inspect, validate
    from bkit import emit, warn, save

Every helper works through the data API where possible (no viewport/context needed),
so the same code runs headless (`blender -b`) and inside the GUI.
"""
from .runtime import emit, warn, save, args  # noqa: F401
from . import compat  # noqa: F401

__version__ = "1.0.0"
