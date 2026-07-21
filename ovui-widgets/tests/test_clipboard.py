# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 35 — in-process clipboard state.

Covers :mod:`ovui_widgets.content.widget.clipboard`:

* :func:`save_to_clipboard` stores a copy of the URL list (caller-side
  mutation does not leak into clipboard state).
* :func:`get_clipboard_urls` returns a fresh copy (callers cannot
  mutate internal state).
* :func:`is_clipboard_cut` reflects the mode passed to
  :func:`save_to_clipboard`.
* :func:`is_path_cut` returns ``True`` only for URLs in a Cut
  selection; Copy selections never flag as cut.
* :func:`clear_clipboard` resets both URL list and cut flag.
* Overwriting the clipboard replaces the previous contents (no
  append / merge behaviour).
* Default mode is Copy (``is_cut=False``).
* An empty URL list is accepted and is equivalent to a clear.

Uses an ``autouse`` fixture to reset module state before every test
so one test's clipboard cannot leak into the next. Tests remain
order-independent, matching the project-wide contract.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ovui_data_adapters.services.content.clipboard import ContentClipboard
from ovui_widgets.content.widget import clipboard

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_clipboard() -> None:
    """Guarantee each test sees an empty clipboard.

    Module state is process-global (that is the whole point — §11),
    so tests must not depend on each other's leftover state. The
    public :func:`clear_clipboard` is the sanctioned reset path.
    """
    clipboard.clear_clipboard()
    yield
    clipboard.clear_clipboard()


# ──────────────────────────────────────────────────────────────────────────────
# save_to_clipboard
# ──────────────────────────────────────────────────────────────────────────────


class TestServiceClipboardBoundary:

    def test_service_instances_are_independent(self) -> None:
        left = ContentClipboard()
        right = ContentClipboard()
        left.save_to_clipboard(["mock://a.usda"], is_cut=True)
        assert left.get_clipboard_urls() == ["mock://a.usda"]
        assert left.is_path_cut("mock://a.usda") is True
        assert right.get_clipboard_urls() == []
        assert right.is_clipboard_cut() is False

    def test_service_clipboard_imports_without_ui_runtime(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from ovui_data_adapters.services.content.clipboard "
                    "import ContentClipboard; "
                    "clip = ContentClipboard(); "
                    "clip.save_to_clipboard(['mock://a.usda'], is_cut=True); "
                    "forbidden = [name for name in sys.modules "
                    "if name == 'ovui_widgets' or name.startswith('ovui_widgets.') "
                    "or name == 'omni' or name.startswith('omni.')]; "
                    "print(clip.get_clipboard_urls(), clip.is_path_cut('mock://a.usda'), forbidden); "
                    "raise SystemExit(1 if forbidden else 0)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            "service ContentClipboard imported UI/runtime modules:\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        assert "True" in proc.stdout


class TestSaveToClipboard:

    def test_stores_urls(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda", "mock://b.usda"])
        assert clipboard.get_clipboard_urls() == [
            "mock://a.usda",
            "mock://b.usda",
        ]

    def test_default_mode_is_copy(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"])
        assert clipboard.is_clipboard_cut() is False

    def test_copy_mode_flag(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=False)
        assert clipboard.is_clipboard_cut() is False

    def test_cut_mode_flag(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        assert clipboard.is_clipboard_cut() is True

    def test_stores_a_copy_of_the_input_list(self) -> None:
        urls = ["mock://a.usda"]
        clipboard.save_to_clipboard(urls)
        # Mutating the caller's list must not affect clipboard state.
        urls.append("mock://b.usda")
        assert clipboard.get_clipboard_urls() == ["mock://a.usda"]

    def test_accepts_empty_list(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        clipboard.save_to_clipboard([])
        assert clipboard.get_clipboard_urls() == []
        # The mode flag is rewritten to the default (Copy) — matches
        # the "empty save is a clear" contract documented on the fn.
        assert clipboard.is_clipboard_cut() is False

    def test_preserves_insertion_order(self) -> None:
        urls = ["mock://c.usda", "mock://a.usda", "mock://b.usda"]
        clipboard.save_to_clipboard(urls)
        assert clipboard.get_clipboard_urls() == urls

    def test_coerces_truthy_is_cut_to_bool(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        # ``is_clipboard_cut`` must return a real bool, not the raw
        # truthy input (callers branch on ``is True`` / ``is False``
        # in a few places — Step 36's Paste-enable gate).
        assert clipboard.is_clipboard_cut() is True


# ──────────────────────────────────────────────────────────────────────────────
# get_clipboard_urls
# ──────────────────────────────────────────────────────────────────────────────


class TestGetClipboardUrls:

    def test_empty_by_default(self) -> None:
        assert clipboard.get_clipboard_urls() == []

    def test_returns_stored_urls(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda", "mock://b.usda"])
        assert clipboard.get_clipboard_urls() == [
            "mock://a.usda",
            "mock://b.usda",
        ]

    def test_returns_fresh_copy_each_call(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"])
        first = clipboard.get_clipboard_urls()
        second = clipboard.get_clipboard_urls()
        # Distinct list objects — callers mutating one must not
        # disturb the other, and neither disturbs internal state.
        assert first is not second
        first.append("mock://z.usda")
        assert clipboard.get_clipboard_urls() == ["mock://a.usda"]


# ──────────────────────────────────────────────────────────────────────────────
# is_clipboard_cut
# ──────────────────────────────────────────────────────────────────────────────


class TestIsClipboardCut:

    def test_false_when_empty(self) -> None:
        assert clipboard.is_clipboard_cut() is False

    def test_false_after_copy(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=False)
        assert clipboard.is_clipboard_cut() is False

    def test_true_after_cut(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        assert clipboard.is_clipboard_cut() is True


# ──────────────────────────────────────────────────────────────────────────────
# is_path_cut
# ──────────────────────────────────────────────────────────────────────────────


class TestIsPathCut:

    def test_false_when_clipboard_empty(self) -> None:
        assert clipboard.is_path_cut("mock://a.usda") is False

    def test_false_for_copy_selection(self) -> None:
        clipboard.save_to_clipboard(
            ["mock://a.usda", "mock://b.usda"], is_cut=False,
        )
        # A Copy selection never flags cut — even though the URL is
        # in the clipboard.
        assert clipboard.is_path_cut("mock://a.usda") is False
        assert clipboard.is_path_cut("mock://b.usda") is False

    def test_true_for_cut_selection_member(self) -> None:
        clipboard.save_to_clipboard(
            ["mock://a.usda", "mock://b.usda"], is_cut=True,
        )
        assert clipboard.is_path_cut("mock://a.usda") is True
        assert clipboard.is_path_cut("mock://b.usda") is True

    def test_false_for_non_member_of_cut_selection(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        # Not in the list → not cut, regardless of mode.
        assert clipboard.is_path_cut("mock://b.usda") is False

    def test_exact_match_required(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        # Substring / prefix / case variants must not match.
        assert clipboard.is_path_cut("mock://A.usda") is False
        assert clipboard.is_path_cut("mock://a.usd") is False
        assert clipboard.is_path_cut("mock://a.usda/child") is False


# ──────────────────────────────────────────────────────────────────────────────
# clear_clipboard
# ──────────────────────────────────────────────────────────────────────────────


class TestClearClipboard:

    def test_empties_url_list(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"])
        clipboard.clear_clipboard()
        assert clipboard.get_clipboard_urls() == []

    def test_resets_cut_flag(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        clipboard.clear_clipboard()
        assert clipboard.is_clipboard_cut() is False

    def test_resets_cut_flag_from_copy(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=False)
        clipboard.clear_clipboard()
        assert clipboard.is_clipboard_cut() is False

    def test_is_path_cut_false_after_clear(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        clipboard.clear_clipboard()
        assert clipboard.is_path_cut("mock://a.usda") is False

    def test_idempotent_on_empty_clipboard(self) -> None:
        # Two consecutive clears must not raise and must leave the
        # clipboard in the same empty state.
        clipboard.clear_clipboard()
        clipboard.clear_clipboard()
        assert clipboard.get_clipboard_urls() == []
        assert clipboard.is_clipboard_cut() is False


# ──────────────────────────────────────────────────────────────────────────────
# Overwrite semantics (Copy → Cut, Cut → Copy, replace, etc.)
# ──────────────────────────────────────────────────────────────────────────────


class TestOverwriteSemantics:

    def test_overwrite_replaces_previous_urls(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda", "mock://b.usda"])
        clipboard.save_to_clipboard(["mock://c.usda"])
        # No append / merge — the second save fully replaces the
        # first. Architecture §11 has no "append" concept.
        assert clipboard.get_clipboard_urls() == ["mock://c.usda"]

    def test_copy_then_cut_switches_mode(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=False)
        assert clipboard.is_clipboard_cut() is False
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        assert clipboard.is_clipboard_cut() is True
        assert clipboard.is_path_cut("mock://a.usda") is True

    def test_cut_then_copy_switches_mode(self) -> None:
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=True)
        assert clipboard.is_clipboard_cut() is True
        clipboard.save_to_clipboard(["mock://a.usda"], is_cut=False)
        assert clipboard.is_clipboard_cut() is False
        assert clipboard.is_path_cut("mock://a.usda") is False

    def test_overwrite_narrows_cut_set(self) -> None:
        clipboard.save_to_clipboard(
            ["mock://a.usda", "mock://b.usda"], is_cut=True,
        )
        assert clipboard.is_path_cut("mock://a.usda") is True
        assert clipboard.is_path_cut("mock://b.usda") is True
        # A subsequent narrower cut drops the old URL from the cut set.
        clipboard.save_to_clipboard(["mock://b.usda"], is_cut=True)
        assert clipboard.is_path_cut("mock://a.usda") is False
        assert clipboard.is_path_cut("mock://b.usda") is True


# ──────────────────────────────────────────────────────────────────────────────
# Import / surface sanity
# ──────────────────────────────────────────────────────────────────────────────


class TestModuleSurface:

    def test_public_functions_exposed(self) -> None:
        # Ensures the five functions named in the plan are importable
        # by attribute from the module — a cheap guard against a
        # future rename accidentally breaking Step 36's wiring.
        for name in (
            "save_to_clipboard",
            "get_clipboard_urls",
            "is_clipboard_cut",
            "is_path_cut",
            "clear_clipboard",
        ):
            assert callable(getattr(clipboard, name)), name

    def test_module_accessible_via_widget_package(self) -> None:
        # The architecture §11 note says :mod:`file_card` imports from
        # :mod:`clipboard` to apply the ``::Cut`` variant (Step 38).
        # The submodule must be reachable from the package.
        from ovui_widgets.content.widget import clipboard as clip_pkg

        assert clip_pkg is clipboard
