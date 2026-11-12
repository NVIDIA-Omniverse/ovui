# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The renderer slot of native frame pacing.

ovui owns the image slots, the upload and the present worker, and calls a
renderer function table for every renderer operation. It never calls a
renderer itself, so these tests build the table in Python with ``ctypes``.

On a build with the Vulkan coordinator, installing a table makes ovui report
the capability and removing it takes the capability away. On a build without
Vulkan the coordinator does not exist, so a table changes nothing. On every
build a table ovui cannot read is refused at installation, with an error,
instead of being accepted and called later from a worker thread.
"""

import ctypes
import subprocess
import sys
import threading
import unittest

import omni.ui as ui

CAPSULE_NAME = b"omni.ui.native_frame_pacing_hooks"
HOOKS_VERSION = 3

_PyCapsule_New = ctypes.pythonapi.PyCapsule_New
_PyCapsule_New.restype = ctypes.py_object
_PyCapsule_New.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]


class NativeFramePacingHooks(ctypes.Structure):
    """Same layout as omni::ui::standalone::NativeFramePacingHooks."""

    _fields_ = [
        ("structSize", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("openRenderer", ctypes.c_void_p),
        ("pauseRenderWorker", ctypes.c_void_p),
        ("resumeRenderWorker", ctypes.c_void_p),
        ("closeRenderer", ctypes.c_void_p),
        ("shutdownWorker", ctypes.c_void_p),
        ("readRendererInfo", ctypes.c_void_p),
        ("lastError", ctypes.c_void_p),
        ("queryCapabilities", ctypes.c_void_p),
        ("cancel", ctypes.c_void_p),
    ]


class NativeFramePacingCapabilities(ctypes.Structure):
    """Same layout as omni::ui::standalone::NativeFramePacingCapabilities."""

    _fields_ = [
        ("structSize", ctypes.c_uint32),
        ("operatesOffUiThread", ctypes.c_uint32),
        ("usesOwnQueue", ctypes.c_uint32),
        ("presentReadsImages", ctypes.c_uint32),
    ]


_QUERY_CAPABILITIES = ctypes.CFUNCTYPE(None, ctypes.POINTER(NativeFramePacingCapabilities))
_CANCEL = ctypes.CFUNCTYPE(None, ctypes.c_uint64)


_FUNCTION_FIELDS = tuple(name for name, _ in NativeFramePacingHooks._fields_[2:])
# Any non-null address is enough: these tests never start a session, so ovui
# only reads the header and checks that every entry is filled.
_PLACEHOLDER = ctypes.cast(_PyCapsule_New, ctypes.c_void_p).value


def _table(version=HOOKS_VERSION, struct_size=None, missing=()):
    hooks = NativeFramePacingHooks()
    hooks.structSize = (
        ctypes.sizeof(NativeFramePacingHooks) if struct_size is None else struct_size
    )
    hooks.version = version
    for name in _FUNCTION_FIELDS:
        setattr(hooks, name, None if name in missing else _PLACEHOLDER)
    return hooks


def _capsule(hooks):
    return _PyCapsule_New(ctypes.byref(hooks), CAPSULE_NAME, None)


def _set(capsule):
    ui._ui._set_native_frame_pacing_hooks(capsule)


def _status():
    return ui.get_frame_pacing_status()


def _coordinator_built():
    """True when this build has the Vulkan coordinator behind the slot.

    Asked with the slot empty: the coordinator then names the missing hooks,
    while a build without Vulkan names the missing backend.
    """

    _set(None)
    return _status()["status_reason"] != "backend_unavailable"


@unittest.skipUnless(
    hasattr(getattr(ui, "_ui", None), "_set_native_frame_pacing_hooks"),
    "this build has no standalone frame-pacing slot",
)
class NativeFramePacingHooksTest(unittest.TestCase):
    def tearDown(self):
        _set(None)

    def test_a_complete_table_makes_pacing_supported_where_the_coordinator_exists(self):
        coordinator = _coordinator_built()
        hooks = _table()
        _set(_capsule(hooks))
        status = _status()
        if coordinator:
            self.assertTrue(status["supported"])
        else:
            # Without Vulkan there is nothing for a renderer table to drive.
            self.assertFalse(status["supported"])
            self.assertEqual(status["status_reason"], "backend_unavailable")

    def test_removing_the_table_takes_the_capability_away(self):
        coordinator = _coordinator_built()
        hooks = _table()
        _set(_capsule(hooks))
        _set(None)
        status = _status()
        self.assertFalse(status["supported"])
        self.assertEqual(
            status["status_reason"],
            "hooks_unavailable" if coordinator else "backend_unavailable",
        )

    def test_an_unreadable_table_is_refused_with_an_error(self):
        cases = {"another version": _table(version=HOOKS_VERSION + 1),
                 "too small": _table(struct_size=8)}
        for name in _FUNCTION_FIELDS:
            cases[f"no {name}"] = _table(missing=(name,))
        for label, hooks in cases.items():
            with self.subTest(table=label):
                with self.assertRaises(ValueError):
                    _set(_capsule(hooks))
                # A refused table leaves the slot empty.
                self.assertFalse(_status()["supported"])

    def test_a_refused_table_also_removes_the_previous_one(self):
        coordinator = _coordinator_built()
        good = _table()
        _set(_capsule(good))
        bad = _table(version=HOOKS_VERSION + 1)
        with self.assertRaises(ValueError):
            _set(_capsule(bad))
        status = _status()
        self.assertFalse(status["supported"])
        if coordinator:
            self.assertEqual(status["status_reason"], "hooks_unavailable")

    def test_starting_without_a_table_fails_with_a_reason(self):
        coordinator = _coordinator_built()
        token = ui._ui._native_frame_pacing_start(
            1, "", 32, 0, 16, None, "/Render/Product", "/Camera", 64, 64
        )
        self.assertEqual(int(token or 0), 0)
        status = _status()
        if coordinator:
            self.assertEqual(status["status_reason"], "hooks_unavailable")
            self.assertIn("renderer hooks", status["last_error"])
        else:
            self.assertEqual(status["status_reason"], "backend_unavailable")

    def test_a_missing_frame_source_is_reported_one_time(self):
        # A new process, so no earlier test has reported it yet. Another
        # error comes between the starts: it must not bring the report back.
        script = (
            "import omni.ui as ui\n"
            "def start():\n"
            "    ui._ui._native_frame_pacing_start("
            "1, '', 32, 0, 16, None, '/Render/Product', '/Camera', 64, 64)\n"
            "start()\n"
            "ui._ui._set_present_rate(30.0)\n"
            "start()\n"
            "start()\n"
            "print(ui.get_frame_pacing_status()['status_reason'])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        if result.stdout.strip() == "backend_unavailable":
            return
        self.assertEqual(result.stdout.strip(), "hooks_unavailable")
        self.assertEqual(result.stderr.count("has no renderer hooks installed"), 1, result.stderr)

    def test_a_frame_source_without_a_capability_starts_no_threads(self):
        coordinator = _coordinator_built()
        rules = {"operatesOffUiThread": "24.8", "usesOwnQueue": "24.9", "presentReadsImages": "24.10"}
        for missing in ("operatesOffUiThread", "usesOwnQueue", "presentReadsImages"):
            with self.subTest(missing=missing):

                def query(output, missing=missing):
                    output.contents.operatesOffUiThread = int(missing != "operatesOffUiThread")
                    output.contents.usesOwnQueue = int(missing != "usesOwnQueue")
                    output.contents.presentReadsImages = int(missing != "presentReadsImages")

                callback = _QUERY_CAPABILITIES(query)
                hooks = _table()
                hooks.queryCapabilities = ctypes.cast(callback, ctypes.c_void_p).value
                _set(_capsule(hooks))
                token = ui._ui._native_frame_pacing_start(
                    1, "", 32, 0, 16, None, "/Render/Product", "/Camera", 64, 64
                )
                self.assertEqual(int(token or 0), 0)
                status = _status()
                if coordinator:
                    self.assertEqual(status["status_reason"], "frame_source_capability")
                    self.assertFalse(status["active"])
                    # Rule 24.15: the report names the check that failed, and only that one.
                    for name, rule in rules.items():
                        named = f"(rule {rule})" in status["last_error"]
                        self.assertEqual(named, name == missing, status["last_error"])
                _set(None)

    def test_a_cancel_reaches_the_frame_source_from_another_thread(self):
        received = []
        callback = _CANCEL(received.append)
        hooks = _table()
        hooks.cancel = ctypes.cast(callback, ctypes.c_void_p).value
        _set(_capsule(hooks))
        sent = []
        worker = threading.Thread(target=lambda: sent.append(ui._ui._native_frame_pacing_cancel(42)))
        worker.start()
        worker.join(timeout=10)
        self.assertEqual(sent, [True])
        self.assertEqual(received, [42])
        _set(None)
        self.assertFalse(ui._ui._native_frame_pacing_cancel(42))

    def test_the_old_version_key_stays_next_to_the_new_one(self):
        status = _status()
        if "renderer_version" in status:
            self.assertEqual(status["ovrtx_version"], status["renderer_version"])
        else:
            self.assertEqual(status["status_reason"], "backend_unavailable")


if __name__ == "__main__":
    unittest.main()
