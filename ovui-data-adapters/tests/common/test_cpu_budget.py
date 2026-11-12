# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The CPUs that the process may use: CPU affinity and cgroup CPU quota.

In a container with a CPU quota the host CPU count is much larger than the CPU
time that the process gets. These tests read cgroup files that the test writes.
"""

from __future__ import annotations

import pytest

from ovui_data_adapters.common import cpu_budget


@pytest.fixture
def cgroup(tmp_path, monkeypatch):
    """A fake cgroup tree and /proc/self/cgroup file; returns a writer for both."""

    root = tmp_path / "cgroup"
    root.mkdir()
    proc = tmp_path / "proc_self_cgroup"
    monkeypatch.setattr(cpu_budget, "_CGROUP_ROOT", str(root))
    monkeypatch.setattr(cpu_budget, "_PROC_CGROUP", str(proc))

    def write(proc_text: str, files: dict[str, str]) -> None:
        proc.write_text(proc_text)
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    return write


def test_cgroup_v2_quota_is_rounded_up_to_whole_cpus(cgroup):
    cgroup("0::/\n", {"cpu.max": "3200000 100000\n"})
    assert cpu_budget.cgroup_cpu_quota() == 32
    cgroup("0::/\n", {"cpu.max": "150000 100000\n"})
    assert cpu_budget.cgroup_cpu_quota() == 2


def test_cgroup_v2_without_a_quota_gives_none(cgroup):
    cgroup("0::/\n", {"cpu.max": "max 100000\n"})
    assert cpu_budget.cgroup_cpu_quota() is None


def test_cgroup_v2_takes_the_smallest_quota_of_the_cgroup_and_its_parents(cgroup):
    cgroup(
        "0::/kubepods/pod1/app\n",
        {
            "cpu.max": "max 100000\n",
            "kubepods/cpu.max": "800000 100000\n",
            "kubepods/pod1/cpu.max": "400000 100000\n",
            "kubepods/pod1/app/cpu.max": "max 100000\n",
        },
    )
    assert cpu_budget.cgroup_cpu_quota() == 4


def test_cgroup_v1_cfs_quota(cgroup):
    cgroup(
        "4:cpu,cpuacct:/docker/abc\n2:memory:/docker/abc\n",
        {
            "cpu,cpuacct/docker/abc/cpu.cfs_quota_us": "1600000\n",
            "cpu,cpuacct/docker/abc/cpu.cfs_period_us": "100000\n",
        },
    )
    assert cpu_budget.cgroup_cpu_quota() == 16
    cgroup(
        "4:cpu,cpuacct:/docker/abc\n",
        {
            "cpu,cpuacct/docker/abc/cpu.cfs_quota_us": "-1\n",
            "cpu,cpuacct/docker/abc/cpu.cfs_period_us": "100000\n",
        },
    )
    assert cpu_budget.cgroup_cpu_quota() is None


def test_an_unreadable_quota_is_reported_and_only_the_affinity_is_used(cgroup, capsys, monkeypatch):
    cgroup("0::/\n", {"cpu.max": "not a number\n"})
    monkeypatch.setattr(cpu_budget.os, "sched_getaffinity", lambda pid: set(range(8)), raising=False)
    assert cpu_budget.usable_cpu_count() == 8
    assert "cannot read the CPU quota of this process (ValueError" in capsys.readouterr().err
