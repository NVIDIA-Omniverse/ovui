# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Artifact metadata and private atomic JSON output for renderer tools."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
from pathlib import Path
from typing import Any


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(4) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
    temporary.replace(path)


def artifact(path: Path, *, kind: str, **metadata) -> dict:
    return {
        "path": str(path.resolve()),
        "kind": kind,
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **metadata,
    }
