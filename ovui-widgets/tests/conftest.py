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

CHILD_PROCESS_VULKAN_DLL_PREAMBLE = r"""
import os as _ovui_test_os

if _ovui_test_os.name == "nt":
    _ovui_test_raw_vulkan_dir = _ovui_test_os.environ.get("Vulkan_DLL_DIR")
    if _ovui_test_raw_vulkan_dir is not None:
        if not _ovui_test_raw_vulkan_dir.strip():
            raise RuntimeError(
                "Vulkan_DLL_DIR is set but empty; expected the directory "
                "containing vulkan-1.dll"
            )
        _ovui_test_vulkan_dir = _ovui_test_os.path.realpath(
            _ovui_test_os.path.expanduser(_ovui_test_raw_vulkan_dir)
        )
        if not _ovui_test_os.path.isdir(_ovui_test_vulkan_dir):
            raise RuntimeError(
                "Vulkan_DLL_DIR does not name an existing directory: "
                f"{_ovui_test_raw_vulkan_dir!r}"
            )
        _ovui_test_vulkan_dll = _ovui_test_os.path.join(
            _ovui_test_vulkan_dir, "vulkan-1.dll"
        )
        if not _ovui_test_os.path.isfile(_ovui_test_vulkan_dll):
            raise RuntimeError(
                f"Vulkan loader DLL is missing: {_ovui_test_vulkan_dll}"
            )
        _ovui_test_add_dll_directory = getattr(
            _ovui_test_os, "add_dll_directory", None
        )
        if not callable(_ovui_test_add_dll_directory):
            raise RuntimeError(
                "callable os.add_dll_directory is required when "
                "Vulkan_DLL_DIR is set"
            )
        _ovui_test_dll_directory_handles = globals().setdefault(
            "_OVUI_TEST_DLL_DIRECTORY_HANDLES", []
        )
        if not _ovui_test_dll_directory_handles:
            try:
                _ovui_test_dll_directory_handles.append(
                    _ovui_test_add_dll_directory(_ovui_test_vulkan_dir)
                )
            except OSError as _ovui_test_exc:
                raise RuntimeError(
                    "could not register Vulkan DLL directory "
                    f"{_ovui_test_vulkan_dir}: {_ovui_test_exc}"
                ) from _ovui_test_exc
"""

import os
import pathlib
import sys

import pytest

# Ensure the ovui-widgets project root is on sys.path so editable installs
# aren't required when running pytest from the monorepo root during
# development. After the repo merge, ``__file__`` lives at
# ``<monorepo-root>/ovui-widgets/tests/conftest.py``, so
# ``parents[0]=tests/``, ``parents[1]=ovui-widgets/``, ``parents[2]=<monorepo-root>/``.
_monorepo_root = pathlib.Path(__file__).resolve().parents[2]
_ovui_widgets_project_root = _monorepo_root / "ovui-widgets"
if str(_ovui_widgets_project_root) not in sys.path:
    sys.path.insert(0, str(_ovui_widgets_project_root))

# The data-adapters source lives under the dash-form folder
# ``ovui-data-adapters/`` (the visible-folder naming requirement). After
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
# invariants in ``test_ovui_widgets_*_no_usd_at_import.py``) inherit the
# same import resolution. Without the ``PYTHONPATH`` mirror the parent
# process resolves ``ovui_data_adapters`` correctly but the child
# doesn't, and the regression manifests as a misleading "cannot import
# name" error from inside ``ovui_widgets.viewport.image_bridge``.
_data_adapters_dist_roots = (
    _monorepo_root / "ovui-data-adapters",
)


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


def _prepend_sys_path(path: pathlib.Path) -> None:
    path_text = str(path)
    if path_text in sys.path:
        sys.path.remove(path_text)
    sys.path.insert(0, path_text)


def _prepend_runtime_usd_python_path() -> None:
    """Prefer an available OpenUSD Python runtime for tests.

    The subprocess clean-exit harness intentionally strips ``usd-build``
    paths from its child, but the parent test process still needs ``pxr``
    to collect and run OpenUSD unit tests in a plain source checkout.
    Prefer an explicit ``USD_ROOT`` when present, then any already-added
    USD Python path, then the standard sibling ``usd-build`` layout used
    by this repository's run guide.
    """
    candidates: list[pathlib.Path] = []
    usd_root = os.environ.get("USD_ROOT", "").strip()
    if usd_root:
        candidates.append(pathlib.Path(usd_root).expanduser() / "lib" / "python")
    for entry in sys.path:
        if not entry:
            continue
        path = pathlib.Path(entry).expanduser()
        if path.name == "python" and path.parent.name == "lib":
            candidates.append(path)
    candidates.append(
        _monorepo_root.parent / "usd-build" / "install" / "lib" / "python"
    )

    for candidate in candidates:
        resolved = candidate.resolve()
        if not (resolved / "pxr").is_dir():
            continue
        _prepend_sys_path(resolved)
        _prepend_to_pythonpath((resolved,))
        return


for _da_root in _data_adapters_dist_roots:
    _prepend_sys_path(_da_root)


_prepend_runtime_usd_python_path()
_prepend_to_pythonpath(_data_adapters_dist_roots)


# Issue #35 Step 10 verification gate: pytest prints the summary line and
# then deadlocks during interpreter shutdown. The C++ ``atexit`` chain in
# ovrtx's bundled runtime (``rtx.neuraylib.plugin``, carb) can hang once
# those libraries have been loaded into the test process — a known
# pre-existing bug we cannot fix from ovui_widgets.app (ovui/ovrtx are out of scope
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


@pytest.fixture(autouse=True)
def _isolate_persistence_state(monkeypatch, tmp_path_factory):
    """Keep every test hermetic against ambient persistence state.

    Two real-world leaks motivated this (both reproduced from a full-suite
    run in a shell prepared for manual QA of the real application):

    * ``OVUI_WIDGETS_SETTINGS_PATH`` inherited from the environment
      re-enables :meth:`Application._settings_persistence_enabled` under
      pytest, so every in-process ``Application()`` loads — and every
      ``shutdown()`` saves — one shared on-disk settings file. Theme,
      ``ui.layout``, recent files, and the rateLimitFrequency written by one
      test then leak into later tests (seven order-dependent failures that
      all pass in isolation). Tests that exercise persistence on purpose
      (e.g. ``test_cli_settings_overrides``) set the variable themselves
      via ``monkeypatch.setenv`` and are unaffected by the delete below.
    * ``Application.shutdown()`` persists the window layout to
      ``~/.ovgear/layout.json`` unconditionally, so any test that shuts an
      application down overwrites the developer's real layout file, and
      ``_restore_layout`` in later tests reads whatever a previous test (or
      the real app) left there. Redirecting ``HOME`` sends both the write
      and the read into a per-test scratch directory.
    """
    monkeypatch.delenv("OVUI_WIDGETS_SETTINGS_PATH", raising=False)
    # X11 discovers its auth cookie via ``$HOME/.Xauthority`` unless
    # ``XAUTHORITY`` is set explicitly. Pin it to the real file BEFORE
    # redirecting HOME, or the interactive-window tests (e.g. the ImGui
    # splitter-style test) lose their X connection and self-skip.
    if "XAUTHORITY" not in os.environ:
        xauthority = os.path.join(os.path.expanduser("~"), ".Xauthority")
        if os.path.exists(xauthority):
            monkeypatch.setenv("XAUTHORITY", xauthority)
    home = tmp_path_factory.mktemp("isolated-home")
    monkeypatch.setenv("HOME", str(home))


@pytest.fixture
def headless_app():
    """Headless Application instance with singleton cleanup.

    Resets Application._instance before creation so this fixture can be used
    from any test module without conflicting with test_application.py.
    """
    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

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
    :class:`ovui_widgets.common.services.WidgetServices` Protocol.

    Used by widget unit tests that need a deterministic, inspectable
    service container instead of an :class:`Application` singleton.
    Each member is a real object with a real type:

    * :attr:`selection_bus` -- a fresh
      :class:`ovui_widgets.common.selection.SelectionBus` instance.
    * :attr:`undo_manager` -- a fresh
      :class:`ovui_widgets.common.undo.UndoManager` instance.
    * :meth:`call_later` -- a synchronous stub that immediately
      invokes ``callback`` and returns a fresh
      :class:`ovui_widgets.common.scheduler.CallbackHandle` whose
      ``_callback`` slot has been cleared (i.e. ``is_fired`` is True
      after dispatch). Tests that need to observe deferred
      scheduling can still inspect the returned handle.

    A ``MagicMock``-based fixture would silently accept attribute
    typos, fail to enforce the three-member surface, and bypass
    :class:`WidgetServices`'s ``runtime_checkable`` ``isinstance``
    contract. This explicit class refuses both.
    """

    def __init__(self) -> None:
        from ovui_widgets.common.scheduler import CallbackHandle  # noqa: F401
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.undo import UndoManager

        self.selection_bus: SelectionBus = SelectionBus()
        self.undo_manager: UndoManager = UndoManager()
        # Public list of every (delay, callback) pair the test code
        # scheduled via ``call_later``. Exposed for assertion clarity
        # in tests that want to verify scheduling behavior.
        self.scheduled_calls: list[tuple[float, "object"]] = []

    def call_later(self, delay_secs: float, callback) -> "object":
        from ovui_widgets.common.scheduler import CallbackHandle

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
