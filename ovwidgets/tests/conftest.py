# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Pytest configuration and shared fixtures for the OvGear test suite.

No ovui runtime is required for smoke tests — all fixtures here are pure Python.
"""

import os
import pathlib
import sys

import pytest

# Ensure the ovwidgets project root is on sys.path so editable installs
# aren't required when running pytest from the monorepo root during
# development. After the repo merge, ``__file__`` lives at
# ``<monorepo-root>/ovwidgets/tests/conftest.py``, so
# ``parents[0]=tests/``, ``parents[1]=ovwidgets/``, ``parents[2]=<monorepo-root>/``.
_monorepo_root = pathlib.Path(__file__).resolve().parents[2]
_ovwidgets_project_root = _monorepo_root / "ovwidgets"
if str(_ovwidgets_project_root) not in sys.path:
    sys.path.insert(0, str(_ovwidgets_project_root))

# The data-adapters source lives under the dash-form folder
# ``ovui-data-adapters/`` (Victor's visible-folder requirement). After
# the repo merge, both adapter sub-packages share a single unified
# Python import-package root:
#
#   <monorepo-root>/ovui-data-adapters/ovui_data_adapters/common/
#   <monorepo-root>/ovui-data-adapters/ovui_data_adapters/openusd/
#
# Adding ``<monorepo-root>/ovui-data-adapters`` to ``sys.path`` makes
# both ``ovui_data_adapters.common`` and ``ovui_data_adapters.openusd``
# importable without editable installs. We also mirror the path onto
# ``PYTHONPATH`` so subprocess tests (e.g. the ``no-USD-at-import``
# invariants in ``test_ovwidgets_*_no_usd_at_import.py``) inherit the
# same import resolution. Without the ``PYTHONPATH`` mirror the parent
# process resolves ``ovui_data_adapters`` correctly but the child
# doesn't, and the regression manifests as a misleading "cannot import
# name" error from inside ``ovwidgets.viewport.image_bridge``.
_data_adapters_dist_roots = (
    _monorepo_root / "ovui-data-adapters",
)
for _da_root in _data_adapters_dist_roots:
    if str(_da_root) not in sys.path:
        sys.path.insert(0, str(_da_root))


def _prepend_to_pythonpath(paths: tuple[pathlib.Path, ...]) -> None:
    """Prepend ``paths`` to ``os.environ['PYTHONPATH']`` without
    duplicating existing entries.

    Subprocesses spawned by tests inherit the parent's environment.
    Updating ``sys.path`` alone only affects the parent interpreter; the
    child needs ``PYTHONPATH`` to see the same import roots.
    """
    existing = os.environ.get("PYTHONPATH", "")
    existing_entries = [p for p in existing.split(os.pathsep) if p]
    new_entries = [str(p) for p in paths if str(p) not in existing_entries]
    if not new_entries:
        return
    combined = os.pathsep.join(new_entries + existing_entries)
    os.environ["PYTHONPATH"] = combined


_prepend_to_pythonpath(_data_adapters_dist_roots)


# Issue #35 Step 10 verification gate: pytest prints the summary line and
# then deadlocks during interpreter shutdown. The C++ ``atexit`` chain in
# ovrtx's bundled runtime (``rtx.neuraylib.plugin``, carb) can hang once
# those libraries have been loaded into the test process — a known
# pre-existing bug we cannot fix from ovwidgets.app (ovui/ovrtx are out of scope
# per the issue-35 plan). The wrapper-hook below lets pytest's own
# terminal-reporter wrapper resume first (so the summary line prints), then
# ``os._exit`` skips the remaining atexit handlers so the shell-level
# ``FINAL_RC=$?`` capture actually fires with the real pytest exit code.
_session_exit_status: int = 0


@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session, exitstatus):
    global _session_exit_status
    _session_exit_status = int(exitstatus)
    yield


def pytest_unconfigure(config):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_session_exit_status)


@pytest.fixture
def headless_app():
    """Headless Application instance with singleton cleanup.

    Resets Application._instance before creation so this fixture can be used
    from any test module without conflicting with test_application.py.
    """
    from ovwidgets.app.application import Application
    from ovwidgets.common.selection import SelectionBus

    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    yield app

    app.shutdown()
    Application._instance = None
    SelectionBus._instance = None


# ──────────────────────────────────────────────────────────────────────────────
# Step 11.1 — explicit FakeWidgetServices test fixture
# ──────────────────────────────────────────────────────────────────────────────


class FakeWidgetServices:
    """Explicit (NON-``MagicMock``) implementation of the
    :class:`ovwidgets.common.services.WidgetServices` Protocol.

    Used by widget unit tests that need a deterministic, inspectable
    service container instead of an :class:`Application` singleton.
    Each member is a real object with a real type:

    * :attr:`selection_bus` -- a fresh
      :class:`ovwidgets.common.selection.SelectionBus` instance.
    * :attr:`undo_manager` -- a fresh
      :class:`ovwidgets.common.undo.UndoManager` instance.
    * :meth:`call_later` -- a synchronous stub that immediately
      invokes ``callback`` and returns a fresh
      :class:`ovwidgets.common.scheduler.CallbackHandle` whose
      ``_callback`` slot has been cleared (i.e. ``is_fired`` is True
      after dispatch). Tests that need to observe deferred
      scheduling can still inspect the returned handle.

    A ``MagicMock``-based fixture would silently accept attribute
    typos, fail to enforce the three-member surface, and bypass
    :class:`WidgetServices`'s ``runtime_checkable`` ``isinstance``
    contract. This explicit class refuses both.
    """

    def __init__(self) -> None:
        from ovwidgets.common.scheduler import CallbackHandle  # noqa: F401
        from ovwidgets.common.selection import SelectionBus
        from ovwidgets.common.undo import UndoManager

        self.selection_bus: SelectionBus = SelectionBus()
        self.undo_manager: UndoManager = UndoManager()
        # Public list of every (delay, callback) pair the test code
        # scheduled via ``call_later``. Exposed for assertion clarity
        # in tests that want to verify scheduling behavior.
        self.scheduled_calls: list[tuple[float, "object"]] = []

    def call_later(self, delay_secs: float, callback) -> "object":
        from ovwidgets.common.scheduler import CallbackHandle

        self.scheduled_calls.append((float(delay_secs), callback))
        try:
            callback()
        except Exception:
            # Tests that need to observe a callback exception can
            # wrap the call themselves; the fixture's job is only
            # to deliver synchronous dispatch so widgets that defer
            # via call_later still execute their deferred body.
            pass
        handle = CallbackHandle(due_time=0.0, callback=callback)
        # Mark the handle as fired so ``is_fired`` returns True (the
        # synchronous-dispatch contract).
        handle._callback = None
        return handle


@pytest.fixture
def fake_widget_services() -> FakeWidgetServices:
    """Pytest fixture yielding a fresh :class:`FakeWidgetServices` instance.

    Every test gets its own instance so selection-bus subscribers,
    undo-stack state, and scheduled-call history do not leak between
    tests.
    """
    return FakeWidgetServices()
