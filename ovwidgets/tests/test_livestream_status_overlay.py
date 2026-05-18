# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step-1.7 livestream status overlay.

Covers the pure formatter (`_livestream_status_overlay`) plus the
viewport-widget wiring that polls the tap once per render.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ovwidgets.viewport import _livestream_status_overlay as overlay

# ---------------------------------------------------------------------------
# Pure formatter tests — no omni.ui frame loop required.
# ---------------------------------------------------------------------------

def test_format_indicator_off_when_state_off():
    assert overlay.format_indicator(
        state="OFF", n_clients=0, last_error=None,
        signal_port=49100, media_port=47999,
    ) == "Off"


def test_format_indicator_listening_shows_both_ports():
    assert overlay.format_indicator(
        state="LISTENING", n_clients=0, last_error=None,
        signal_port=49100, media_port=47999,
    ) == "Listening :49100/47999"


def test_format_indicator_streaming_pluralises_clients():
    one = overlay.format_indicator(
        state="STREAMING", n_clients=1, last_error=None,
        signal_port=49100, media_port=47999,
    )
    two = overlay.format_indicator(
        state="STREAMING", n_clients=2, last_error=None,
        signal_port=49100, media_port=47999,
    )
    assert one == "Streaming 1 client"
    assert two == "Streaming 2 clients"


def test_format_indicator_error_takes_precedence():
    """A non-empty ``last_error`` wins over the state field, so an
    ERROR transition mid-session shows up immediately even if the
    state hasn't caught up."""
    assert overlay.format_indicator(
        state="STREAMING", n_clients=3, last_error="bind failed",
        signal_port=49100, media_port=47999,
    ) == "Error: bind failed"


def test_format_indicator_unknown_state_falls_back_to_off():
    assert overlay.format_indicator(
        state="UNKNOWN_STATE", n_clients=0, last_error=None,
        signal_port=49100, media_port=47999,
    ) == "Off"


def test_format_tooltip_includes_protocol_ports_and_public_ip():
    txt = overlay.format_tooltip(
        state="LISTENING", n_clients=0, last_error=None,
        signal_port=49100, media_port=47999,
        protocol="webrtc", public_ip="203.0.113.42",
    )
    assert "Livestream — Listening :49100/47999" in txt
    assert "Protocol: webrtc" in txt
    assert "Signaling port: 49100" in txt
    assert "Media port: 47999" in txt
    assert "Public IP: 203.0.113.42" in txt


def test_format_tooltip_unset_public_ip_renders_auto():
    """``public_ip=None`` (no env var) shows ``auto (ICE)`` so the
    user knows ICE is in play, not that the IP is missing."""
    txt = overlay.format_tooltip(
        state="OFF", n_clients=0, last_error=None,
        signal_port=49100, media_port=47999,
        protocol="webrtc", public_ip=None,
    )
    assert "Public IP: auto (ICE)" in txt


# ---------------------------------------------------------------------------
# ViewportWidget wiring — uses MagicMock omni.ui surface so this runs
# without an X server. Only exercises the refresh path; screenshot QA covers
# the overlay's visual placement.
# ---------------------------------------------------------------------------

def _make_widget_stub():
    """Build a ViewportWidget-shaped stub with the exact attributes
    the Step-1.7 refresh path touches."""
    from ovwidgets.viewport import viewport_widget as vw_mod

    stub = vw_mod.ViewportWidget.__new__(vw_mod.ViewportWidget)
    stub._renderer = None
    stub._livestream_row = MagicMock()
    stub._livestream_row.visible = False
    stub._livestream_value_label = MagicMock()
    stub._livestream_value_label.text = ""
    return stub


def test_refresh_hides_overlay_when_no_renderer():
    stub = _make_widget_stub()
    # _refresh_livestream_status is bound; call it directly.
    from ovwidgets.viewport.viewport_widget import ViewportWidget
    ViewportWidget._refresh_livestream_status(stub)
    # Hidden row → ``_set_widget_visible(row, False)`` → ``row.visible = False``.
    # The MagicMock recorded a setattr on `visible`; check the latest value.
    assert stub._livestream_row.visible is False


def test_refresh_hides_overlay_when_no_livestream_attr():
    stub = _make_widget_stub()
    stub._renderer = SimpleNamespace()  # no .livestream attribute
    from ovwidgets.viewport.viewport_widget import ViewportWidget
    ViewportWidget._refresh_livestream_status(stub)
    assert stub._livestream_row.visible is False


def test_refresh_renders_listening_text_when_tap_attached():
    """With a live tap reporting LISTENING, the value-label text
    should be exactly the formatter's output and the row should
    become visible."""
    stub = _make_widget_stub()

    tap = MagicMock()
    tap.status.return_value = ("LISTENING", 0, None)
    tap.signal_port = 49100
    tap.media_port = 47999
    tap.protocol = "webrtc"
    tap.public_ip = None

    stub._renderer = SimpleNamespace(livestream=tap)
    from ovwidgets.viewport.viewport_widget import ViewportWidget
    ViewportWidget._refresh_livestream_status(stub)

    assert stub._livestream_value_label.text == "Listening :49100/47999"
    assert stub._livestream_row.visible is True


def test_refresh_renders_streaming_text_after_simulated_connect():
    """Drive a connect: tap reports STREAMING with 2 clients → label
    should read ``Streaming 2 clients``. This is the Step-1.7
    'status updates on simulated connect' acceptance check."""
    stub = _make_widget_stub()
    tap = MagicMock()
    tap.signal_port = 49100
    tap.media_port = 47999
    tap.protocol = "webrtc"
    tap.public_ip = None
    stub._renderer = SimpleNamespace(livestream=tap)

    from ovwidgets.viewport.viewport_widget import ViewportWidget

    # Initial: LISTENING.
    tap.status.return_value = ("LISTENING", 0, None)
    ViewportWidget._refresh_livestream_status(stub)
    assert stub._livestream_value_label.text == "Listening :49100/47999"

    # Simulated connect: two clients.
    tap.status.return_value = ("STREAMING", 2, None)
    ViewportWidget._refresh_livestream_status(stub)
    assert stub._livestream_value_label.text == "Streaming 2 clients"


def test_refresh_renders_error_text_when_tap_has_error():
    stub = _make_widget_stub()
    tap = MagicMock()
    tap.status.return_value = ("ERROR", 0, "bind failed: address in use")
    tap.signal_port = 49100
    tap.media_port = 47999
    tap.protocol = "webrtc"
    tap.public_ip = None
    stub._renderer = SimpleNamespace(livestream=tap)

    from ovwidgets.viewport.viewport_widget import ViewportWidget
    ViewportWidget._refresh_livestream_status(stub)

    assert stub._livestream_value_label.text == "Error: bind failed: address in use"


def test_refresh_recovers_from_status_exception():
    """If ``tap.status()`` itself raises (worker-thread race, mock
    misconfig), the overlay must hide the row, not crash the HUD
    refresh."""
    stub = _make_widget_stub()
    tap = MagicMock()
    tap.status.side_effect = RuntimeError("worker thread blew up")
    stub._renderer = SimpleNamespace(livestream=tap)

    from ovwidgets.viewport.viewport_widget import ViewportWidget
    # Must not raise.
    ViewportWidget._refresh_livestream_status(stub)
    assert stub._livestream_row.visible is False
