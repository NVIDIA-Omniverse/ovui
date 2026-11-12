# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A stage with a valid numeric, string or token default must open and show it."""

from __future__ import annotations

import math
from importlib import import_module

import pytest

from ovui_data_adapters.ovstage import _scene

from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_property_adapter,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes

pytestmark = pytest.mark.requires_ovstage

_SAMPLED = "custom {type} v = {value}\n custom {type} v.timeSamples = {{0: {a}, 1: {b}}}"

_CASES = {
    "camera-shutter": (
        'def Camera "Item"\n{\n double shutter:open = -2\n double shutter:close = 2\n}',
        "shutter:open",
        -2.0,
    ),
    "negative-double": (_SAMPLED.format(type="double", value="-2", a=1, b=2), "v", -2.0),
    "nan-double": (_SAMPLED.format(type="double", value="nan", a=1, b=2), "v", "nan"),
    "inf-double": (_SAMPLED.format(type="double", value="inf", a=1, b=2), "v", math.inf),
    "negative-int": (_SAMPLED.format(type="int", value="-7", a=1, b=2), "v", -7),
    "uint": (_SAMPLED.format(type="uint", value="7", a=1, b=2), "v", 7),
    "uint64": (_SAMPLED.format(type="uint64", value="9", a=1, b=2), "v", 9),
    "uchar": (_SAMPLED.format(type="uchar", value="5", a=1, b=2), "v", 5),
    "string": (_SAMPLED.format(type="string", value='"hello"', a='"a"', b='"b"'), "v", "hello"),
    "token": (_SAMPLED.format(type="token", value='"tok"', a='"a"', b='"b"'), "v", "tok"),
    "token-array": (
        _SAMPLED.format(type="token[]", value='["one", "two"]', a='["a"]', b='["b"]'),
        "v",
        ("one", "two"),
    ),
    "token-array-with-empty": (
        _SAMPLED.format(type="token[]", value='["one", "", "two"]', a='["a"]', b='["b"]'),
        "v",
        ("one", "", "two"),
    ),
}


def _write_scene(tmp_path, prim):
    source = tmp_path / "scene.usda"
    source.write_text(f'#usda 1.0\ndef Xform "World"\n{{\n{prim}\n}}\n', encoding="utf-8")
    return str(source)


def _open_and_read(source, path, attribute):
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    try:
        scene = session.open_stage(source)
        return create_property_adapter(scene, [path]).get_value(attribute)
    finally:
        session.shutdown_scene()


@pytest.mark.parametrize("case", sorted(_CASES))
def test_valid_default_opens_and_reads_back(case, tmp_path):
    body, attribute, expected = _CASES[case]
    path = "/World/Item" if body.startswith("def ") else "/World"
    value = _open_and_read(_write_scene(tmp_path, body), path, attribute)
    if expected == "nan":
        assert isinstance(value, float) and math.isnan(value)
    else:
        assert value == expected


def test_number_default_is_not_looked_up_as_a_token(tmp_path, monkeypatch):
    # An unsigned number is not a token id. No token lookup may be made for it,
    # and it must read back as the number.
    ovstage = import_module("ovstage")
    looked_up: list[int] = []
    path_dictionary = ovstage.PathDictionary

    class RecordingPathDictionary:
        def __init__(self, *args, **kwargs):
            self._inner = path_dictionary(*args, **kwargs)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc_info):
            return self._inner.__exit__(*exc_info)

        def token_to_string(self, token_id):
            looked_up.append(int(token_id))
            return self._inner.token_to_string(token_id)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(ovstage, "PathDictionary", RecordingPathDictionary)
    number = 987654
    prim = "\n".join(
        _SAMPLED.format(type=type_name, value=value, a=1, b=2).replace(" v", f" {name}")
        for type_name, name, value in (
            ("uint", "u", number),
            ("uint64", "w", number + 1),
            ("uchar", "c", 200),
        )
    )
    source = _write_scene(tmp_path, prim)
    assert _open_and_read(source, "/World", "u") == number
    assert _open_and_read(source, "/World", "w") == number + 1
    assert _open_and_read(source, "/World", "c") == 200
    assert looked_up, "the recording stand-in was not used"
    assert not {number, number + 1, 200} & set(looked_up)


@pytest.mark.parametrize("type_name", ["token", "string", "token[]"])
def test_missing_token_text_fails_the_open(type_name, tmp_path, monkeypatch):
    # If the copied text of a token id is lost, the open must fail. The value
    # must not silently become empty text.
    read = _scene._read_populated_extras

    def read_without_text(source, ordinal):
        extras = read(source, ordinal)
        assert extras.token_text, "the scene has no token text to lose"
        extras.token_text.clear()
        return extras

    monkeypatch.setattr(_scene, "_read_populated_extras", read_without_text)
    body, attribute, _ = _CASES[type_name if type_name != "token[]" else "token-array"]
    source = _write_scene(tmp_path, body)
    with pytest.raises(Exception, match="no text was copied for token id"):
        _open_and_read(source, "/World", attribute)
