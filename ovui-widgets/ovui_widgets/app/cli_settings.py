# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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
from typing import Any, Dict, List, Sequence, Tuple

OVERRIDE_PREFIX = "--/"

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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


__all__ = [
    "OVERRIDE_PREFIX",
    "coerce_value",
    "extract_setting_overrides",
    "parse_override_token",
]
