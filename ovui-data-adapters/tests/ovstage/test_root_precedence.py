# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVRTX_ROOT and OVSTAGE_ROOT select their copy over one already on the path.

These tests build real small packages on disk, so they exercise the real
import order. Mocked imports cannot show the path-order or link problems.
"""

from __future__ import annotations

import sys

import pytest

from ovui_data_adapters.common import ovrtx_import as ovrtx_resolver
from ovui_data_adapters.ovstage import runtime_import as ovstage_resolver


def _make_package(directory, product, origin):
    package = directory / product
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"origin = {origin!r}\nfrom .child import origin as child_origin\n"
    )
    (package / "child.py").write_text(f"origin = {origin!r}\n")


def _link_directory(link, target):
    """Make ``link`` reach the directory ``target`` through the filesystem.

    Windows holds a directory symlink back from an ordinary account, which has
    neither Developer Mode nor SeCreateSymbolicLinkPrivilege. That account can
    still make a junction, and an import resolves through it the same way.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def _forget(product):
    for name in list(sys.modules):
        if name == product or name.startswith(product + "."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _fresh_resolvers():
    ovrtx_resolver.reset_ovrtx_import_cache()
    ovstage_resolver.reset_ovstage_import_cache()


def _resolve(product, root, monkeypatch):
    _forget(product)
    ovrtx_resolver.reset_ovrtx_import_cache()
    if product == "ovrtx":
        monkeypatch.setenv(ovrtx_resolver.OVRTX_ROOT_ENV, str(root))
        return ovrtx_resolver.import_ovrtx()
    monkeypatch.setenv(ovstage_resolver.OVSTAGE_ROOT_ENV, str(root))
    return ovstage_resolver.resolve_ovstage_runtime_module("ovstage")


@pytest.mark.parametrize("product", ["ovrtx", "ovstage"])
def test_set_root_wins_over_copy_earlier_on_sys_path(product, tmp_path, monkeypatch):
    installed = tmp_path / "installed"
    selected = tmp_path / "selected"
    _make_package(installed, product, "installed")
    _make_package(selected, product, "selected")
    # The installed copy is already ahead of the selected root on the path.
    monkeypatch.syspath_prepend(str(selected))
    monkeypatch.syspath_prepend(str(installed))

    result = _resolve(product, selected, monkeypatch)
    _forget(product)

    assert result.available, result.error
    assert result.module.origin == "selected"


def test_ovrtx_root_does_not_keep_a_child_from_another_copy(tmp_path, monkeypatch):
    installed = tmp_path / "installed"
    selected = tmp_path / "selected"
    _make_package(installed, "ovrtx", "installed")
    _make_package(selected, "ovrtx", "selected")
    # Load the installed copy and its child first, with no root set.
    monkeypatch.syspath_prepend(str(installed))
    _forget("ovrtx")
    ovrtx_resolver.reset_ovrtx_import_cache()
    import ovrtx  # noqa: F401

    assert ovrtx.child_origin == "installed"

    # Resolve with the root set, but do not clear the loaded child here: the
    # resolver itself must drop the stale child from the installed copy.
    monkeypatch.setenv(ovrtx_resolver.OVRTX_ROOT_ENV, str(selected))
    ovrtx_resolver.reset_ovrtx_import_cache()
    result = ovrtx_resolver.import_ovrtx()
    module = result.module
    _forget("ovrtx")

    assert result.available, result.error
    assert module.origin == "selected"
    assert module.child_origin == "selected"


@pytest.mark.parametrize("product", ["ovrtx", "ovstage"])
def test_set_root_accepts_a_linked_package(product, tmp_path, monkeypatch):
    real = tmp_path / "real"
    selected = tmp_path / "selected"
    _make_package(real, product, "linked")
    selected.mkdir()
    _link_directory(selected / product, real / product)

    result = _resolve(product, selected, monkeypatch)
    _forget(product)

    assert result.available, result.error
    assert result.module.origin == "linked"
