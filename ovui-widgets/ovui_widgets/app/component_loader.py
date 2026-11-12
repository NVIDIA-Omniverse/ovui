# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Load-failure record for optional ovui-widgets UI components."""

from __future__ import annotations

from dataclasses import dataclass
import traceback


@dataclass(frozen=True)
class ComponentModuleLoadFailure:
    """Structured diagnostic for one failed component entry point."""

    name: str
    value: str
    exception_type: str
    message: str
    traceback_summary: tuple[str, ...]

    @classmethod
    def from_exception(
        cls,
        name: str,
        value: str,
        exc: BaseException,
    ) -> "ComponentModuleLoadFailure":
        return cls(
            name=name,
            value=value,
            exception_type=type(exc).__name__,
            message=str(exc),
            traceback_summary=tuple(
                line.rstrip()
                for line in traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )

