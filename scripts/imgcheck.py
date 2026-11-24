"""Exposure / clipping / noise check of a rendered image. Usage: python bk.py imgcheck render.png"""
import sys

from bkit import emit
from bkit import inspect as I

paths = [p for p in sys.argv[1:] if not p.startswith("--")]
emit(images={p: I.image_stats(p) for p in paths})
