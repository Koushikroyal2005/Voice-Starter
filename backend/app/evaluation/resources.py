"""Process-only resource measurements; no sampler in the production worker."""

import ctypes
import os
import platform
import time


def memory_snapshot():
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("faults", wintypes.DWORD),
                *[
                    (name, ctypes.c_size_t)
                    for name in (
                        "peak_rss",
                        "rss",
                        "peak_paged",
                        "paged",
                        "peak_nonpaged",
                        "nonpaged",
                        "pagefile",
                        "peak_pagefile",
                    )
                ],
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return {
                "rss_bytes": counters.rss,
                "process_peak_rss_bytes": counters.peak_rss,
            }
    else:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "rss_bytes": None,
            "process_peak_rss_bytes": peak
            * (1 if platform.system() == "Darwin" else 1024),
        }
    return {"rss_bytes": None, "process_peak_rss_bytes": None}


class ResourceWindow:
    def __init__(self):
        self.wall = time.perf_counter()
        self.cpu = time.process_time()
        self.before = memory_snapshot()

    def finish(self):
        elapsed = time.perf_counter() - self.wall
        cpu = time.process_time() - self.cpu
        return {
            "scope": (
                "evaluation Python process only; "
                "excludes child/remote/browser processes"
            ),
            "wall_seconds": elapsed,
            "cpu_seconds": cpu,
            "average_cpu_percent_one_core": 100 * cpu / elapsed if elapsed else None,
            "memory_before": self.before,
            "memory_after": memory_snapshot(),
            "peak_scope": (
                "process lifetime, not reset per fixture; not a sampled per-run peak"
            ),
        }


def hardware():
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
