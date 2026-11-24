#!/usr/bin/env python3
"""Can this machine run each local image-to-3D model? Standard library only.

    python scripts/ai3d/check.py [--json] [--model triposr]

For every model in models.json: GPU verdict (VRAM, compute capability, driver CUDA ceiling,
PyTorch wheel support for the architecture), CPU verdict (supported + RAM), install status,
and the recommended execution (gpu | cpu | none) with reasons. Run this BEFORE installing or
running anything - never retry incompatible installs.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hwprobe  # noqa: E402

# ~/.cache on every OS. NOT %LOCALAPPDATA%: packaged (MSIX) Windows apps - e.g. the Claude desktop
# app - silently redirect AppData writes to a private per-app folder, so a model installed from one
# app would be invisible to a terminal or another agent. Override with env BKIT_AI3D_HOME.
AI3D_HOME = os.environ.get("BKIT_AI3D_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "blender-master", "ai3d")


def _v(s):
    try:
        return tuple(int(x) for x in str(s).lstrip("<").split("."))
    except ValueError:
        return (0,)


def installed(key):
    marker = os.path.join(AI3D_HOME, key, "INSTALLED.json")
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8") as f:
            return json.load(f)
    return None


def evaluate(model, hw):
    reasons, gpu_ok = [], False
    nv = [g for g in hw["gpus"] if g.get("vendor") == "NVIDIA"]
    if not nv:
        reasons.append("no NVIDIA GPU detected (these models need CUDA; Apple/AMD paths are unsupported or experimental)")
    for g in nv:
        r = []
        if g.get("vram_gb") is not None and g["vram_gb"] < model["gpu_min_vram_gb"]:
            r.append("VRAM %.1f GB < %s GB needed" % (g["vram_gb"], model["gpu_min_vram_gb"]))
        cc = g.get("compute_capability")
        if cc is not None and cc < model.get("gpu_min_cc", 0):
            r.append("compute capability %.1f < %.1f" % (cc, model["gpu_min_cc"]))
        if cc is not None and cc < 7.5:
            r.append("PyTorch CUDA 12.8+/13 wheels dropped cc < 7.5 (%s); only CUDA <=12.6 wheels remain" % g.get("arch"))
        mc = g.get("max_cuda")
        if mc and _v(mc) < _v(model.get("min_cuda", "11.8")):
            r.append("driver %s supports CUDA %s < %s required (driver update needed)" % (g.get("driver"), mc, model["min_cuda"]))
        if g.get("vram_gb") is None:
            r.append("VRAM unknown")
        if not [x for x in r if not x.startswith("PyTorch")] and model["gpu_min_vram_gb"] <= (g.get("vram_gb") or 0):
            gpu_ok = True
        reasons += ["GPU %s: %s" % (g["name"], x) for x in r]
    ram = hw["ram_gb"]["total"] or 0
    cpu_ok = bool(model.get("cpu_inference")) and ram >= model.get("cpu_min_ram_gb", 8)
    if not model.get("cpu_inference"):
        reasons.append("no CPU inference path")
    elif not cpu_ok:
        reasons.append("RAM %.0f GB < %s GB for CPU inference" % (ram, model.get("cpu_min_ram_gb")))
    disk_ok = hw["disk_free_gb"] >= model.get("download_gb", 0) * 1.5
    if not disk_ok:
        reasons.append("free disk %.0f GB < %.0f GB needed" % (hw["disk_free_gb"], model["download_gb"] * 1.5))
    run = "gpu" if gpu_ok else "cpu" if cpu_ok else "none"
    if not disk_ok:
        run = "none"
    inst = installed(model["_key"])
    return {"model": model["name"], "run_on": run, "installed": bool(inst), "install_info": inst,
            "supported_by_skill": model.get("supported_by_skill", False), "license": model["license"],
            "reasons": reasons}


def check(only=None):
    with open(os.path.join(HERE, "models.json"), encoding="utf-8") as f:
        reg = json.load(f)["models"]
    hw = hwprobe.probe(AI3D_HOME if os.path.exists(AI3D_HOME) else None)
    out = {}
    for key, m in reg.items():
        if only and key != only:
            continue
        m = dict(m, _key=key)
        out[key] = evaluate(m, hw)
    usable = [k for k, v in out.items() if v["run_on"] != "none" and v["supported_by_skill"]]
    return {"hardware": hw, "models": out, "usable_with_skill": usable,
            "recommendation": (("Mode 3 possible with: %s" % ", ".join(
                "%s (%s%s)" % (k, out[k]["run_on"], ", installed" if out[k]["installed"] else ", not installed")
                for k in usable)) if usable else
                "No local AI model can run here - use Mode 1 (procedural) or Mode 2 (reference-based).")}


def main():
    only = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else None
    res = check(only)
    if "--json" in sys.argv:
        print(json.dumps(res, indent=1))
        return 0
    for k, v in res["models"].items():
        print("%-15s run_on=%-4s installed=%-5s adapter=%-5s %s" % (k, v["run_on"], v["installed"], v["supported_by_skill"], v["license"][:60]))
        for r in v["reasons"]:
            print("                 - " + r)
    print("=>", res["recommendation"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
