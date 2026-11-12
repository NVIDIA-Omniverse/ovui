# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ui.Window and ui.ToolBar look up the Python module that creates them. When that lookup fails, the
window is still created, and the failure is reported with its cause. A normal lookup reports nothing."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest

MESSAGE = "Could not find the Python module that creates this window or toolbar"


def _run_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=180,
        env=dict(os.environ),
    )


class TestWindowOwnerLookup(unittest.TestCase):
    def test_failed_lookup_is_reported_with_its_cause(self):
        done = _run_python(
            """
            import sys
            import omni.ui as ui
            ui.init("owner-lookup", 64, 64)
            normal = ui.Window("normal window")
            original = sys._getframe
            def failing_getframe(*args):
                raise RuntimeError("owner lookup probe")
            sys._getframe = failing_getframe
            try:
                window = ui.Window("window without owner")
                toolbar = ui.ToolBar("toolbar without owner")
            finally:
                sys._getframe = original
            print("created", window.title, toolbar.title, flush=True)
            ui.shutdown()
            """
        )
        output = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, f"stdout:\n{done.stdout}\nstderr (end):\n{done.stderr[-3000:]}")
        self.assertIn("created window without owner toolbar without owner", done.stdout)
        self.assertEqual(output.count(MESSAGE), 2, output[-3000:])
        self.assertEqual(output.count("owner lookup probe"), 2, output[-3000:])


if __name__ == "__main__":
    unittest.main()
