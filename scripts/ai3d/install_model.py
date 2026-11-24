#!/usr/bin/env python3
"""Install a local image-to-3D model into an ISOLATED venv (never into Blender's Python).

    python scripts/ai3d/install_model.py triposr            # dry run: what would be downloaded
    python scripts/ai3d/install_model.py triposr --yes      # install (gated by check.py)

Home: ~/.cache/blender-master/ai3d on every OS (Windows: %USERPROFILE%/.cache/...), override
with env BKIT_AI3D_HOME. (Not %LOCALAPPDATA%: packaged Windows apps virtualize AppData.) Remove a model by deleting its folder. Refuses models this machine
cannot run (check.py verdict 'none') - no repeated failing installs.
Downloads (TripoSR, CPU): PyTorch CPU wheel (download.pytorch.org), transformers/einops/
omegaconf/trimesh/PyMCubes/huggingface_hub (PyPI), TripoSR source (github.com/VAST-AI-Research/
TripoSR, MIT), weights stabilityai/TripoSR model.ckpt+config.yaml (Hugging Face, MIT) and the
facebook/dino-vitb16 config.json the model references.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check  # noqa: E402

SPEC = {
    "triposr": {
        "src_zip": "https://codeload.github.com/VAST-AI-Research/TripoSR/zip/refs/heads/main",
        "src_subdir": "tsr",
        "pip_cpu": [["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]],
        "pip_gpu": [["torch", "--index-url", "https://download.pytorch.org/whl/cu126"]],
        # imageio: imported unconditionally by tsr/utils.py. Not needed: torchmcubes (C++ build; shimmed
        # with PyMCubes), rembg (shimmed), xatlas/moderngl (only tsr/bake_texture.py, unused here).
        "pip": ["transformers>=4.40,<5", "einops", "omegaconf", "trimesh", "PyMCubes", "huggingface_hub",
                "safetensors", "pillow", "numpy", "imageio"],
        "import_check": "import sys; sys.path[:0]=[sys.argv[1], sys.argv[2]]; from tsr.system import TSR; print('tsr import ok')",
        "weights": [("stabilityai/TripoSR", "config.yaml"), ("stabilityai/TripoSR", "model.ckpt")],
        "extra_hf": [("facebook/dino-vitb16", "config.json")],
    }
}


def log(msg):
    print("[install %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def run(cmd, env=None):
    log("$ " + " ".join(cmd))
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        raise SystemExit("command failed (%d): %s" % (r.returncode, " ".join(cmd)))


def dir_size_mb(p):
    return round(sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(p) for f in fs) / 1024 ** 2, 1)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        print("adapters available for: %s" % ", ".join(SPEC))
        return 2
    if args[0] not in SPEC:
        with open(os.path.join(HERE, "models.json"), encoding="utf-8") as f:
            info = json.load(f).get("models", {}).get(args[0])
        if info:
            # in the registry (researched) but no install+run adapter in this skill
            v = check.check(args[0])["models"].get(args[0], {})
            print("%s (%s) is evaluated in models.json but has NO adapter in this skill - not installable "
                  "here.\n  licence: %s\n  this machine: run_on=%s%s\n  supported now: %s. To add one: an "
                  "install SPEC here + adapters/<model>_infer.py (see triposr)." % (
                      args[0], info.get("name"), info.get("license"), v.get("run_on", "?"),
                      ("; " + "; ".join(v.get("reasons") or [])) if v.get("reasons") else "", ", ".join(SPEC)))
        else:
            print("unknown model '%s'. Adapters available for: %s" % (args[0], ", ".join(SPEC)))
        return 2
    key = args[0]
    spec = SPEC[key]
    verdict = check.check(key)["models"][key]
    log("compatibility: run_on=%s; %s" % (verdict["run_on"], "; ".join(verdict["reasons"]) or "no issues"))
    if verdict["run_on"] == "none":
        log("REFUSED: this machine cannot run %s. Use Mode 1 or Mode 2 (references/image-to-3d.md)." % key)
        return 3
    home = os.path.join(check.AI3D_HOME, key)
    if "--yes" not in sys.argv:
        log("dry run. Would install into %s (venv + source + weights, ~%s GB). Re-run with --yes." % (
            home, json.load(open(os.path.join(HERE, "models.json")))["models"][key]["download_gb"]))
        return 0
    t0 = time.time()
    os.makedirs(home, exist_ok=True)
    venv = os.path.join(home, "venv")
    py = os.path.join(venv, "Scripts" if sys.platform == "win32" else "bin", "python.exe" if sys.platform == "win32" else "python")
    if not os.path.isfile(py):
        run([sys.executable, "-m", "venv", venv])
    env = dict(os.environ, HF_HOME=os.path.join(home, "hf"), PIP_DISABLE_PIP_VERSION_CHECK="1")
    run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], env)
    for extra in (spec["pip_gpu"] if verdict["run_on"] == "gpu" else spec["pip_cpu"]):
        run([py, "-m", "pip", "install", "-q"] + extra, env)
    run([py, "-m", "pip", "install", "-q"] + spec["pip"], env)
    # source (only the python package folder + licence are kept)
    src = os.path.join(home, "src")
    if not os.path.isdir(os.path.join(src, spec["src_subdir"])):
        log("downloading source " + spec["src_zip"])
        data = urllib.request.urlopen(spec["src_zip"], timeout=120).read()
        sha = hashlib.sha256(data).hexdigest()
        z = zipfile.ZipFile(io.BytesIO(data))
        root = z.namelist()[0].split("/")[0]
        os.makedirs(src, exist_ok=True)
        for n in z.namelist():
            rel = n[len(root) + 1:]
            if rel.startswith(spec["src_subdir"] + "/") or rel in ("LICENSE", "README.md"):
                dst = os.path.join(src, rel)
                if n.endswith("/"):
                    os.makedirs(dst, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(z.read(n))
        with open(os.path.join(src, "SOURCE.txt"), "w") as f:
            f.write("%s\nsha256 %s\n" % (spec["src_zip"], sha))
    # weights via huggingface_hub inside the venv (resumable, cached in <home>/hf)
    wdir = os.path.join(home, "weights")
    files = ",".join("%s|%s" % rf for rf in spec["weights"])
    extra = ",".join("%s|%s" % rf for rf in spec["extra_hf"])
    code = ("import sys\nfrom huggingface_hub import hf_hub_download\n"
            "for rf in sys.argv[2].split(','):\n r,f=rf.split('|'); print(hf_hub_download(r,f,local_dir=sys.argv[1]))\n"
            "for rf in [x for x in sys.argv[3].split(',') if x]:\n r,f=rf.split('|'); print(hf_hub_download(r,f))\n")
    run([py, "-c", code, wdir, files, extra], env)
    if spec.get("import_check"):
        run([py, "-c", spec["import_check"], os.path.join(HERE, "adapters", "shims"), src], env)
    ver = subprocess.run([py, "-c", "import torch,transformers;print(torch.__version__,transformers.__version__)"],
                         capture_output=True, text=True, env=env).stdout.strip()
    info = {"model": key, "run_on": verdict["run_on"], "python": py, "home": home,
            "versions": ver, "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t0), "size_mb": dir_size_mb(home)}
    with open(os.path.join(home, "INSTALLED.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    log("done: %s" % json.dumps(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
