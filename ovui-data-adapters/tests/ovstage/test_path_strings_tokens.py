# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Path names stay correct when ovstage frees the memory of its tokens.

A newer ovstage gives each name of a path as a token that shows memory of
one call. ovstage frees that memory after the call and uses it again. A
previous ovstage gives plain integers. These tests use small stand-ins, so
they run with no ovstage installed.
"""

from __future__ import annotations

import ctypes
import gc
import sys
import weakref
from types import SimpleNamespace

import pytest

from ovui_data_adapters.ovstage._native import path_strings


class _Token(ctypes.Structure):
    """A token of a newer ovstage: it shows the memory that holds its number."""

    _fields_ = [("_value", ctypes.c_uint64)]

    @property
    def raw_id(self) -> int:
        return self._value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Token) and self.raw_id == other.raw_id

    def __hash__(self) -> int:
        return hash((_Token, self.raw_id))


class _BorrowedTokenPaths:
    """A path dictionary that gives tokens that show memory of one call."""

    __module__ = "ovstage._src.path_dictionary"

    def __init__(self, paths: list[list[int]]) -> None:
        self._paths = paths
        self.borrowed: list[weakref.ref] = []
        self.kept_after_free = 0
        self.resolved: list[int] = []

    def token_to_string(self, token: _Token) -> str:
        assert isinstance(token, _Token)
        self.resolved.append(token.raw_id)
        return f"n{token.raw_id}"

    def _path_to_string(self, numbers: list[int]) -> str:
        memory = (ctypes.c_uint64 * len(numbers))(*numbers)
        tokens = [_Token.from_buffer(memory, i * 8) for i in range(len(numbers))]
        self.borrowed = [weakref.ref(token) for token in tokens]
        text = "".join("/" + self.token_to_string(token) for token in tokens)
        del tokens
        gc.collect()
        # ovstage frees the memory now; a token that is still kept shows it.
        self.kept_after_free += sum(ref() is not None for ref in self.borrowed)
        return text

    def get_path_strings(self, path_list: str) -> list[str]:
        assert path_list == "all"
        return [self._path_to_string(numbers) for numbers in self._paths]


class _IntegerTokenPaths:
    """A path dictionary of a previous ovstage: tokens are plain integers."""

    def __init__(self, paths: list[list[int]]) -> None:
        self._paths = paths
        self.resolved: list[int] = []

    def token_to_string(self, token: int) -> str:
        assert type(token) is int
        self.resolved.append(token)
        return f"n{token}"

    def get_path_strings(self, path_list: str) -> list[str]:
        assert path_list == "all"
        return [
            "".join("/" + self.token_to_string(number) for number in numbers)
            for numbers in self._paths
        ]


_PATHS = [[1], [1, 2], [1, 2, 3], [1, 2, 4], [1, 5, 6]]
_EXPECTED = ["/n1", "/n1/n2", "/n1/n2/n3", "/n1/n2/n4", "/n1/n5/n6"]


def test_no_borrowed_token_is_kept_after_ovstage_frees_its_memory(monkeypatch):
    monkeypatch.setitem(sys.modules, "ovstage", SimpleNamespace(Token=_Token))
    paths = _BorrowedTokenPaths(_PATHS)

    assert path_strings(paths, "all") == _EXPECTED
    assert paths.kept_after_free == 0
    # The cache still resolves each name only once.
    assert sorted(paths.resolved) == [1, 2, 3, 4, 5, 6]


def test_integer_tokens_of_a_previous_ovstage_are_resolved_once():
    paths = _IntegerTokenPaths(_PATHS)

    assert path_strings(paths, "all") == _EXPECTED
    assert sorted(paths.resolved) == [1, 2, 3, 4, 5, 6]
