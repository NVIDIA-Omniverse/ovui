# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The application exits at once with status 1 when a task did not stop in its time limit.

Review of #854: at shutdown the OpenUSD renderer adapter waits for the step
that builds the scene again after a stage edit, now with a time limit. When
the limit runs out, the step still runs; the ordinary end of Python would
wait for it again, with no limit. The application prints the failure and
ends the process with status 1 instead.

Each check runs a Python process of its own. A thread that never ends stands
for the work that the ordinary end of Python would wait for.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

_CHILD = textwrap.dedent(
    """
    import os
    import sys
    import threading
    import time

    from ovui_data_adapters.common.render_diagnostics import BackgroundTaskStuckError
    from ovui_widgets.app.application import _exit_at_once_when_a_task_is_stuck

    threading.Thread(target=lambda: time.sleep(3600), name="never-ends").start()
    mode = sys.argv[1]
    if mode == "stuck":
        error = BackgroundTaskStuckError("the renderer step did not end in 120 s at shutdown")
    elif mode == "stuck-cause":
        error = RuntimeError("the viewport could not be destroyed")
        error.__cause__ = BackgroundTaskStuckError("the renderer step did not end")
    else:
        error = RuntimeError("the viewport could not be destroyed")
    _exit_at_once_when_a_task_is_stuck(error)
    print("the helper returned", flush=True)
    os._exit(0)
    """
)


def _run_child(mode: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "PYTEST_CURRENT_TEST"}
    env.pop("OVUI_WIDGETS_NATIVE_FAST_EXIT", None)
    # On Windows the test run adds the Vulkan loader folder (Vulkan_DLL_DIR)
    # with os.add_dll_directory; a new process does not inherit it. The child
    # adds it before it imports the application, which loads native modules.
    preamble = sys.modules["tests.conftest"].CHILD_PROCESS_VULKAN_DLL_PREAMBLE
    return subprocess.run(
        [sys.executable, "-c", preamble + _CHILD, mode],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_task_that_did_not_stop_in_its_time_limit_ends_the_process_at_once_with_status_1():
    result = _run_child("stuck")

    assert result.returncode == 1, result
    assert "the helper returned" not in result.stdout
    assert "BackgroundTaskStuckError: the renderer step did not end in 120 s at shutdown" in result.stderr
    assert "a task did not stop in its time limit at shutdown" in result.stderr


def test_a_stuck_task_that_caused_the_shutdown_error_also_ends_the_process():
    result = _run_child("stuck-cause")

    assert result.returncode == 1, result
    assert "BackgroundTaskStuckError: the renderer step did not end" in result.stderr


def test_another_shutdown_error_keeps_the_ordinary_exit():
    result = _run_child("other")

    assert result.returncode == 0, result
    assert "the helper returned" in result.stdout
    assert "time limit" not in result.stderr
