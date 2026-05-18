# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Verifies the real ``icon_caches`` registry as populated by
import-time side effects.

Issue #35, Step 3 + Step 4b.

Unlike :mod:`tests.test_icon_caches`, this file does NOT define an
autouse fixture that monkeypatches ``_callbacks`` — the whole point is
to inspect the live registry that's been populated by importing every
module from :data:`EXPECTED_REGISTRATIONS`. The integration tests in
:mod:`tests.test_application_shutdown_integration` rely on the same
import-time registrations (Round 4 F1 / Round 8 F1), so the
collection-time imports below are also a defensive seeding.

Round 3 F7: pytest collects every test file BEFORE running any test,
so the module-level imports below fire during collection — *before*
any autouse fixture in another test file activates. Registrations land
on the real ``icon_caches._callbacks`` list. Re-imports inside test
bodies are no-ops (Python caches imports in :data:`sys.modules`).

Inventory after Step 4b: **21 holders** — 15 dict caches + 1 module
singleton + 2 helper-class singletons + 3 dialog-tracking lists.
"""
from __future__ import annotations

import importlib

import pytest

# ----------------------------------------------------------------------
# Inventory of the 18 Step-3 registrations.
#
# Each tuple is ``(module_path, kind, attribute_or_qualified_name)``.
# ``kind`` selects the dedup-key shape we expect to see in the
# registry; the per-name key-presence test (below) constructs the
# expected string/int key from this tuple.
# ----------------------------------------------------------------------
EXPECTED_REGISTRATIONS = (
    # 15 dict caches.
    ("ovwidgets.content.widget.file_card", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.filter_button", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.browser_bar", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.navigation_model", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.zoom_bar", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.bookmark_button", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.file_browser_delegate", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.search_field", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.content.widget.options_menu", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.common.icon_caches", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.layers.layer_icons", "dict", "_PROVIDER_CACHE"),
    ("ovwidgets.layers.layer_delegate", "dict", "_CHEVRON_PROVIDER_CACHE"),
    ("ovwidgets.viewport.viewport_widget", "dict", "_TOOLBAR_ICON_PROVIDERS"),
    ("ovwidgets.property.window", "dict", "_FILTER_ICON_CACHE"),
    ("ovwidgets.layers.window", "dict", "_LAYERS_FILTER_ICON_CACHE"),
    # 1 module-scope singleton (lazy-init module global).
    ("ovwidgets.app.menu_bar", "singleton", "_LOGO_PROVIDER"),
    # 2 helper-class singletons via stable-string-keyed classmethod.
    (
        "ovwidgets.content.file_importer",
        "classmethod",
        "FileImporterHelper.reset_singleton",
    ),
    (
        "ovwidgets.content.file_exporter",
        "classmethod",
        "FileExporterHelper.reset_singleton",
    ),
    # 3 dialog-tracking lists (Step 4b). Each module's
    # ``_clear_open_dialogs`` callable is registered via
    # ``register(_clear_open_dialogs)`` — id-based dedup.
    (
        "ovwidgets.common.dialogs",
        "module_callable",
        "_clear_open_dialogs",
    ),
    (
        "ovwidgets.common.file_dialogs",
        "module_callable",
        "_clear_open_dialogs",
    ),
    (
        "ovwidgets.content.widget.confirm_overwrite_dialog",
        "module_callable",
        "_clear_open_dialogs",
    ),
)

# Final inventory after Step 4b: 21 holders.
EXPECTED_AFTER_STEP_4B = 21


# ----------------------------------------------------------------------
# Round 3 F7 / Round 8 F1: collection-time imports.
#
# Pytest collects every test file before running any test. These
# top-level imports fire during collection — BEFORE any autouse
# ``_isolated_registry`` fixture in another test file activates, and
# BEFORE any test body's import statement gets a chance to land
# registrations on a temporary monkeypatched ``_callbacks = []``.
# After this block, every Step-3 registration lives on the real
# registry, regardless of which test file pytest schedules first.
# ----------------------------------------------------------------------
for _mod_name, _, _ in EXPECTED_REGISTRATIONS:
    importlib.import_module(_mod_name)

from ovwidgets.common import icon_caches  # noqa: E402 — imports follow the side-effect block

_BASELINE_COUNT = len(icon_caches._callbacks)


# ----------------------------------------------------------------------
# Tests.
# ----------------------------------------------------------------------
def test_baseline_matches_final_inventory_exactly() -> None:
    """Round 4 F3 / Round 7 F4 — exact count, no `>=` slack.

    After importing every Step-3 + Step-4b module exactly once, the
    registry must contain EXACTLY :data:`EXPECTED_AFTER_STEP_4B`
    entries. Any other count means a registration is missing OR a
    duplicate slipped through (which would indicate a dedup regression).
    """
    assert _BASELINE_COUNT == EXPECTED_AFTER_STEP_4B, (
        f"Expected exactly {EXPECTED_AFTER_STEP_4B} registrations after "
        f"importing every Step-3 + Step-4b module, got {_BASELINE_COUNT}. "
        f"Either a registration is missing or duplicates slipped through "
        f"(check the dedup key shape for the offending registrar)."
    )


def test_reimport_does_not_change_count() -> None:
    """Round 3 F7: re-importing already-imported modules must NOT add
    new registrations. A regression that broke the dedup (e.g. moving
    back to bound-method-id keys for classmethods, see Round 2 F5)
    would silently add duplicates here.
    """
    for mod_name, _kind, _attr in EXPECTED_REGISTRATIONS:
        importlib.import_module(mod_name)
    assert len(icon_caches._callbacks) == _BASELINE_COUNT


@pytest.mark.parametrize("mod_name,kind,attr", EXPECTED_REGISTRATIONS)
def test_each_named_holder_exists(mod_name: str, kind: str, attr: str) -> None:
    """Every entry in :data:`EXPECTED_REGISTRATIONS` must point at an
    attribute that actually exists in its module.

    Catches a typo in the inventory list or a refactor that renamed the
    cache without updating the registration / inventory.
    """
    mod = importlib.import_module(mod_name)
    if kind == "dict":
        d = getattr(mod, attr)
        assert isinstance(d, dict), (
            f"{mod_name}.{attr} is not a dict (got {type(d).__name__})"
        )
    elif kind == "singleton":
        # The attribute may legally be None at this point (lazy init),
        # so we only assert that the module exposes it at all.
        assert hasattr(mod, attr), f"{mod_name} has no attribute {attr}"
    elif kind == "classmethod":
        cls_name, method_name = attr.split(".")
        cls = getattr(mod, cls_name)
        method = getattr(cls, method_name)
        assert callable(method), (
            f"{mod_name}.{cls_name}.{method_name} is not callable"
        )
    elif kind == "module_callable":
        # Module-level function (e.g., _clear_open_dialogs) registered
        # via icon_caches.register(...).
        fn = getattr(mod, attr)
        assert callable(fn), f"{mod_name}.{attr} is not callable"
    else:
        raise AssertionError(f"unknown kind {kind!r}")


@pytest.mark.parametrize("mod_name,kind,attr", EXPECTED_REGISTRATIONS)
def test_each_named_key_present_in_registry(
    mod_name: str, kind: str, attr: str
) -> None:
    """Round 3 F7 — strongest possible check: every expected
    registration is present in the registry under its stable key.

    If a registration line was deleted, or the key shape changed, this
    test fails for the affected module.
    """
    expected_key: object
    if kind == "dict":
        # ``register_dict`` keys by ``id(d)``. We look up the dict and
        # use its current id; if the same dict object is in
        # ``sys.modules``, the registration's recorded key matches.
        mod = importlib.import_module(mod_name)
        d = getattr(mod, attr)
        expected_key = id(d)
    elif kind == "singleton":
        mod = importlib.import_module(mod_name)
        owner_name = (
            getattr(mod, "__name__", None) or repr(mod)
        )
        expected_key = f"singleton:{owner_name}.{attr}"
    elif kind == "classmethod":
        mod = importlib.import_module(mod_name)
        cls_name, method_name = attr.split(".")
        cls = getattr(mod, cls_name)
        expected_key = (
            f"clsmethod:{cls.__module__}.{cls.__qualname__}.{method_name}"
        )
    elif kind == "module_callable":
        # ``register(_clear_open_dialogs)`` keys by ``id(_clear_open_dialogs)``.
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, attr)
        expected_key = id(fn)
    else:
        raise AssertionError(f"unknown kind {kind!r}")

    keys_present = [k for (k, _cb) in icon_caches._callbacks]
    assert expected_key in keys_present, (
        f"Registration for {mod_name}.{attr} (kind={kind}) is missing "
        f"from icon_caches. Expected key: {expected_key!r}. "
        f"First 30 keys present: {keys_present[:30]}"
    )
