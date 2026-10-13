# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Published-state contract of ``ui.RasterImageProvider`` across source changes.

These tests drive the real standalone raster loader against real files, which
is the path the reported defect follows: after a provider has successfully
loaded an image, pointing the *same* provider at a missing file must leave it
reporting that it has no image, so an application fallback keyed on
``is_reference_valid`` can render.

The provider's load state machine is advanced with
``ImageWithProvider.prepare_draw()`` rather than by pumping frames, and the
widget is kept hidden. That is deliberate: it exercises the loader end to end
while guaranteeing the widget never *draws* the provider's texture handle. A
provider that wrongly reports a released handle as valid would otherwise hand
that handle to the graphics backend, which is not something a test should ask a
driver to do.

The exhaustive per-branch contract (including the asynchronous terminal failure
that the synchronous standalone loader cannot produce) lives in the native test
``tests/cpp/test_raster_image_provider_contract.cpp``.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
import zlib

import omni.ui as ui
from test_base import OmniUiTest


def _write_png(path: pathlib.Path, width: int, height: int) -> None:
    """Write a minimal opaque-white RGBA8 PNG without requiring Pillow."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + tag
            + payload
            + zlib.crc32(tag + payload).to_bytes(4, "big")
        )

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 6, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\xff" * (width * 4) for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class TestRasterImageProviderContract(OmniUiTest):
    """The provider's public state must always describe its current source."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._tmp.name)

        self._first = root / "first.png"
        self._second = root / "second.png"
        self._missing = root / "does_not_exist.png"
        _write_png(self._first, 8, 8)
        _write_png(self._second, 4, 2)
        self.assertFalse(self._missing.exists(), "the missing-source fixture must not exist")

        self._window = ui.Window(
            "raster-image-provider-contract",
            dockPreference=ui.DockPreference.DISABLED,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_TITLE_BAR | ui.WINDOW_FLAGS_NO_RESIZE,
            width=64,
            height=64,
            position_x=0,
            position_y=0,
        )

    async def asyncTearDown(self):
        if self._window is not None:
            self._window.destroy()
            self._window = None
        self._tmp.cleanup()
        await super().asyncTearDown()

    def _provider(self, source) -> ui.RasterImageProvider:
        """A provider wired to a hidden widget, so loads run but nothing draws."""
        provider = ui.RasterImageProvider(str(source))
        with self._window.frame:
            widget = ui.ImageWithProvider(provider, fill_policy=ui.IwpFillPolicy.IWP_STRETCH)
        widget.visible = False
        self._widget = widget
        return provider

    def _advance(self, frames: int = 8) -> None:
        for _ in range(frames):
            self._widget.prepare_draw(64.0, 64.0)

    def _assert_no_image(self, provider, where: str) -> None:
        self.assertFalse(
            provider.is_reference_valid,
            f"{where}: is_reference_valid must be False so an authored fallback can render",
        )
        self.assertEqual((provider.width, provider.height), (0, 0), f"{where}: dimensions must be 0x0")

    def _assert_image(self, provider, size, where: str) -> None:
        self.assertTrue(provider.is_reference_valid, f"{where}: is_reference_valid must be True")
        self.assertEqual((provider.width, provider.height), size, f"{where}: dimensions must match the image")

    # -- baseline behaviour that already holds and must keep holding ---------

    async def test_cold_missing_source_reports_no_image(self):
        provider = self._provider(self._missing)
        self._advance()
        self._assert_no_image(provider, "missing source from construction")
        self.assertEqual(provider.source_url, str(self._missing))

    async def test_valid_to_valid_replaces_the_image(self):
        provider = self._provider(self._first)
        self._advance()
        self._assert_image(provider, (8, 8), "first valid load")

        provider.source_url = str(self._second)
        self._advance()
        self._assert_image(provider, (4, 2), "second valid load")
        self.assertEqual(provider.source_url, str(self._second))

    # -- the reported defect -------------------------------------------------

    async def test_terminal_failure_after_valid_load_clears_published_state(self):
        """The ticket: a failed load must not keep publishing the previous image."""
        provider = self._provider(self._first)
        self._advance()
        self._assert_image(provider, (8, 8), "precondition")

        provider.source_url = str(self._missing)
        self._advance()

        self._assert_no_image(provider, "terminal failure after a valid load")
        self.assertEqual(
            provider.source_url,
            str(self._missing),
            "the requested source URL must survive a failed load",
        )

    async def test_recovery_after_terminal_failure(self):
        provider = self._provider(self._first)
        self._advance()
        provider.source_url = str(self._missing)
        self._advance()

        provider.source_url = str(self._second)
        self._advance()
        self._assert_image(provider, (4, 2), "recovery after a failed load")
        self.assertEqual(provider.source_url, str(self._second))

    async def test_reload_rereads_the_file_while_an_image_shares_the_path(self):
        """A reload must read the replaced file even when ``ui.Image`` shares it.

        ``ui.Image(path)`` and ``RasterImageProvider(path)`` go through one
        per-URL texture cache. The drawn Image holds a reference to the cached
        entry for as long as it lives, so a reload that only dropped the
        provider's own reference used to find the entry still there and
        republish the old pixels. The replacement here changes the image
        dimensions, so the provider's published size shows which file was read.
        """
        shared = pathlib.Path(self._tmp.name) / "shared.png"
        _write_png(shared, 8, 8)

        # A real, drawn ui.Image on the same path: this is what takes the
        # second reference to the shared cache entry.
        window = await self.create_test_window(64, 64)
        with window.frame:
            with ui.VStack():
                ui.Image(str(shared), height=32)
                provider = ui.RasterImageProvider(str(shared))
                ui.ImageWithProvider(provider, height=32, fill_policy=ui.IwpFillPolicy.IWP_STRETCH)
        await self.wait_n_updates(4)
        self._assert_image(provider, (8, 8), "precondition: both consumers loaded the first file")

        # Replace the file on disk with different content, then reload.
        _write_png(shared, 4, 2)
        provider.source_url = str(shared)
        await self.wait_n_updates(4)

        self._assert_image(provider, (4, 2), "reload while a ui.Image shares the path")

    async def test_reload_finds_a_created_file_while_another_consumer_shares_it(self):
        """A reload must find a file that appeared, even if a peer also failed on it.

        Two consumers point at a path that does not exist yet, so both fail.
        The file is then created and only one of them reloads. A failed load
        that was remembered and held alive by the peer would be handed back
        here, leaving the reloading consumer blank with the file on disk.
        """
        later = pathlib.Path(self._tmp.name) / "appears_later.png"
        self.assertFalse(later.exists(), "the fixture must not exist yet")

        window = await self.create_test_window(64, 64)
        with window.frame:
            with ui.VStack():
                peer = ui.RasterImageProvider(str(later))
                ui.ImageWithProvider(peer, height=32, fill_policy=ui.IwpFillPolicy.IWP_STRETCH)
                provider = ui.RasterImageProvider(str(later))
                ui.ImageWithProvider(provider, height=32, fill_policy=ui.IwpFillPolicy.IWP_STRETCH)
        await self.wait_n_updates(4)
        self._assert_no_image(peer, "precondition: the peer failed on the missing file")
        self._assert_no_image(provider, "precondition: the provider failed on the missing file")

        # The file appears. Only one consumer reloads; the peer keeps failing.
        _write_png(later, 4, 2)
        provider.source_url = str(later)
        await self.wait_n_updates(4)

        self._assert_image(provider, (4, 2), "reload after the file appeared, with a failed peer")

    async def test_repeated_transitions_converge(self):
        provider = self._provider(self._first)
        self._advance()

        provider.source_url = str(self._missing)
        self._advance()
        self._assert_no_image(provider, "first failure")

        provider.source_url = str(self._missing.with_name("also_absent.png"))
        self._advance()
        self._assert_no_image(provider, "second failure")

        provider.source_url = str(self._second)
        self._advance()
        self._assert_image(provider, (4, 2), "recovery after repeated failures")


if __name__ == "__main__":
    unittest.main()
