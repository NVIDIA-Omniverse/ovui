# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The render settings a scene saved by Kit stores, as ovrtx attribute lines.

Kit stores them in the root layer ``customLayerData['renderSettings']``, keyed
``rtx:post:tonemap:op``, and applies them when it opens the scene. Without
them such a scene can render black.

ovrtx reads these settings from attributes of the viewport RenderProduct and
its Camera. The installed ``generatedSchema.usda`` of ovrtx documents the Kit
setting path of each attribute, and ``plugInfo.json`` the prim type that owns
it, so the mapping follows the installed ovrtx build.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
from typing import Any

from ovui_data_adapters.common.ovrtx_import import import_ovrtx, ovrtx_runtime_dirs

__all__ = ["stored_render_setting_lines"]

_CLASS = re.compile(r'^class "(?P<name>[^"]+)"')
_ATTRIBUTE = re.compile(
    r"^ {4}(?:(?:uniform|custom) )*(?P<type>[a-z0-9]+(?:\[\])?) (?P<name>[A-Za-z][\w:]*)\b"
    r"(?: = (?P<default>\([^)]*\)|[^(\s][^\n]*?))?(?: \(|$)"
)
_CARB_PATH = re.compile(r"carb setting path: '([^']+)'")
_ALLOWED_TOKENS = re.compile(r"allowedTokens = \[(?P<tokens>[^\]]*)\]")
#: The component count of a vector type, as in the 3 of ``color3f`` or ``int3``.
_TYPE_SIZE = re.compile(r"\d")

#: The values each USD integer type can hold. A wider stored number is no
#: value of that type: USD refuses the whole layer that states it, so the
#: scene would reach ovrtx without any of its settings.
_INTEGER_RANGE = {
    "int": (-(2**31), 2**31 - 1),
    "uint": (0, 2**32 - 1),
    "int64": (-(2**63), 2**63 - 1),
    "uint64": (0, 2**64 - 1),
}

#: Kit stores the tone mapper as a number; ovrtx names it with a token.
_KIT_TONEMAP_OPERATORS = (
    "raw", "none", "reinhard", "modifiedReinhard",
    "hejiHableAlu", "hableUc2", "acesApproximation", "iray",
)


def _schema_dir() -> Path | None:
    """Return the ``rtx_settings`` directory of the selected ovrtx install.

    A wheel keeps it under the Python package. An ``OVRTX_ROOT`` install keeps
    it beside the native libraries, which the resolver locates.
    """

    ovrtx = import_ovrtx().module
    if ovrtx is None:
        return None
    bin_dirs = (Path(ovrtx.__file__).parent / "bin", *ovrtx_runtime_dirs())
    for bin_dir in bin_dirs:
        schema_dir = bin_dir / "usd_plugins" / "rtx_settings"
        if (schema_dir / "generatedSchema.usda").is_file():
            return schema_dir
    print(
        "[stored render settings] the stored render settings of the scene are "
        "not applied: no usd_plugins/rtx_settings/generatedSchema.usda under "
        + ", ".join(str(bin_dir) for bin_dir in bin_dirs),
        file=sys.stderr,
    )
    return None


@lru_cache(maxsize=1)
def _ovrtx_setting_attributes() -> dict[str, tuple[str, str, str, tuple[str, ...]]]:
    """Kit setting path or attribute name -> (owner, USD type, attribute, tokens).

    The owner is the prim type that carries the attribute. A Kit path that
    two attributes claim has no single owner, ``None``. The default that the
    schema states for an attribute is kept in ``_SCHEMA_DEFAULTS``.
    """

    _SCHEMA_DEFAULTS.clear()
    schema_dir = _schema_dir()
    if schema_dir is None:
        return {}
    plug_info = json.loads(
        "\n".join(
            line
            for line in (schema_dir / "plugInfo.json").read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
    )
    owners = {
        spec["alias"]["UsdSchemaBase"]: spec["apiSchemaCanOnlyApplyTo"][0]
        for plugin in plug_info["Plugins"]
        for spec in plugin["Info"]["Types"].values()
        if len(spec.get("apiSchemaCanOnlyApplyTo", ())) == 1
    }
    attributes: list[list[Any]] = []
    owner = None
    in_body = False
    for line in (schema_dir / "generatedSchema.usda").read_text().splitlines():
        if line in ("{", "}"):
            in_body = line == "{"
        elif match := _CLASS.match(line):
            owner = owners.get(match["name"])
        elif in_body and (match := _ATTRIBUTE.match(line)):
            attributes.append([owner, match["type"], match["name"], (), []])
            if match["default"] is not None:
                _SCHEMA_DEFAULTS[match["name"]] = match["default"]
        elif in_body and attributes and (match := _ALLOWED_TOKENS.search(line)):
            attributes[-1][3] = tuple(re.findall(r'"([^"]*)"', match["tokens"]))
        elif in_body and attributes and (match := _CARB_PATH.search(line)):
            attributes[-1][4].append(match[1])
    claims: dict[str, list[tuple[str, str, str, tuple[str, ...]]]] = {}
    for owner, usd_type, name, tokens, carb_paths in attributes:
        for key in (name, *carb_paths):
            claims.setdefault(key, []).append((owner, usd_type, name, tokens))
    return {
        key: entries[0] if len(entries) == 1 else (None, "", "", ())
        for key, entries in claims.items()
    }


#: Attribute name -> the default its schema states, as USDA text.
_SCHEMA_DEFAULTS: dict[str, str] = {}


def _is_rtx_default(name: str, usd_type: str, literal: str) -> bool:
    """Whether ``literal`` is the default the ovrtx schema states for ``name``.

    Kit saves every render setting of a scene, most of them at their default,
    and ovrtx reads each one stated on the RenderProduct while it renders.
    Leaving a default out changes no pixel. Only the ``omni:rtx:`` settings
    are left out: an attribute of the USD Camera itself, such as
    ``exposure:fStop``, has a USD fallback that can differ from the ovrtx
    default.
    """

    default = _SCHEMA_DEFAULTS.get(name)
    if default is None or not name.startswith("omni:rtx:"):
        return False
    if usd_type == "bool":
        return {"1": "1", "true": "1", "0": "0", "false": "0"}.get(default) == literal
    if usd_type in ("token", "string"):
        return default == literal
    try:
        stated = [float(item) for item in literal.strip("()").split(",")]
        schema = [float(item) for item in default.strip("()").split(",")]
    except ValueError:
        return False
    # A float attribute holds a 32-bit value: 0.9 is saved as 0.8999999761581421.
    return len(stated) == len(schema) and all(
        abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b)) for a, b in zip(stated, schema)
    )


def _integer(usd_type: str, value: Any) -> int:
    """The value as an integer of ``usd_type``, or raise if it is too wide."""

    number = int(value)
    low, high = _INTEGER_RANGE[usd_type]
    if not low <= number <= high:
        raise ValueError(f"{number} is outside the range of {usd_type}")
    return number


def _literal(usd_type: str, value: Any) -> str:
    if usd_type == "bool":
        return "1" if value else "0"
    if usd_type in ("token", "string"):
        if not isinstance(value, str):
            raise TypeError(f"{value!r} is not text")
        text = value.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + text.replace("\n", "\\n").replace("\r", "\\r") + '"'
    if usd_type in _INTEGER_RANGE:
        return str(_integer(usd_type, value))
    if usd_type == "float":
        return repr(float(value))
    if usd_type.startswith(("float", "color", "int")) and not usd_type.endswith("[]"):
        # Each component of an int2, int3 or int4 is itself an int.
        is_int = usd_type.startswith("int")
        items = [_integer("int", item) if is_int else float(item) for item in value]
        size = int(_TYPE_SIZE.search(usd_type)[0])
        if len(items) != size:
            raise ValueError(f"{len(items)} values, not the {size} of a {usd_type}")
        return "(" + ", ".join(repr(item) for item in items) + ")"
    raise TypeError(f"no stored value is applied to a {usd_type} attribute")


def stored_render_setting_lines(stored: Mapping[str, Any]) -> dict[str, list[str]]:
    """USDA attribute lines for the stored settings, per owner prim type.

    The owner is ``"Camera"`` or ``"RenderProduct"``. Left out are a key that
    names no attribute of the installed ovrtx, a value of the wrong kind (the
    ovrtx tools refused both too), a setting of the global RenderSettings
    prim, which ovrtx reads only from the scene root, and an ``omni:rtx:``
    setting stored at the default of the ovrtx schema. A key whose attribute
    exists but whose value the attribute cannot take is reported on stderr and
    left out; the other settings of the scene are still applied. A scene is
    data from elsewhere, so no value of it may stop the scene from opening.
    That holds for ``stored`` itself: the metadata is free-form, so a scene
    can hold anything under the key, and anything but a dictionary is
    reported on stderr and leaves the scene with its defaults.
    """

    lines: dict[str, list[str]] = {"Camera": [], "RenderProduct": []}
    if not isinstance(stored, Mapping):
        print(
            "[stored render settings] the stored render settings of the scene "
            "are not applied: customLayerData['renderSettings'] holds "
            f"{type(stored).__name__} {stored!r}, not a dictionary",
            file=sys.stderr,
        )
        return lines
    attributes = _ovrtx_setting_attributes() if stored else {}
    rejected: list[str] = []
    for key, value in stored.items():
        path = "/" + key.replace(":", "/")
        owner, usd_type, name, tokens = attributes.get(
            path, attributes.get("omni:" + key, (None, "", "", ()))
        )
        if owner not in lines:
            continue
        try:
            if path == "/rtx/post/tonemap/op" and isinstance(value, int):
                if not 0 <= value < len(_KIT_TONEMAP_OPERATORS):
                    raise IndexError(f"{value} is no Kit tone mapper number")
                value = _KIT_TONEMAP_OPERATORS[value]
            if tokens and value not in tokens:
                raise ValueError(f"not one of {', '.join(tokens)}")
            literal = _literal(usd_type, value)
            if not _is_rtx_default(name, usd_type, literal):
                lines[owner].append(f"{usd_type} {name} = {literal}")
        except Exception as error:
            rejected.append(f"{key} = {value!r} ({name}, {usd_type}): {error}")
    if rejected:
        print(
            "[stored render settings] the scene stores a value these ovrtx "
            "settings refuse, so they keep their default: "
            + "; ".join(rejected),
            file=sys.stderr,
        )
    return lines
