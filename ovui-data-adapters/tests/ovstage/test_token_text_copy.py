# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A token id with no copied text must fail, not become empty text.

These tests use small stand-ins, so they run with no ovstage installed. The
tests of real stages are in ``test_sampled_default_values.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.ovstage._scene import _PopulatedColumn
from ovui_data_adapters.ovstage._scene import _copied_token_text
from ovui_data_adapters.ovstage._scene import _write_populated_column

_SEMANTIC = SimpleNamespace(TOKEN_ID=2, STRING=5)
_OVSTAGE = SimpleNamespace(AttributeSemantic=_SEMANTIC)


class _Paths:
    def intern_token(self, text):
        return 100 + len(text)


def _column(is_array):
    row = np.array([7], dtype=np.uint64)
    return _PopulatedColumn("v", is_array, 0, 1, {"/World": row}, 1)


def test_copied_text_is_returned():
    assert _copied_token_text({7: "seven"}, 7, "/World", "v") == "seven"


def test_id_zero_is_no_token():
    assert _copied_token_text({}, 0, "/World", "v") == ""


def test_missing_text_is_an_error_with_the_place():
    with pytest.raises(RuntimeError, match=r"token id 7 of /World\.v"):
        _copied_token_text({8: "eight"}, 7, "/World", "v")


@pytest.mark.parametrize(
    ("type_name", "is_array"),
    [("token", False), ("string", False), ("token[]", True)],
)
def test_writing_a_default_with_no_copied_text_fails(type_name, is_array):
    column = _column(is_array)
    with pytest.raises(RuntimeError, match="no text was copied for token id 7"):
        _write_populated_column(
            _OVSTAGE,
            _Paths(),
            column,
            {("/World", "v"): type_name},
            {"/World": np.array([7], dtype=np.uint64)},
            {},
            {},
            target=None,
            ordinal=1,
        )
