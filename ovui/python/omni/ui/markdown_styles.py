# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Reusable MarkdownWidget style presets.

These helpers intentionally return plain Python dictionaries so applications can
copy, mutate, and embed the styles directly in local workflows.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from .color_utils import color as _color


MarkdownStyleName = Literal["white", "dark-blue", "black"]
MARKDOWN_STYLE_NAMES: tuple[MarkdownStyleName, ...] = ("white", "dark-blue", "black")
DEFAULT_MARKDOWN_STYLE: MarkdownStyleName = "black"


class MarkdownTheme(TypedDict):
    background: int
    style: dict


def _normalize_name(name: str | None) -> MarkdownStyleName:
    if not name:
        return DEFAULT_MARKDOWN_STYLE
    normalized = name.strip().lower().replace("_", "-")
    aliases = {
        "light": "white",
        "dark": "black",
        "darkblue": "dark-blue",
        "blue": "dark-blue",
        "default": "black",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in MARKDOWN_STYLE_NAMES:
        raise ValueError(f"Unknown MarkdownWidget style {name!r}; expected one of {MARKDOWN_STYLE_NAMES}")
    return normalized  # type: ignore[return-value]


def _syntax_colors(name: MarkdownStyleName) -> dict:
    if name == "white":
        # Values ported from the Shiki github-light theme so light-surface
        # code blocks match the same reference renders used by the quality
        # corpus oracle (markdown/quality_harness/oracle). Keyword uses the
        # slightly-warmer #d73a49 that Shiki renders instead of the spec
        # #cf222e — matches what the oracle pixels actually show.
        return {
            "MarkdownWidget.CodeBlock.Keyword": {"color": _color(0.843, 0.227, 0.286)},  # #d73a49
            "MarkdownWidget.CodeBlock.String": {"color": _color(0.039, 0.188, 0.412)},   # #0a3069
            "MarkdownWidget.CodeBlock.Comment": {"color": _color(0.431, 0.467, 0.506)},  # #6e7781
            "MarkdownWidget.CodeBlock.Number": {"color": _color(0.020, 0.314, 0.682)},   # #0550ae
            "MarkdownWidget.CodeBlock.Punctuation": {"color": _color(0.141, 0.161, 0.184)},  # #24292f
        }
    if name == "dark-blue":
        return {
            "MarkdownWidget.CodeBlock.Keyword": {"color": _color(0.50, 0.74, 1.0)},
            "MarkdownWidget.CodeBlock.String": {"color": _color(1.0, 0.77, 0.48)},
            "MarkdownWidget.CodeBlock.Comment": {"color": _color(0.52, 0.62, 0.74)},
            "MarkdownWidget.CodeBlock.Number": {"color": _color(0.78, 0.62, 1.0)},
            "MarkdownWidget.CodeBlock.Punctuation": {"color": _color(0.72, 0.80, 0.90)},
        }
    return {
        "MarkdownWidget.CodeBlock.Keyword": {"color": _color(0.68, 0.82, 1.0)},
        "MarkdownWidget.CodeBlock.String": {"color": _color(0.94, 0.74, 0.48)},
        "MarkdownWidget.CodeBlock.Comment": {"color": _color(0.56, 0.58, 0.62)},
        "MarkdownWidget.CodeBlock.Number": {"color": _color(0.78, 0.66, 0.95)},
        "MarkdownWidget.CodeBlock.Punctuation": {"color": _color(0.78, 0.80, 0.84)},
    }


def markdown_background(name: str | None = DEFAULT_MARKDOWN_STYLE) -> int:
    """Return the companion background color for a MarkdownWidget preset."""

    style_name = _normalize_name(name)
    if style_name == "white":
        return _color(0.99, 0.995, 1.0)
    if style_name == "dark-blue":
        return _color(0.035, 0.055, 0.10)
    return _color(0.025, 0.025, 0.028)


def markdown_style(
    name: str | None = DEFAULT_MARKDOWN_STYLE,
    *,
    table_policy: str = "equal",
    font_size: int | float = 14,
) -> dict:
    """Return a fresh style dictionary for MarkdownWidget.

    Args:
        name: ``"white"``, ``"dark-blue"``, or ``"black"``.
        table_policy: MarkdownWidget.Table ``layout_policy`` value.
        font_size: Base MarkdownWidget font size in pixels.
    """

    style_name = _normalize_name(name)

    if style_name == "white":
        # Surface + chrome colours mirror the oracle's CSS
        # (markdown/quality_harness/oracle/src/index.css):
        #   :root  color       #0f172a  -> body text
        #   pre    background  #f6f8fa  -> code-block body
        #   pre    color       #24292f  -> code body text
        #   border             #d0d7de  -> chrome border
        #   muted-foreground   #57606a  -> lang label / line numbers
        style = {
            "MarkdownWidget": {
                "font_size": font_size,
                "color": _color(0.059, 0.090, 0.165),          # #0f172a
                "secondary_color": _color(0.020, 0.051, 0.106),
                "secondary_selected_color": _color(0.020, 0.314, 0.682),
                "secondary_background_color": _color(0.965, 0.972, 0.980, 1.0),  # #f6f8fa
                "border_color": _color(0.816, 0.843, 0.871),  # #d0d7de
            },
            "MarkdownWidget.Link": {
                "color": _color(0.020, 0.314, 0.682),
                "selected_color": _color(0.0, 0.42, 0.86),
            },
            "MarkdownWidget.HeadingAnchor": {"color": _color(0.0, 0.34, 0.72, 0.72)},
            "MarkdownWidget.Code": {
                "color": _color(0.141, 0.161, 0.184),  # #24292f
                "background_color": _color(0.945, 0.960, 0.976, 1.0),  # ~Tailwind slate-100
            },
            "MarkdownWidget.CodeBlock": {
                "color": _color(0.141, 0.161, 0.184),  # #24292f body text
                "background_color": _color(0.965, 0.972, 0.980, 1.0),  # #f6f8fa
                "border_color": _color(0.816, 0.843, 0.871),  # #d0d7de
                "secondary_color": _color(0.341, 0.376, 0.416),  # #57606a lang chip
                "border_radius": 8,  # match oracle's 8px
            },
            "MarkdownWidget.CodeBlock.CopyButton": {
                "color": _color(0.341, 0.376, 0.416),
                "background_color": _color(0.922, 0.929, 0.945, 1.0),
                "border_color": _color(0.816, 0.843, 0.871),
            },
            "MarkdownWidget.Table": {
                "layout_policy": table_policy,
                "color": _color(0.12, 0.15, 0.20),
                "secondary_color": _color(0.03, 0.05, 0.09),
                "background_color": _color(0.88, 0.93, 0.98, 0.96),
                "secondary_background_color": _color(0.95, 0.97, 0.99, 0.96),
                "border_color": _color(0.62, 0.70, 0.80),
            },
            "MarkdownWidget.Image": {
                "color": _color(0.42, 0.48, 0.58),
                "background_color": _color(0.92, 0.95, 0.98, 0.96),
                "border_color": _color(0.70, 0.76, 0.84),
            },
            # Blockquote: oracle draws a 4 px left bar in slate-300
            # (#cbd5e1) and no background. Alpha=0 turns off the tint that
            # would otherwise be derived from secondary_background_color.
            "MarkdownWidget.Quote": {
                "color": _color(0.20, 0.23, 0.33),
                "secondary_color": _color(0.796, 0.835, 0.882),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
                "border_width": 4,
                "padding": 18,
            },
            # Alerts: oracle's GitHub alert plugin renders with a coloured
            # left bar + uppercased label only — no tinted background fill.
            # background_color alpha=0 turns off the fill rect.
            "MarkdownWidget.Alert.Note": {
                "color": _color(0.06, 0.18, 0.34),
                "secondary_color": _color(0.0, 0.31, 0.68),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Tip": {
                "color": _color(0.04, 0.22, 0.10),
                "secondary_color": _color(0.10, 0.50, 0.22),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Important": {
                "color": _color(0.24, 0.12, 0.42),
                "secondary_color": _color(0.46, 0.27, 0.78),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Warning": {
                "color": _color(0.32, 0.22, 0.02),
                "secondary_color": _color(0.72, 0.47, 0.00),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Caution": {
                "color": _color(0.38, 0.04, 0.07),
                "secondary_color": _color(0.72, 0.10, 0.14),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            # Heading hierarchy targets the oracle's rendered cap-heights
            # (measured 28/23/18/18/15/13 px on atoms/02_headings.md). ImGui
            # renders at roughly 77% of declared size so we scale up to land
            # the same visible weight.
            "MarkdownWidget.H1": {"font_size": 36, "color": _color(0.02, 0.05, 0.10)},
            "MarkdownWidget.H2": {"font_size": 30, "color": _color(0.05, 0.12, 0.22)},
            "MarkdownWidget.H3": {"font_size": 24, "color": _color(0.05, 0.12, 0.22)},
            "MarkdownWidget.H4": {"font_size": 22, "color": _color(0.05, 0.12, 0.22)},
            "MarkdownWidget.H5": {"font_size": 20, "color": _color(0.05, 0.12, 0.22)},
            "MarkdownWidget.H6": {"font_size": 18, "color": _color(0.05, 0.12, 0.22)},
        }
    elif style_name == "dark-blue":
        style = {
            "MarkdownWidget": {
                "font_size": font_size,
                "color": _color(0.84, 0.90, 0.98),
                "secondary_color": _color(0.98, 1.0, 1.0),
                "secondary_selected_color": _color(0.42, 0.70, 1.0),
                "secondary_background_color": _color(0.08, 0.13, 0.22, 0.86),
                "border_color": _color(0.24, 0.34, 0.48),
            },
            "MarkdownWidget.Link": {
                "color": _color(0.42, 0.70, 1.0),
                "selected_color": _color(0.62, 0.82, 1.0),
            },
            "MarkdownWidget.HeadingAnchor": {"color": _color(0.62, 0.82, 1.0, 0.72)},
            "MarkdownWidget.Code": {
                "color": _color(1.0, 0.78, 0.52),
                "background_color": _color(0.13, 0.18, 0.26, 0.96),
            },
            "MarkdownWidget.CodeBlock": {
                "color": _color(0.88, 0.94, 1.0),
                "background_color": _color(0.06, 0.10, 0.17, 0.98),
                "border_color": _color(0.25, 0.38, 0.54),
                "secondary_color": _color(0.62, 0.74, 0.88),
            },
            "MarkdownWidget.CodeBlock.CopyButton": {
                "color": _color(0.88, 0.94, 1.0),
                "background_color": _color(0.12, 0.19, 0.30, 1.0),
                "border_color": _color(0.32, 0.48, 0.66),
            },
            "MarkdownWidget.Table": {
                "layout_policy": table_policy,
                "color": _color(0.82, 0.89, 0.97),
                "secondary_color": _color(0.96, 0.98, 1.0),
                "background_color": _color(0.10, 0.17, 0.28, 0.96),
                "secondary_background_color": _color(0.07, 0.12, 0.20, 0.96),
                "border_color": _color(0.25, 0.38, 0.54),
            },
            "MarkdownWidget.Image": {
                "color": _color(0.62, 0.72, 0.84),
                "background_color": _color(0.10, 0.16, 0.25, 0.96),
                "border_color": _color(0.25, 0.38, 0.54),
            },
            "MarkdownWidget.Quote": {
                "color": _color(0.71, 0.78, 0.88),
                "secondary_color": _color(0.20, 0.31, 0.47),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
                "border_width": 4,
                "padding": 18,
            },
            "MarkdownWidget.Alert.Note": {
                "color": _color(0.78, 0.88, 1.0),
                "secondary_color": _color(0.38, 0.66, 1.0),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Tip": {
                "color": _color(0.70, 0.95, 0.76),
                "secondary_color": _color(0.18, 0.72, 0.36),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Important": {
                "color": _color(0.86, 0.76, 1.0),
                "secondary_color": _color(0.62, 0.44, 1.0),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Warning": {
                "color": _color(1.0, 0.86, 0.56),
                "secondary_color": _color(0.95, 0.67, 0.12),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Caution": {
                "color": _color(1.0, 0.72, 0.74),
                "secondary_color": _color(1.0, 0.34, 0.40),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.H1": {"font_size": 30, "color": _color(0.96, 0.99, 1.0)},
            "MarkdownWidget.H2": {"font_size": 22, "color": _color(0.86, 0.94, 1.0)},
        }
    else:
        style = {
            "MarkdownWidget": {
                "font_size": font_size,
                "color": _color(0.84, 0.86, 0.88),
                "secondary_color": _color(0.98, 0.98, 0.98),
                "secondary_selected_color": _color(0.72, 0.76, 0.82),
                "secondary_background_color": _color(0.13, 0.13, 0.14, 0.90),
                "border_color": _color(0.34, 0.35, 0.38),
            },
            "MarkdownWidget.Link": {
                "color": _color(0.78, 0.82, 0.88),
                "selected_color": _color(0.95, 0.96, 0.98),
            },
            "MarkdownWidget.HeadingAnchor": {"color": _color(0.78, 0.82, 0.88, 0.72)},
            "MarkdownWidget.Code": {
                "color": _color(0.94, 0.74, 0.48),
                "background_color": _color(0.17, 0.17, 0.18, 0.96),
            },
            "MarkdownWidget.CodeBlock": {
                "color": _color(0.86, 0.88, 0.91),
                "background_color": _color(0.08, 0.08, 0.09, 0.98),
                "border_color": _color(0.34, 0.35, 0.38),
                "secondary_color": _color(0.60, 0.62, 0.66),
            },
            "MarkdownWidget.CodeBlock.CopyButton": {
                "color": _color(0.90, 0.91, 0.93),
                "background_color": _color(0.17, 0.17, 0.18, 1.0),
                "border_color": _color(0.40, 0.41, 0.44),
            },
            "MarkdownWidget.Table": {
                "layout_policy": table_policy,
                "color": _color(0.82, 0.84, 0.87),
                "secondary_color": _color(0.96, 0.97, 0.98),
                "background_color": _color(0.15, 0.15, 0.16, 0.96),
                "secondary_background_color": _color(0.09, 0.09, 0.10, 0.96),
                "border_color": _color(0.36, 0.37, 0.40),
            },
            "MarkdownWidget.Image": {
                "color": _color(0.62, 0.64, 0.68),
                "background_color": _color(0.15, 0.15, 0.16, 0.96),
                "border_color": _color(0.36, 0.37, 0.40),
            },
            "MarkdownWidget.Quote": {
                "color": _color(0.79, 0.79, 0.79),
                "secondary_color": _color(0.23, 0.23, 0.23),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
                "border_width": 4,
                "padding": 18,
            },
            "MarkdownWidget.Alert.Note": {
                "color": _color(0.84, 0.87, 0.92),
                "secondary_color": _color(0.76, 0.80, 0.86),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Tip": {
                "color": _color(0.82, 0.90, 0.84),
                "secondary_color": _color(0.45, 0.72, 0.50),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Important": {
                "color": _color(0.88, 0.82, 0.96),
                "secondary_color": _color(0.68, 0.58, 0.86),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Warning": {
                "color": _color(0.94, 0.84, 0.62),
                "secondary_color": _color(0.78, 0.61, 0.26),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.Alert.Caution": {
                "color": _color(0.98, 0.74, 0.76),
                "secondary_color": _color(0.88, 0.36, 0.40),
                "background_color": _color(0.0, 0.0, 0.0, 0.0),
            },
            "MarkdownWidget.H1": {"font_size": 30, "color": _color(0.97, 0.98, 0.99)},
            "MarkdownWidget.H2": {"font_size": 22, "color": _color(0.90, 0.92, 0.95)},
        }

    style.update(_syntax_colors(style_name))
    return style


def markdown_theme(
    name: str | None = DEFAULT_MARKDOWN_STYLE,
    *,
    table_policy: str = "equal",
    font_size: int | float = 14,
) -> MarkdownTheme:
    """Return ``{"background": int, "style": dict}`` for MarkdownWidget demos."""

    style_name = _normalize_name(name)
    return {
        "background": markdown_background(style_name),
        "style": markdown_style(style_name, table_policy=table_policy, font_size=font_size),
    }
