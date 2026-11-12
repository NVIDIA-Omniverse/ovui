# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A frame that ovui refused must not count as presented.

ovui keeps the previous pixels when it refuses an upload. The viewport used to
ignore the answer and tell the renderer that the frame was presented, so the
presented sequence moved on while the screen did not. The failure hook of one
provider, ``inject_upload_failures``, makes the refusal reproducible.

The tests start the ovui backend, so the first upload of every bridge must be
accepted; every assertion runs. Without a GPU backend there is no renderer:
then the viewport must present its frames as before, which a separate process
checks.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from types import SimpleNamespace as NS

import numpy as np
import omni.ui as ui
import pytest
from ovui_widgets.viewport.image_bridge import ImageBridge
from ovui_widgets.viewport.viewport_widget import ViewportWidget

from tests._vulkan_device import missing_vulkan_device


def _nvidia_gpu_listed():
    """Whether this host shows an NVIDIA GPU to the driver tools."""
    if os.path.exists("/dev/nvidia0"):
        return True
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return False
    try:
        done = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "GPU" in done.stdout


@pytest.fixture(scope="module")
def backend():
    """Start the ovui backend once. Skip only when this host has no hardware for it.

    A start that fails on a host with a Vulkan device, or with an NVIDIA GPU
    that the driver tools list, is a broken renderer start and fails the test.
    When the host cannot be told apart, the test fails too.
    """
    if ui.ByteImageProvider.has_upload_backend():
        return
    try:
        ui.init("rejected-upload", 64, 64)
    except RuntimeError as exc:
        absent = missing_vulkan_device()
        if not absent:
            pytest.fail(f"ui.init() failed on a host with a Vulkan device: {exc}")
        if _nvidia_gpu_listed():
            pytest.fail(f"ui.init() failed on a host with an NVIDIA GPU ({absent}): {exc}")
        pytest.skip(f"no hardware for the ovui backend: {absent}")
    assert ui.ByteImageProvider.has_upload_backend(), "ui.init() registered no GPU backend"


def _accepted_bridge():
    """A bridge whose first (blank) upload the backend accepted."""
    bridge = ImageBridge(4, 4)
    result = bridge.provider.last_upload_result
    assert result.accepted, f"the backend refused the first upload of the bridge: {result.cause}"
    return bridge


def _viewport(bridge, marks, released):
    renderer = NS(
        mark_render_frame_presented=lambda meta: marks.append(meta),
        release_render_frame=lambda meta: released.append(meta),
    )
    return NS(
        _bridge=bridge,
        _renderer=renderer,
        _async_render_dt=0.016,
        _scene_view=None,
        _viewport_hooks=NS(update_frame=lambda camera: None),
        _transform_manipulator=None,
        _async_resize_refresh_was_pending=False,
        _retry_selection_highlight_after_render=lambda: None,
        _record_fps_sample=lambda dt: None,
        _refresh_hud=lambda: None,
        _maybe_invalidate_gizmo_for_scale=lambda: None,
    )


def _metadata():
    return NS(extent=(4, 4), view_matrix=np.eye(4), projection_matrix=np.eye(4))


@pytest.mark.usefixtures("backend")
class TestViewportRejectedUpload:
    def test_refused_frame_is_not_marked_presented(self):
        bridge = _accepted_bridge()
        marks, released = [], []
        viewport = _viewport(bridge, marks, released)
        frame = np.full((4, 4, 4), 255, dtype=np.uint8)
        metadata = _metadata()

        bridge.provider.inject_upload_failures(1)
        presented = ViewportWidget._present_async_render_frame_impl(viewport, frame, metadata)

        assert presented is False
        assert not bridge.provider.last_upload_result.accepted
        assert bridge.provider.upload_failure_count == 1
        assert marks == [], "a refused frame must not be marked presented"
        assert released == [metadata], "the refused frame goes back to the renderer"
        assert not hasattr(viewport, "_last_presented_frame_metadata"), "no metadata for a refused frame"

    def test_accepted_frame_is_still_marked_presented(self):
        bridge = _accepted_bridge()
        marks, released = [], []
        viewport = _viewport(bridge, marks, released)
        metadata = _metadata()

        presented = ViewportWidget._present_async_render_frame_impl(
            viewport, np.full((4, 4, 4), 255, dtype=np.uint8), metadata
        )

        assert presented is True
        assert bridge.provider.last_upload_result.accepted
        assert marks == [metadata]
        assert released == []


@pytest.mark.usefixtures("backend")
class TestViewportRejectedPresentation:
    """Poll progress, the exported image and the metadata stay truthful after a refusal."""

    def _setup(self):
        bridge = _accepted_bridge()
        marks, released = [], []
        viewport = _viewport(bridge, marks, released)
        old = np.zeros((4, 4, 4), dtype=np.uint8)
        old[:] = [255, 0, 0, 255]
        assert bridge.update(old) is True, f"the backend refused a good frame: {bridge.provider.last_upload_result.cause}"
        viewport._last_image_frame = old
        viewport._last_presented_frame_metadata = "old"
        viewport._render_generation = 1
        viewport._render_viewport_id = "v"
        meta = NS(generation=1, extent=(4, 4), view_matrix=np.eye(4), projection_matrix=np.eye(4))
        new = np.full((4, 4, 4), 255, dtype=np.uint8)
        viewport._renderer.poll_render_frame = lambda key: NS(image=new, metadata=meta)
        viewport._present_async_render_frame = lambda image, metadata: (
            ViewportWidget._present_async_render_frame_impl(viewport, image, metadata)
        )
        return viewport, marks, released, old, new, meta

    def test_refused_frame_is_not_progress_and_not_exported(self):
        viewport, marks, released, old, new, meta = self._setup()
        viewport._bridge.provider.inject_upload_failures(1)
        assert ViewportWidget.poll_render(viewport) is False
        assert marks == []
        assert released == [meta]
        assert np.array_equal(ViewportWidget.get_presentation_image(viewport), old)
        assert viewport._last_presented_frame_metadata == "old"

    def test_accepted_frame_is_progress_and_exported(self):
        viewport, marks, released, old, new, meta = self._setup()
        assert ViewportWidget.poll_render(viewport) is True
        assert marks == [meta]
        assert np.array_equal(ViewportWidget.get_presentation_image(viewport), new)
        assert viewport._last_presented_frame_metadata is meta


@pytest.mark.usefixtures("backend")
class TestViewportRefusedInitialUpload:
    """When the very first upload is refused, nothing was presented: no image and no metadata."""

    def test_refused_initial_frames_are_not_the_presentation(self, monkeypatch):
        make_provider = ui.ByteImageProvider

        def provider_that_refuses_its_first_upload():
            provider = make_provider()
            provider.inject_upload_failures(1)
            return provider

        # The real bridge constructor runs; its blank first upload is refused.
        monkeypatch.setattr(ui, "ByteImageProvider", provider_that_refuses_its_first_upload)
        bridge = ImageBridge(4, 4)
        monkeypatch.undo()
        assert bridge.provider.last_upload_result.status == ui.UploadStatus.FAILED
        assert not bridge.provider.is_reference_valid
        marks, released = [], []
        viewport = _viewport(bridge, marks, released)
        viewport._last_image_frame = None
        viewport._render_generation = 1
        viewport._render_viewport_id = "v"
        meta = NS(generation=1, extent=(4, 4), view_matrix=np.eye(4), projection_matrix=np.eye(4))
        new = np.full((4, 4, 4), 255, dtype=np.uint8)
        viewport._renderer.poll_render_frame = lambda key: NS(image=new, metadata=meta)
        viewport._present_async_render_frame = lambda image, metadata: (
            ViewportWidget._present_async_render_frame_impl(viewport, image, metadata)
        )
        bridge.provider.inject_upload_failures(1)
        assert ViewportWidget.poll_render(viewport) is False
        assert marks == []
        assert released == [meta]
        assert ViewportWidget.get_presentation_image(viewport) is None
        assert getattr(viewport, "_last_presented_frame_metadata", None) is None


def _frame_the_provider_cannot_convert():
    """A frame of Python objects: the upload of the real provider raises TypeError."""
    return np.empty((4, 4, 4), dtype=object)


class _RecordingBridge:
    """The real ImageBridge; records each exception that its upload raises, with its cause and context."""

    def __init__(self, bridge):
        self._bridge = bridge
        self.raised = []

    def update(self, frame):
        try:
            return self._bridge.update(frame)
        except BaseException as exc:
            self.raised.append((exc, exc.__cause__, exc.__context__, exc.__suppress_context__))
            raise

    def __getattr__(self, name):
        return getattr(self._bridge, name)


@pytest.mark.usefixtures("backend")
class TestViewportFailedUpload:
    """An upload that raises keeps the previous presentation, and its own error propagates."""

    def _setup(self, release):
        bridge = _accepted_bridge()
        marks = []
        viewport = _viewport(bridge, marks, [])
        viewport._renderer.release_render_frame = release
        old = np.zeros((4, 4, 4), dtype=np.uint8)
        old[:] = [255, 0, 0, 255]
        assert bridge.update(old) is True, f"the backend refused a good frame: {bridge.provider.last_upload_result.cause}"
        viewport._last_image_frame = old
        viewport._last_presented_frame_metadata = "old"
        return viewport, marks, old

    def test_failed_upload_keeps_the_previous_presentation(self):
        released = []
        viewport, marks, old = self._setup(released.append)
        meta = _metadata()

        with pytest.raises(TypeError):
            ViewportWidget._present_async_render_frame_impl(viewport, _frame_the_provider_cannot_convert(), meta)

        assert released == [meta], "the frame of the failed upload goes back to the renderer once"
        assert marks == []
        assert np.array_equal(ViewportWidget.get_presentation_image(viewport), old)
        assert viewport._last_presented_frame_metadata == "old"

    def test_failed_release_does_not_hide_the_upload_error(self, capsys):
        released = []

        def release(metadata):
            released.append(metadata)
            raise RuntimeError("release refused")

        viewport, marks, old = self._setup(release)
        bridge = _RecordingBridge(viewport._bridge)
        viewport._bridge = bridge
        meta = _metadata()

        with pytest.raises(TypeError) as caught:
            ViewportWidget._present_async_render_frame_impl(viewport, _frame_the_provider_cannot_convert(), meta)

        (upload_error, cause, context, suppressed), = bridge.raised
        assert caught.value is upload_error, "the caller gets the exception that the upload raised"
        assert (caught.value.__cause__, caught.value.__context__, caught.value.__suppress_context__) == (
            cause, context, suppressed
        ), "the upload exception keeps its cause and context"
        assert released == [meta]
        report = capsys.readouterr().err
        assert "did not take back the frame of a failed upload" in report
        assert "RuntimeError: release refused" in report
        assert np.array_equal(ViewportWidget.get_presentation_image(viewport), old)


def test_without_a_gpu_backend_frames_are_presented_as_before():
    """No GPU backend (no renderer) is not a refusal: the frame is marked, hooks and HUD run."""
    script = textwrap.dedent(
        """
        import json
        from types import SimpleNamespace as NS

        import numpy as np
        import omni.ui as ui
        from ovui_widgets.viewport.image_bridge import ImageBridge
        from ovui_widgets.viewport.viewport_widget import ViewportWidget

        calls = {"marked": 0, "released": 0, "hooks": 0, "hud": 0}

        def count(name):
            return lambda *args: calls.__setitem__(name, calls[name] + 1)

        bridge = ImageBridge(4, 4)
        meta = NS(generation=1, extent=(4, 4), view_matrix=np.eye(4), projection_matrix=np.eye(4))
        viewport = NS(
            _bridge=bridge,
            _renderer=NS(
                mark_render_frame_presented=count("marked"),
                release_render_frame=count("released"),
                poll_render_frame=lambda key: NS(image=np.full((4, 4, 4), 255, np.uint8), metadata=meta),
            ),
            _render_generation=1,
            _render_viewport_id="v",
            _async_render_dt=0.016,
            _scene_view=None,
            _viewport_hooks=NS(update_frame=count("hooks")),
            _transform_manipulator=None,
            _async_resize_refresh_was_pending=False,
            _retry_selection_highlight_after_render=lambda: None,
            _record_fps_sample=lambda dt: None,
            _refresh_hud=count("hud"),
            _maybe_invalidate_gizmo_for_scale=lambda: None,
        )
        viewport._present_async_render_frame = lambda image, metadata: (
            ViewportWidget._present_async_render_frame_impl(viewport, image, metadata)
        )
        progress = ViewportWidget.poll_render(viewport)
        print(json.dumps({
            "has_backend": ui.ByteImageProvider.has_upload_backend(),
            "progress": progress,
            "failures": bridge.provider.upload_failure_count,
            "metadata_kept": viewport._last_presented_frame_metadata is meta,
            **calls,
        }))
        """
    )
    # On Windows the test run adds the Vulkan loader folder (Vulkan_DLL_DIR)
    # with os.add_dll_directory; a new process does not inherit it.
    preamble = sys.modules["tests.conftest"].CHILD_PROCESS_VULKAN_DLL_PREAMBLE
    done = subprocess.run([sys.executable, "-c", preamble + script], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, f"stdout:\n{done.stdout}\nstderr (end):\n{done.stderr[-3000:]}"
    report = done.stdout.strip().splitlines()[-1]
    assert report == (
        '{"has_backend": false, "progress": true, "failures": 0, "metadata_kept": true, '
        '"marked": 1, "released": 0, "hooks": 1, "hud": 1}'
    )
