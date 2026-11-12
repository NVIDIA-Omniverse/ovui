# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Upload results of ByteImageProvider as seen from Python.

``set_bytes_data`` and the other setters return True when the backend accepted
the pixels, False when they were refused, and None when there is no GPU
backend (no renderer, which is not a failure). ``inject_upload_failures``
makes the next uploads of one provider fail without a patched renderer, so a
consumer can test its fallback.

OmniUiTest starts the backend, so a good upload must be accepted here. A
refused good upload fails the test with its cause; it is never a skip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest

import omni.ui as ui
from test_base import OmniUiTest

PIXELS = [10, 20, 30, 255] * 16
SIZE = [4, 4]


def _run_python(code: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a new interpreter with the environment of this test."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=180,
        env=dict(os.environ),
    )


class TestByteImageUploadStatus(OmniUiTest):
    def _accepted_provider(self) -> ui.ByteImageProvider:
        provider = ui.ByteImageProvider()
        answer = provider.set_bytes_data(PIXELS, SIZE)
        self.assertIs(answer, True, f"the backend refused a good upload: {provider.last_upload_result.cause}")
        return provider

    async def test_injected_failure_is_reported_and_keeps_the_old_image(self):
        provider = self._accepted_provider()
        other = self._accepted_provider()
        self.assertEqual(provider.upload_failure_count, 0)
        self.assertTrue(provider.is_reference_valid)

        provider.inject_upload_failures(2)
        self.assertIs(other.set_bytes_data(PIXELS, SIZE), True, "the hook of one provider does not reach another")
        self.assertIs(provider.set_bytes_data(PIXELS, SIZE), False)
        self.assertIs(provider.set_bytes_data_from_gpu(0x1000, SIZE), False)
        self.assertEqual(provider.upload_failure_count, 2)
        self.assertEqual(other.upload_failure_count, 0)
        self.assertTrue(provider.is_reference_valid, "the previous pixels stay")
        result = provider.last_upload_result
        self.assertFalse(result.accepted)
        self.assertFalse(bool(result))
        self.assertEqual(result.status, ui.UploadStatus.FAILED)
        self.assertEqual(result.upload_id, 0)
        self.assertIn("injectUploadFailures", result.cause)

        # The hook is used up: the next upload goes to the backend again.
        self.assertIs(provider.set_bytes_data(PIXELS, SIZE), True)
        self.assertEqual(provider.inject_upload_failures(0), 0)

    async def test_accepted_upload_has_an_id_and_completion(self):
        provider = self._accepted_provider()
        result = provider.last_upload_result
        self.assertTrue(result.accepted)
        self.assertIn(result.status, (ui.UploadStatus.ENQUEUED, ui.UploadStatus.COMPLETE))
        self.assertGreater(result.upload_id, 0)
        self.assertIsNone(result.cause)
        self.assertLessEqual(provider.completed_upload_id, result.upload_id)

    async def test_events_report_a_failure_until_unsubscribed(self):
        provider = ui.ByteImageProvider()
        events = []
        token = provider.subscribe_upload_events(lambda kind, upload_id, req, got: events.append((kind, upload_id)))
        self.assertNotEqual(token, 0)

        provider.inject_upload_failures(1)
        provider.set_bytes_data(PIXELS, SIZE)
        self.assertEqual(events, [(ui.ByteImageUploadEventKind.FAILED, 0)])

        provider.unsubscribe_upload_events(token)
        provider.inject_upload_failures(1)
        provider.set_bytes_data(PIXELS, SIZE)
        self.assertEqual(len(events), 1)

    async def test_input_that_cannot_be_read_is_a_recorded_refusal(self):
        provider = self._accepted_provider()
        events = []
        provider.subscribe_upload_events(lambda kind, upload_id, req, got: events.append(kind))
        cases = (
            ([], "empty"),
            ([[]], "empty"),
            ([None], "not int, float or pixel tuples"),
            ([["a"]], "not int or float"),
        )
        for data, cause in cases:
            with self.subTest(data=data):
                failures = provider.upload_failure_count
                self.assertIs(provider.set_bytes_data(data, SIZE), False)
                result = provider.last_upload_result
                self.assertFalse(result.accepted)
                self.assertEqual(result.status, ui.UploadStatus.FAILED)
                self.assertIn(cause, result.cause)
                self.assertEqual(provider.upload_failure_count, failures + 1)
                self.assertEqual(events[-1], ui.ByteImageUploadEventKind.FAILED)
        self.assertTrue(provider.is_reference_valid, "the previous pixels stay")

    async def test_input_that_does_not_fit_its_sizes_is_a_recorded_refusal(self):
        provider = self._accepted_provider()
        events = []
        provider.subscribe_upload_events(lambda kind, upload_id, req, got: events.append(kind))
        cases = (
            ("too few bytes", lambda: provider.set_bytes_data(PIXELS[:4], SIZE), "do not match"),
            ("zero size", lambda: provider.set_bytes_data(PIXELS, [0, 0]), "do not match"),
            ("ragged pixels", lambda: provider.set_bytes_data([[1, 2, 3, 4], [5, 6]], [1, 2]), "same number"),
            ("null GPU pointer", lambda: provider.set_bytes_data_from_gpu(0, SIZE), "not valid"),
        )
        for name, call, cause in cases:
            failures = provider.upload_failure_count
            self.assertIs(call(), False, name)
            result = provider.last_upload_result
            self.assertEqual(result.status, ui.UploadStatus.FAILED, name)
            self.assertIn(cause, result.cause, name)
            self.assertEqual(provider.upload_failure_count, failures + 1, name)
            self.assertEqual(events[-1], ui.ByteImageUploadEventKind.FAILED, name)
        with self.assertRaises(ValueError):
            provider.set_bytes_data(PIXELS[:4], SIZE, strict=True)
        self.assertTrue(provider.is_reference_valid, "the previous pixels stay")

    async def test_a_failing_subscriber_does_not_undo_the_upload(self):
        provider = ui.ByteImageProvider()
        seen = []
        reported = []

        def failing(*event):
            raise RuntimeError("subscriber bug")

        provider.subscribe_upload_events(failing)
        provider.subscribe_upload_events(lambda kind, *rest: seen.append(kind))
        previous_hook = sys.unraisablehook
        sys.unraisablehook = reported.append
        try:
            answer = provider.set_bytes_data(PIXELS, SIZE)
        finally:
            sys.unraisablehook = previous_hook
        self.assertIs(answer, True, f"the backend refused a good upload: {provider.last_upload_result.cause}")
        self.assertIn(ui.ByteImageUploadEventKind.ENQUEUED, seen, "the other subscriber gets the event")
        self.assertTrue(reported, "the exception of the subscriber is reported")
        self.assertIsInstance(reported[0].exc_value, RuntimeError)

    async def test_a_subscription_kept_until_exit_does_not_crash_the_exit(self):
        done = _run_python(
            """
            import omni.ui as ui
            ui.init("subscription-at-exit", 64, 64)
            provider = ui.ByteImageProvider()
            provider.subscribe_upload_events(lambda *event: None)
            print("answer", provider.set_bytes_data([10, 20, 30, 255] * 16, [4, 4]))
            ui.shutdown()
            """
        )
        self.assertEqual(done.returncode, 0, f"stdout:\n{done.stdout}\nstderr (end):\n{done.stderr[-3000:]}")
        self.assertIn("answer True", done.stdout)

    async def test_no_backend_is_not_a_failure(self):
        done = _run_python(
            """
            import json
            import omni.ui as ui
            provider = ui.ByteImageProvider()
            events = []
            provider.subscribe_upload_events(lambda kind, *rest: events.append(str(kind)))
            answer = provider.set_bytes_data([10, 20, 30, 255] * 16, [4, 4])
            result = provider.last_upload_result
            print(json.dumps({
                "has_backend": ui.ByteImageProvider.has_upload_backend(),
                "answer": answer,
                "status": str(result.status),
                "accepted": result.accepted,
                "failures": provider.upload_failure_count,
                "events": events,
            }))
            """
        )
        self.assertEqual(done.returncode, 0, f"stdout:\n{done.stdout}\nstderr (end):\n{done.stderr[-3000:]}")
        report = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(
            report,
            {
                "has_backend": False,
                "answer": None,
                "status": str(ui.UploadStatus.NO_BACKEND),
                "accepted": False,
                "failures": 0,
                "events": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
