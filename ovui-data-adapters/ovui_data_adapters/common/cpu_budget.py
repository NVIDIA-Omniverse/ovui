# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The CPUs that this process may use: its CPU affinity and the CPU quota of its cgroup.

A container can see all CPUs of its host and still get the time of a few of
them through a cgroup CPU quota, for example 32 CPUs of a host with 192.
Thread pools that size themselves to the host then run many more threads than
the process has CPU time for. This module imports no renderer and no OpenUSD.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Optional

_CGROUP_ROOT = "/sys/fs/cgroup"
_PROC_CGROUP = "/proc/self/cgroup"


def _report(message: str) -> None:
    print(f"[ovui_data_adapters] {message}", file=sys.stderr)


def _quota_cpus(quota: int, period: int) -> Optional[int]:
    if quota <= 0 or period <= 0:
        return None
    return max(1, math.ceil(quota / period))


def _cgroup_v2_quota(cgroup_path: str) -> Optional[int]:
    """The smallest ``cpu.max`` quota of the cgroup and its parents, in CPUs."""

    limits = []
    path = cgroup_path
    while True:
        file = os.path.join(_CGROUP_ROOT, path.lstrip("/"), "cpu.max")
        try:
            with open(file, encoding="ascii") as stream:
                quota, period = stream.read().split()[:2]
        except FileNotFoundError:
            pass
        else:
            if quota != "max":
                cpus = _quota_cpus(int(quota), int(period))
                if cpus is not None:
                    limits.append(cpus)
        if path in ("", "/"):
            break
        path = os.path.dirname(path.rstrip("/"))
    return min(limits) if limits else None


def _cgroup_v1_quota(cgroup_path: str) -> Optional[int]:
    """The CFS quota of the cgroup v1 ``cpu`` controller, in CPUs."""

    for folder in ("cpu,cpuacct", "cpu"):
        base = os.path.join(_CGROUP_ROOT, folder)
        for path in (os.path.join(base, cgroup_path.lstrip("/")), base):
            try:
                with open(os.path.join(path, "cpu.cfs_quota_us"), encoding="ascii") as stream:
                    quota = int(stream.read())
                with open(os.path.join(path, "cpu.cfs_period_us"), encoding="ascii") as stream:
                    period = int(stream.read())
            except FileNotFoundError:
                continue
            return _quota_cpus(quota, period)
    return None


def cgroup_cpu_quota() -> Optional[int]:
    """The CPU quota of this process's cgroup, rounded up to whole CPUs; None when there is none."""

    try:
        with open(_PROC_CGROUP, encoding="utf-8") as stream:
            entries = [line.rstrip("\n").split(":", 2) for line in stream if line.strip()]
    except FileNotFoundError:
        return None  # Not Linux, or no cgroups.
    v2_path = next((path for hierarchy, _controllers, path in entries if hierarchy == "0"), None)
    v1_path = next(
        (path for _hierarchy, controllers, path in entries if "cpu" in controllers.split(",")),
        None,
    )
    if v2_path is not None:
        quota = _cgroup_v2_quota(v2_path)
        if quota is not None:
            return quota
    if v1_path is not None:
        return _cgroup_v1_quota(v1_path)
    return None


def usable_cpu_count() -> Optional[int]:
    """The CPUs that this process may use: its CPU affinity and its cgroup CPU quota."""

    counts = []
    get_affinity = getattr(os, "sched_getaffinity", None)
    if get_affinity is not None:
        counts.append(len(get_affinity(0)))
    try:
        quota = cgroup_cpu_quota()
    except (OSError, ValueError) as error:
        _report(f"cannot read the CPU quota of this process ({type(error).__name__}: {error}); "
                "only its CPU affinity is used")
        quota = None
    if quota is not None:
        counts.append(quota)
    return min(counts) if counts else None
