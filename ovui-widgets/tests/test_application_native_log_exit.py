# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The renderer log that the adapters named is removed when the process ends, unless it is failure evidence.

When the renderer config names no log file, the adapters name one in the temp folder. After #488 each
start of the application left that file behind, and it grows with each rendered frame. The renderer library
writes to it until the process ends, so it is removed only then: by atexit, and before the native fast exit,
which skips atexit. The log is kept when a line of it reported a failure, when an adapter was not shut down
(a renderer that failed to start) or when an unhandled exception ends the process. A log file that the
caller named is kept. A log that cannot be removed is marked, and the next start removes it.

Each check runs a Python process of its own. The child writes the files in place of the renderer.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import render_native_log as nl

_CHILD = textwrap.dedent(
    """
    import os
    import sys
    import tempfile
    from types import SimpleNamespace

    from ovui_data_adapters.common.render_native_log import (
        prepare_native_log, release_native_log, start_native_log,
    )
    from ovui_widgets.app.application import _fast_exit_after_successful_native_shutdown

    mode = sys.argv[3]
    tempfile.tempdir = sys.argv[1]
    owner = SimpleNamespace()
    start_native_log(owner, SimpleNamespace(log_file_path=None))
    named = owner._native_log_path
    kept = prepare_native_log(SimpleNamespace(log_file_path=sys.argv[2]))
    for path in (named, kept):
        with open(path, "w") as handle:
            # Longer than the folder that takes the log's place in "cannot-remove": the reader read the whole log.
            handle.write("[Info] [omni.sensorscheduling] Updated config for sensor\\n" * 200)
    print(named, flush=True)
    if mode == "failure":
        with open(named, "a") as handle:
            handle.write("2026-11-06T21:18:59Z [422ms] [Error] [omni.rtx] Failed load texture file:/scene/red.png\\n")
    if mode != "not-shut-down":
        release_native_log(owner)  # the reader reads the last lines first
    if mode == "cannot-remove":
        os.remove(named)
        os.mkdir(named)
        with open(os.path.join(named, "in-use"), "w"):
            pass
    elif mode == "exception":
        raise RuntimeError("the renderer failed")
    _fast_exit_after_successful_native_shutdown()
    """
)


def _run_child(tmp_path, mode: str, fast_exit: str = "1"):
    env = {key: value for key, value in os.environ.items() if key != "PYTEST_CURRENT_TEST"}
    env["OVUI_WIDGETS_NATIVE_FAST_EXIT"] = fast_exit
    # On Windows the test run adds the Vulkan loader folder (Vulkan_DLL_DIR)
    # with os.add_dll_directory; a new process does not inherit it. The child
    # adds it before it imports the application, which loads native modules.
    preamble = sys.modules["tests.conftest"].CHILD_PROCESS_VULKAN_DLL_PREAMBLE
    return subprocess.run(
        [sys.executable, "-c", preamble + _CHILD, str(tmp_path), str(tmp_path / "caller.log"), mode],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _named(result, tmp_path) -> str:
    named = result.stdout.strip().splitlines()[-1]
    assert os.path.dirname(named) == str(tmp_path)
    return named


@pytest.mark.parametrize("fast_exit", ["1", "0"])
def test_the_renderer_log_that_the_adapter_named_is_removed_when_the_process_ends(tmp_path, fast_exit):
    result = _run_child(tmp_path, "normal", fast_exit)

    assert result.returncode == 0, result
    assert not os.path.exists(_named(result, tmp_path))
    assert (tmp_path / "caller.log").is_file()


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("failure", "the renderer log reported 1 failure(s)"),
        ("not-shut-down", "1 renderer adapter(s) were not shut down"),
        ("exception", "an unhandled exception ends the process"),
    ],
)
def test_the_renderer_log_is_kept_when_it_is_the_evidence_of_a_failure(tmp_path, mode, reason):
    result = _run_child(tmp_path, mode)

    assert result.returncode == (1 if mode == "exception" else 0), result
    named = _named(result, tmp_path)
    assert os.path.isfile(named)
    assert f"the native renderer log {named} is kept: {reason}" in result.stderr


def test_a_renderer_log_that_cannot_be_removed_is_removed_by_the_next_start(tmp_path, monkeypatch):
    result = _run_child(tmp_path, "cannot-remove")

    assert result.returncode == 0, result
    named = _named(result, tmp_path)
    assert os.path.isfile(named + ".remove")
    # The process that held the log open has ended; the log is an ordinary file again.
    os.remove(os.path.join(named, "in-use"))
    os.rmdir(named)
    with open(named, "w") as handle:
        handle.write("[Info] [omni.sensorscheduling] Updated config for sensor\n")
    evidence = tmp_path / "ovui-ovrtx-1.log"
    evidence.write_text("[Error] [omni.rtx] Failed load texture file:/scene/red.png\n")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(nl, "_OWN_LOGS", set())

    nl.prepare_native_log(SimpleNamespace(log_file_path=None))

    assert not os.path.exists(named)
    assert not os.path.exists(named + ".remove")
    assert evidence.is_file()
