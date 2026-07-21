# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Entry-point loader for optional ovui-widgets UI components."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
import traceback
from typing import Any


COMPONENT_ENTRY_POINT_GROUP = "ovui_widgets.components"


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


def discover_component_modules(app: Any) -> tuple[ComponentModuleLoadFailure, ...]:
    """Load ``ovui_widgets.components`` entry points and call ``register(app)``."""
    failures: list[ComponentModuleLoadFailure] = []
    for entry_point in entry_points(group=COMPONENT_ENTRY_POINT_GROUP):
        try:
            register = entry_point.load()
            register(app)
        except Exception as exc:
            report = getattr(app, "report_module_load_failure", None)
            if callable(report):
                reported = report(entry_point.name, entry_point.value, exc)
                if isinstance(reported, ComponentModuleLoadFailure):
                    failures.append(reported)
                    continue
            failures.append(
                ComponentModuleLoadFailure.from_exception(
                    entry_point.name,
                    entry_point.value,
                    exc,
                )
            )
    return tuple(failures)
