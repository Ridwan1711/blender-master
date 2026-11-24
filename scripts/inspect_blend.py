"""Scene report. Usage: python bk.py inspect scene.blend [--health] [--intersections] [--no-objects] [--out report.json]"""
import argparse
import json
import sys

from bkit import emit
from bkit import inspect as I

ap = argparse.ArgumentParser()
ap.add_argument("--health", action="store_true", help="mesh health per renderable mesh")
ap.add_argument("--intersections", action="store_true")
ap.add_argument("--no-objects", action="store_true")
ap.add_argument("--max-objects", type=int, default=150)
ap.add_argument("--out", help="also write the full report JSON here")
a = ap.parse_args(sys.argv[1:])

rep = I.scene_report(objects=not a.no_objects, max_objects=a.max_objects)
if a.health:
    rep["health"] = {o.name: I.mesh_health(o) for o in I.renderable() if o.type == "MESH"}
if a.intersections:
    rep["intersections"] = I.intersections()
if a.out:
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1, default=str)
    rep = {"written": a.out, "tris_total": rep["tris_total"], "counts": rep["counts"]}
emit(report=rep)
