"""Resource accounting for child processes (peak RAM, CPU time). Standard library only.

    proc = subprocess.Popen(...); out = proc.communicate()
    stats = procstats.collect(proc)   # call BEFORE the Popen object is garbage-collected
    -> {"peak_ram_mb": 1234.5, "cpu_seconds": 56.7}
"""
import sys


def collect(proc):
    try:
        if sys.platform == "win32":
            return _win(proc)
        import resource
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        scale = 1 if sys.platform == "darwin" else 1024  # macOS bytes, Linux KB
        return {"peak_ram_mb": round(ru.ru_maxrss * scale / 1024 ** 2, 1),
                "cpu_seconds": round(ru.ru_utime + ru.ru_stime, 1),
                "note": "POSIX RUSAGE_CHILDREN (largest child so far)"}
    except Exception as e:  # noqa: BLE001 - accounting must never break a run
        return {"error": str(e)[:100]}


def _win(proc):
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    handle = int(proc._handle)
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(handle), ctypes.byref(pmc), pmc.cb)
    ft = [wintypes.FILETIME() for _ in range(4)]
    ok2 = ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(handle), *[ctypes.byref(x) for x in ft])
    out = {}
    if ok:
        out["peak_ram_mb"] = round(pmc.PeakWorkingSetSize / 1024 ** 2, 1)
    if ok2:
        def secs(f):
            return ((f.dwHighDateTime << 32) + f.dwLowDateTime) / 1e7
        out["cpu_seconds"] = round(secs(ft[2]) + secs(ft[3]), 1)
    return out
