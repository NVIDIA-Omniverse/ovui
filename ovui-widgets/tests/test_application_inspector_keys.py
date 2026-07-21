# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from ovui_widgets.app.application import _normalize_printable_key


def test_inspector_named_keys_normalize_to_application_glfw_shortcuts() -> None:
    assert _normalize_printable_key(522) == 261  # ImGui Delete -> GLFW Delete
    assert _normalize_printable_key(523) == 259  # ImGui Backspace -> GLFW Backspace
    assert _normalize_printable_key(573) == 291  # ImGui F2 -> GLFW F2
    assert _normalize_printable_key(513) == 263  # ImGui Left -> GLFW Left
    assert _normalize_printable_key(514) == 262  # ImGui Right -> GLFW Right
    assert _normalize_printable_key(526) == 256  # ImGui Escape -> GLFW Escape


def test_inspector_printable_keys_normalize_to_ascii() -> None:
    assert _normalize_printable_key(536) == ord("0")
    assert _normalize_printable_key(545) == ord("9")
    assert _normalize_printable_key(546) == ord("A")
    assert _normalize_printable_key(571) == ord("Z")


def test_native_glfw_and_ascii_keys_are_unchanged() -> None:
    assert _normalize_printable_key(261) == 261
    assert _normalize_printable_key(ord("Z")) == ord("Z")
