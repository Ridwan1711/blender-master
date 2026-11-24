#!/usr/bin/env python3
"""Hardware probe for local AI 3D reconstruction (Mode 3). Standard library only.

    python scripts/ai3d/hwprobe.py            # human summary + JSON
    python scripts/ai3d/hwprobe.py --json     # JSON only

Reports GPU(s) with vendor, architecture, compute capability, VRAM, driver and the highest
CUDA version that driver can run; CPU threads, RAM, free disk; Python. Never assumes: every
field says where it came from, unknown values stay null.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys

# NVIDIA consumer/pro GPU name -> (architecture, compute capability). Longest match wins.
NV_ARCH = [
    (r"RTX PRO \d+ Blackwell|RTX 50\d0|B200|B100|GB200", ("Blackwell", 12.0)),
    (r"RTX 40\d0|RTX [456]000 Ada|L40|L4\b", ("Ada Lovelace", 8.9)),
    (r"H100|H200|GH200", ("Hopper", 9.0)),
    (r"RTX 30\d0|RTX A\d000|A100|A10\b|A40|A30", ("Ampere", 8.6)),
    (r"RTX 20\d0|GTX 16\d0|TITAN RTX|Quadro RTX|T4\b|T1000|T600", ("Turing", 7.5)),
    (r"TITAN V|V100", ("Volta", 7.0)),
    (r"GTX 10\d0|TITAN Xp|TITAN X \(Pascal\)|P100|P40|P4\b|MX[1-3]\d0|Quadro P", ("Pascal", 6.1)),
    (r"GTX 9\d0|GTX 750|GTX 745|GTX TITAN X|Quadro M|M\d{3,4}M|GTX 9\d0M", ("Maxwell", 5.0)),
    (r"GTX 7\d0|GTX 6\d0|GT 7\d0|K\d{2,4}", ("Kepler", 3.5)),
]
# Highest CUDA runtime a given NVIDIA driver supports (Windows/Linux, conservative).
DRIVER_CUDA = [(580, "13.0"), (570, "12.8"), (560, "12.6"), (550, "12.4"), (530, "12.1"), (525, "12.0"),
               (520, "11.8"), (510, "11.6"), (470, "11.4"), (452, "11.0"), (418, "10.1"), (410, "10.0"),
               (396, "9.2"), (384, "9.0"), (369, "8.0"), (0, "<8.0")]


def _run(cmd, timeout=20):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def nv_arch(name):
    for pat, val in NV_ARCH:
        if re.search(pat, name, re.I):
            return val
    return (None, None)


def cuda_for_driver(ver):
    try:
        major = int(float(str(ver).split(".")[0]))
    except ValueError:
        return None
    for d, c in DRIVER_CUDA:
        if major >= d:
            return c
    return None


def win_driver_to_nvidia(dv):
    """Windows driver version 21.21.13.7654 -> NVIDIA 376.54 (last 5 digits)."""
    digits = dv.replace(".", "")[-5:]
    return "%s.%s" % (digits[:3], digits[3:]) if len(digits) == 5 else None


def gpus():
    found = []
    smi = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if os.path.exists(r"C:\Windows\System32\nvidia-smi.exe") else None)
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"])
        for line in out.strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 3:
                arch, cc = nv_arch(p[0])
                try:
                    cc = float(p[3]) if len(p) > 3 and p[3] not in ("", "[N/A]") else cc
                except ValueError:
                    pass
                found.append({"vendor": "NVIDIA", "name": p[0], "vram_gb": round(float(p[1]) / 1024, 2),
                              "driver": p[2], "arch": arch, "compute_capability": cc, "source": "nvidia-smi"})
        if found:
            return found
    if sys.platform == "win32":
        ps = ("Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*'"
              " -ErrorAction SilentlyContinue | Where-Object { $_.DriverDesc } | ForEach-Object { $_.DriverDesc + '|' +"
              " $_.'HardwareInformation.qwMemorySize' + '|' + $_.DriverVersion + '|' + $_.DriverDate }")
        for line in _run(["powershell", "-NoProfile", "-Command", ps]).splitlines():
            p = line.strip().split("|")
            if len(p) < 3 or not p[0]:
                continue
            name = p[0]
            vendor = "NVIDIA" if "NVIDIA" in name.upper() else "AMD" if re.search("AMD|RADEON", name, re.I) else \
                "Intel" if "INTEL" in name.upper() else "other"
            try:
                vram = round(float(p[1]) / 1024 ** 3, 2) if p[1] else None
            except ValueError:
                vram = None
            drv = win_driver_to_nvidia(p[2]) if vendor == "NVIDIA" else p[2]
            arch, cc = nv_arch(name) if vendor == "NVIDIA" else (None, None)
            found.append({"vendor": vendor, "name": name, "vram_gb": vram, "driver": drv,
                          "driver_date": p[3] if len(p) > 3 else None, "arch": arch,
                          "compute_capability": cc, "source": "windows-registry"})
    elif sys.platform == "darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        for m in re.finditer(r"Chipset Model: (.+)", out):
            found.append({"vendor": "Apple" if "Apple" in m.group(1) else "other", "name": m.group(1).strip(),
                          "vram_gb": None, "driver": None, "arch": "Metal", "compute_capability": None,
                          "source": "system_profiler", "note": "Apple Silicon shares system RAM (unified memory)"})
    else:
        for line in _run(["lspci"]).splitlines():
            if re.search("VGA|3D controller", line):
                name = line.split(":", 2)[-1].strip()
                vendor = "NVIDIA" if "NVIDIA" in name.upper() else "AMD" if "AMD" in name.upper() else "other"
                found.append({"vendor": vendor, "name": name, "vram_gb": None, "driver": None,
                              "arch": None, "compute_capability": None, "source": "lspci"})
    for g in found:
        if g["vendor"] == "NVIDIA" and g.get("driver"):
            g["max_cuda"] = cuda_for_driver(g["driver"])
    return found


def ram_gb():
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return round(ms.ullTotalPhys / 1024 ** 3, 1), round(ms.ullAvailPhys / 1024 ** 3, 1)
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        avail = os.sysconf("SC_AVPHYS_PAGES") if hasattr(os, "sysconf") else None
        return round(pages * size / 1024 ** 3, 1), round(avail * size / 1024 ** 3, 1) if avail else None
    except (ValueError, OSError, AttributeError):
        out = _run(["sysctl", "-n", "hw.memsize"])
        return (round(int(out) / 1024 ** 3, 1), None) if out.strip() else (None, None)


def probe(target_dir=None):
    total, avail = ram_gb()
    target_dir = target_dir or os.path.expanduser("~")
    du = shutil.disk_usage(target_dir if os.path.exists(target_dir) else os.path.expanduser("~"))
    cpu_name = platform.processor()
    if sys.platform == "win32":
        cpu_name = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]).strip() or cpu_name
    return {
        "os": "%s %s" % (platform.system(), platform.release()), "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cpu": {"name": cpu_name, "threads": os.cpu_count()},
        "ram_gb": {"total": total, "available": avail},
        "disk_free_gb": round(du.free / 1024 ** 3, 1), "disk_checked": target_dir,
        "gpus": gpus(),
    }


def main():
    rep = probe()
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=1))
        return 0
    print("OS      %s (%s), Python %s" % (rep["os"], rep["machine"], rep["python"]))
    print("CPU     %s, %s threads" % (rep["cpu"]["name"], rep["cpu"]["threads"]))
    print("RAM     %s GB total, %s GB available" % (rep["ram_gb"]["total"], rep["ram_gb"]["available"]))
    print("Disk    %s GB free (%s)" % (rep["disk_free_gb"], rep["disk_checked"]))
    for g in rep["gpus"] or [{"name": "none detected"}]:
        print("GPU     %s | %s GB | driver %s | %s cc %s | max CUDA %s  [%s]" % (
            g.get("name"), g.get("vram_gb"), g.get("driver"), g.get("arch"), g.get("compute_capability"),
            g.get("max_cuda"), g.get("source")))
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
