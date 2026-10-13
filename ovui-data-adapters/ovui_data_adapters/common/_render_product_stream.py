# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Ownership and product routing for the adapters' existing CUDA stream tap."""


def attach(adapter, tap, product_path):
    existing = getattr(adapter, "_livestream", None)
    if existing is not None and existing is not tap:
        raise ValueError("Renderer already has a livestream owner")
    if not product_path or product_path != adapter.get_active_render_product_path():
        raise ValueError("Select the target RenderProduct before attaching its stream")
    stop_pacing = getattr(adapter, "_stop_native_frame_pacing", None)
    if stop_pacing:
        stop_pacing("RenderProduct stream attached")
    release = getattr(adapter, "_release_retained_output", None)
    if release:
        release()
    adapter._livestream = tap
    adapter._livestream_product_path = product_path


def detach(adapter, tap):
    if getattr(adapter, "_livestream", None) is tap:
        adapter._livestream = None
        adapter._livestream_product_path = None


def is_attached(adapter, tap):
    return tap is not None and getattr(adapter, "_livestream", None) is tap


def release_for_shutdown(adapter):
    """Return an adapter-owned tap to close; release a borrowed one unclosed.

    A RenderProduct stream attached through attach() belongs to its external
    owner (for example Media), which also owns the ovstream SDK lifetime.
    """
    tap = getattr(adapter, "_livestream", None)
    if tap is not None and getattr(adapter, "_livestream_product_path", None):
        detach(adapter, tap)
        return None
    return tap


def for_current_product(adapter):
    product = getattr(adapter, "_livestream_product_path", None)
    if product and product != adapter.get_active_render_product_path():
        return None
    return getattr(adapter, "_livestream", None)
