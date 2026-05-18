# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""POSIX ``/proc/mounts`` parser — drive discovery without psutil.

See the content browser behavior and the content browser implementation step 43.

:class:`MyComputerCollection` (``collections/my_computer.py``) needs a
list of real mount points on Linux / macOS, but adding ``psutil`` as a
runtime dependency for one call is disproportionate. The architecture
spec's minimal replacement is a 20-line ``/proc/mounts`` parser that
returns enough information for the collection to apply its filesystem-
type / mount-option filters.

On Windows, drive enumeration goes through
``ctypes.windll.kernel32.GetLogicalDrives()`` directly — this module's
:func:`disk_partitions` raises :class:`NotImplementedError` there so a
caller that forgets the platform branch gets a clean, loud failure
rather than silently empty data.

The filter constants live here alongside the parser so a future consumer
(e.g. a different collection that wants the same "real mounts only"
view) can pull parser + filter from a single module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple

# Synthetic / kernel-virtual filesystems whose mount points are never
# useful navigation destinations in a file browser. Matches
# the content browser behavior and the content browser implementation step 43's
# explicit filter set.
FSTYPE_BLOCKLIST: frozenset = frozenset({
    "tmpfs",
    "proc",
    "devpts",
    "sysfs",
    "nsfs",
    "autofs",
    "cgroup",
    "hugetlbfs",
})


# Path to the kernel mount table on Linux. Isolated as a module
# constant so tests can monkey-patch it to a fixture file without
# patching module internals.
MOUNTS_PATH = "/proc/mounts"


@dataclass(frozen=True)
class Partition:
    """One row from ``/proc/mounts`` — a single mounted filesystem.

    Field order follows the ``/proc/mounts`` column order (device,
    mount point, fstype, mount options) so the dataclass maps 1:1 to a
    split line. Frozen because a mount-table row is an immutable
    observation at parse time; mutating it later would make the
    :func:`disk_partitions` return value look stateful.

    ``opts`` is the raw comma-joined mount-option string (e.g.
    ``"rw,relatime"``) — callers that need a set can ``.split(",")``
    themselves. Keeping it as a string avoids allocating a set the
    majority of callers do not use.
    """

    device: str
    mountpoint: str
    fstype: str
    opts: str


def _parse_mounts_line(line: str) -> "Partition | None":
    """Split one ``/proc/mounts`` row into a :class:`Partition`.

    Returns ``None`` for a blank / malformed line so the parser can
    tolerate a comment line or a trailing newline without raising.
    ``/proc/mounts`` escapes space / tab / backslash / newline in
    paths as ``\\040`` / ``\\011`` / ``\\134`` / ``\\012``; decode
    those so a mount at ``/mnt/My Drive`` round-trips cleanly.
    """
    parts = line.split()
    if len(parts) < 4:
        return None
    device = _decode_mounts_field(parts[0])
    mountpoint = _decode_mounts_field(parts[1])
    fstype = parts[2]
    opts = parts[3]
    return Partition(
        device=device,
        mountpoint=mountpoint,
        fstype=fstype,
        opts=opts,
    )


_MOUNTS_ESCAPES: Tuple[Tuple[str, str], ...] = (
    (r"\040", " "),
    (r"\011", "\t"),
    (r"\012", "\n"),
    (r"\134", "\\"),
)


def _decode_mounts_field(field: str) -> str:
    """Decode the octal escapes the kernel writes into ``/proc/mounts``."""
    for needle, repl in _MOUNTS_ESCAPES:
        if needle in field:
            field = field.replace(needle, repl)
    return field


def disk_partitions() -> List[Partition]:
    """Parse :data:`MOUNTS_PATH` and return every mounted partition.

    The returned list preserves ``/proc/mounts`` order — that's the
    order the kernel reports mounts in, which is stable enough for the
    "drives listed in mount order" UX without an extra sort step.

    Callers apply their own filters (fstype / opts / mountpoint
    dedup) on top. The parser itself does NOT filter so tests can
    assert the full raw output separately from the collection's
    filtering policy.

    Raises :class:`NotImplementedError` on Windows — drive discovery
    there uses ``kernel32.GetLogicalDrives`` directly, not
    ``/proc/mounts`` (which does not exist on NT). Callers who run on
    both platforms are expected to branch on :data:`os.name`
    themselves rather than relying on this function to no-op.
    """
    if os.name == "nt":
        raise NotImplementedError(
            "disk_partitions() is POSIX-only; use "
            "ctypes.windll.kernel32.GetLogicalDrives on Windows.",
        )

    partitions: List[Partition] = []
    with open(MOUNTS_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            partition = _parse_mounts_line(line)
            if partition is not None:
                partitions.append(partition)
    return partitions
