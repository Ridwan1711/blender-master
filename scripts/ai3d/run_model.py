#!/usr/bin/env python3
"""Run an installed local image-to-3D model safely (Mode 3). Standard library only.

    python scripts/ai3d/run_model.py triposr --image ref.png --out out/model.glb
            [--mc-res 256] [--threads N] [--timeout 1800]

Guards: compatibility re-checked (refuses 'none'), model must be installed, inference runs in
the model's own venv as a separate process at below-normal priority with a timeout, offline
(HF_HUB_OFFLINE=1), temp files cleaned. Reports wall time, peak RAM and CPU time.
Import the result into Blender with bkit.recon.import_mesh(path) and run the common QA pipeline.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import check  # noqa: E402
import procstats  # noqa: E402

ADAPTERS = {"triposr": "triposr_infer.py"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=list(ADAPTERS))
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mc-res", type=int, default=256)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=8192)
    ap.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args()
    verdict = check.check(a.model)["models"][a.model]
    if verdict["run_on"] == "none":
        print(json.dumps({"ok": False, "refused": True, "reasons": verdict["reasons"],
                          "advice": "use Mode 1 (procedural) or Mode 2 (reference-based)"}))
        return 3
    info = verdict["install_info"]
    if not info:
        print(json.dumps({"ok": False, "error": "not installed",
                          "advice": "python scripts/ai3d/install_model.py %s --yes (after user approval)" % a.model}))
        return 4
    home = info["home"]
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cmd = [info["python"], os.path.join(HERE, "adapters", ADAPTERS[a.model]), "--src", os.path.join(home, "src"),
           "--weights", os.path.join(home, "weights"), "--image", os.path.abspath(a.image), "--out", out,
           "--mc-res", str(a.mc_res), "--chunk", str(a.chunk), "--threads", str(a.threads),
           "--device", "cuda" if verdict["run_on"] == "gpu" else "cpu"]
    env = dict(os.environ, HF_HOME=os.path.join(home, "hf"), HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8")
    flags = 0x00004000 if sys.platform == "win32" else 0  # BELOW_NORMAL_PRIORITY_CLASS: keep desktop/Blender responsive
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, creationflags=flags)
    timed_out = False
    try:
        text, _ = proc.communicate(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        text, _ = proc.communicate()
        timed_out = True
    stats = procstats.collect(proc)
    text = text.decode("utf-8", "replace")
    res = None
    for line in text.splitlines():
        if line.startswith("@@AI3D@@"):
            res = json.loads(line[8:])
    log_path = os.path.splitext(out)[0] + "_ai3d.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(" ".join(cmd) + "\n\n" + text)
    if res and res.get("process"):  # the adapter measured the real interpreter (venv python.exe is a launcher on Windows)
        stats = {k: v for k, v in res["process"].items()}
    report = dict(res or {"ok": False}, model=a.model, run_on=verdict["run_on"], wall_s=round(time.time() - t0, 1),
                  timed_out=timed_out, exit=proc.returncode, log=log_path, **stats)
    if not res:
        tail = [l for l in text.splitlines() if l.strip()][-8:]
        report["error_tail"] = tail
    with open(os.path.splitext(out)[0] + "_ai3d.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0 if res and res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
