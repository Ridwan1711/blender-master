"""QA validation. Usage:
python bk.py validate scene.blend [--tier mobile|game|hero|film] [--purpose preview|final]
                                  [--subjects A,B] [--no-health] [--no-intersections] [--strict]
--strict makes warnings fail the run (exit 1) as well as errors.
"""
import argparse
import sys

import bpy
from bkit import emit
from bkit import validate as V

ap = argparse.ArgumentParser()
ap.add_argument("--tier", default="hero", choices=list(V.TIERS))
ap.add_argument("--purpose", default="final", choices=["preview", "final"])
ap.add_argument("--subjects", help="comma-separated object names that must be in frame")
ap.add_argument("--no-health", action="store_true")
ap.add_argument("--no-intersections", action="store_true")
ap.add_argument("--strict", action="store_true")
a = ap.parse_args(sys.argv[1:])

subj = None
if a.subjects:
    subj = [bpy.data.objects[n] for n in a.subjects.split(",")]
res = V.run(tier=a.tier, health=not a.no_health, intersect=not a.no_intersections,
            purpose=a.purpose, subjects=subj)
emit(validation=res)
if not res["passed"] or (a.strict and res["counts"]["warn"]):
    raise SystemExit(1)
