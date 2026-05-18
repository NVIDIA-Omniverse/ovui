# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Status overlay widget for the livestream tap — issue #34 Step 1.7.

Pure presentation logic: takes a status snapshot from
``LivestreamTap`` (state + client count + last error + the static
protocol / port / public-IP fields) and renders the strings the
overlay shows. The widget itself lives inside
``ViewportWidget._build_hud`` (top-right block); this module only
formats text so the formatting can be unit-tested without an
omni.ui frame loop.

Public:
    format_indicator(state, n_clients, last_error, signal_port, media_port)
        → short label text shown in the overlay
    format_tooltip(state, n_clients, last_error, signal_port, media_port,
                   protocol, public_ip)
        → multi-line tooltip text
"""

from __future__ import annotations

from typing import Optional

# Stable strings — must match _livestream_tap._STATE_* values.
STATE_OFF       = "OFF"
STATE_LISTENING = "LISTENING"
STATE_STREAMING = "STREAMING"
STATE_ERROR     = "ERROR"


def format_indicator(
    state: str,
    n_clients: int,
    last_error: Optional[str],
    signal_port: int,
    media_port: int,
) -> str:
    """Short user-facing label shown inside the overlay.

    The four cases map exactly to ``LivestreamTap.status()``'s state
    field. Examples:

      * ``"Off"`` — tap exists but server is not up (or not yet up).
      * ``"Listening :49100/47999"`` — server bound, no clients yet.
      * ``"Streaming 2 clients"`` — at least one client attached.
      * ``"Error: bind failed"`` — permanent failure; tap disabled.

    The error case takes precedence over state when ``last_error`` is
    set, so a transition to ERROR mid-session surfaces immediately
    even if the state field hasn't been re-assigned yet.
    """
    if last_error:
        return f"Error: {last_error}"
    if state == STATE_STREAMING:
        word = "client" if n_clients == 1 else "clients"
        return f"Streaming {n_clients} {word}"
    if state == STATE_LISTENING:
        return f"Listening :{signal_port}/{media_port}"
    if state == STATE_ERROR:
        # Defensive: ERROR state with no last_error string should not
        # happen, but fall through to a generic message rather than
        # show "Off" (which would mislead).
        return "Error"
    return "Off"


def format_tooltip(
    state: str,
    n_clients: int,
    last_error: Optional[str],
    signal_port: int,
    media_port: int,
    protocol: str,
    public_ip: Optional[str],
) -> str:
    """Multi-line tooltip shown when the user hovers the indicator.

    Surfaces the static configuration the overlay's short label
    cannot fit (protocol, public IP) plus the dynamic state. Lines
    are joined with ``\\n`` so omni.ui's tooltip widget renders them
    as separate rows.
    """
    primary = format_indicator(state, n_clients, last_error, signal_port, media_port)
    ip_text = public_ip if public_ip else "auto (ICE)"
    return (
        f"Livestream — {primary}\n"
        f"Protocol: {protocol}\n"
        f"Signaling port: {signal_port}\n"
        f"Media port: {media_port}\n"
        f"Public IP: {ip_text}"
    )
