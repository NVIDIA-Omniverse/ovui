# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Command-line settings overrides.

Supports Kit-style ``--/path/to/key=value`` arguments on the app command
line. The slash path maps to the dotted key used by
:class:`ovui_widgets.common.settings.Settings` (``--/ui/theme=light`` sets
``ui.theme``), and the value text is coerced to a scalar: ``true``/``false``
(case-insensitive) become ``bool``, then ``int``, then ``float`` are tried,
and anything else stays a string.
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Sequence, Tuple

OVERRIDE_PREFIX = "--/"

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_BACKEND_SETTING = "app.renderer.backend"
_BACKEND_ENV = "OMNIUI_BACKEND"
_RENDER_FLOW_MODE_SETTING = "app.renderer.flowMode"
_RENDER_FLOW_MODE_ENV = "OMNIUI_RENDER_FLOW_MODE"
_DEFAULT_RENDER_FLOW_MODE = "nativePacing"


def coerce_value(text: str) -> Any:
    """Coerce override value text to bool / int / float, else keep the string."""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_override_token(token: str) -> Tuple[str, Any]:
    """Parse one ``--/path/to/key=value`` token into ``(dotted_key, value)``.

    Raises :class:`ValueError` with a user-facing message when the token is
    malformed (missing ``=``, empty path, or empty/invalid path segments).
    """
    if not token.startswith(OVERRIDE_PREFIX):
        raise ValueError(f"not a settings override: {token!r}")
    body = token[len(OVERRIDE_PREFIX):]
    path, sep, value_text = body.partition("=")
    if not sep:
        raise ValueError(
            f"invalid settings override {token!r}: expected --/path/to/key=value"
        )
    segments = path.split("/")
    if not path or any(not _SEGMENT_RE.match(segment) for segment in segments):
        raise ValueError(
            f"invalid settings override {token!r}: setting path must be "
            "non-empty /-separated segments of letters, digits, '_', '-' or '.'"
        )
    return ".".join(segments), coerce_value(value_text)


def extract_setting_overrides(
    argv: Sequence[str],
) -> Tuple[Dict[str, Any], List[str]]:
    """Split ``argv`` into settings overrides and the remaining arguments.

    Every token starting with ``--/`` is consumed as an override (later
    duplicates win); everything else is returned in order for the regular
    argument parser. A literal ``--`` ends override extraction, matching
    the usual end-of-options convention. Raises :class:`ValueError` on a
    malformed override token.
    """
    overrides: Dict[str, Any] = {}
    remaining: List[str] = []
    for index, token in enumerate(argv):
        if token == "--":
            remaining.extend(argv[index:])
            break
        if token.startswith(OVERRIDE_PREFIX):
            key, value = parse_override_token(token)
            overrides[key] = value
        else:
            remaining.append(token)
    return overrides, remaining


def apply_early_setting_overrides(overrides: Dict[str, Any]) -> None:
    """Apply settings needed before importing or initializing ``omni.ui``."""
    # Leave the automatic native Vulkan preference (and OpenGL fallback) intact.
    # An environment override is explicit too; only a CLI setting supersedes it.
    backend = str(overrides.get(_BACKEND_SETTING, "")).strip().lower()
    if backend in {"ogl", "opengl", "gl"}:
        os.environ[_BACKEND_ENV] = "opengl"
    elif backend in {"vk", "vulkan"}:
        os.environ[_BACKEND_ENV] = "vulkan"
    elif backend:
        raise ValueError(
            f"invalid {_BACKEND_SETTING}={backend!r}: expected ogl or vk"
        )

    render_flow_mode = str(
        overrides.get(_RENDER_FLOW_MODE_SETTING, _DEFAULT_RENDER_FLOW_MODE)
    ).strip()
    if render_flow_mode not in {"fast", "nativePacing"}:
        raise ValueError(
            f"invalid {_RENDER_FLOW_MODE_SETTING}={render_flow_mode!r}: "
            "expected fast or nativePacing"
        )
    os.environ[_RENDER_FLOW_MODE_ENV] = render_flow_mode

    viewport_width = overrides.get("app.viewport.width")
    viewport_height = overrides.get("app.viewport.height")
    if viewport_width is not None or viewport_height is not None:
        if viewport_width is None or viewport_height is None:
            raise ValueError("app.viewport.width and app.viewport.height must be provided together")
        overrides["viewport.instances.main.resolution"] = [
            int(viewport_width),
            int(viewport_height),
        ]


__all__ = [
    "OVERRIDE_PREFIX",
    "apply_early_setting_overrides",
    "coerce_value",
    "extract_setting_overrides",
    "parse_override_token",
]
