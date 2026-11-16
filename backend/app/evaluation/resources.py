"""Process-only resource measurements; no sampler in the production worker."""

import ctypes
import os
import platform
import subprocess
import time


def memory_snapshot(process_handle=None):
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
            process_handle or kernel.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            return {
                "rss_bytes": counters.rss,
                "process_peak_rss_bytes": counters.peak_rss,
            }
    elif process_handle is None:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "rss_bytes": None,
            "process_peak_rss_bytes": peak
            * (1 if platform.system() == "Darwin" else 1024),
        }
    return {"rss_bytes": None, "process_peak_rss_bytes": None}


def run_measured_child(command, **kwargs):
    """Bounded evaluation subprocess; never include its CPU in parent metrics.

    Windows child CPU uses GetProcessTimes. Peak working set is sampled while
    alive; a very short-lived allocation may be missed. No runtime sampler.
    """
    timeout = kwargs.pop("timeout")
    check = kwargs.pop("check", False)
    started = time.perf_counter()
    handle, kernel, cpu_seconds, peak = None, None, None, None
    with subprocess.Popen(command, **kwargs) as process:
        try:
            if os.name == "nt":
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [
                    wintypes.DWORD,
                    wintypes.BOOL,
                    wintypes.DWORD,
                ]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = kernel.OpenProcess(0x410, False, process.pid)
            while process.poll() is None:
                if handle:
                    value = memory_snapshot(handle)["process_peak_rss_bytes"]
                    if value is not None:
                        peak = max(peak or 0, value)
                remaining = timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    process.wait(timeout=min(0.01, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if handle:
                times = [wintypes.FILETIME() for _ in range(4)]
                kernel.GetProcessTimes.argtypes = [
                    wintypes.HANDLE,
                    *([ctypes.POINTER(wintypes.FILETIME)] * 4),
                ]
                if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    cpu_seconds = (
                        sum(
                            (t.dwHighDateTime << 32) + t.dwLowDateTime
                            for t in times[2:]
                        )
                        / 10_000_000
                    )
            if check and process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
            elapsed = time.perf_counter() - started
            return subprocess.CompletedProcess(command, process.returncode), {
                "scope": "owned child only; includes startup, model load and I/O",
                "wall_seconds": elapsed,
                "cpu_seconds": cpu_seconds,
                "average_cpu_percent_one_core": 100 * cpu_seconds / elapsed
                if cpu_seconds is not None
                else None,
                "sampled_process_peak_rss_bytes": peak,
                "sampling_interval_seconds": 0.01,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if handle:
                kernel.CloseHandle(handle)


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
