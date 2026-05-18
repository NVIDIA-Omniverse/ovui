# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ChangeEvent.get_common_prefix() (Step 25).

No pxr dependency — pure Python.
"""


from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    ChangeEvent,
    ChangeEventType,
    is_camera_property_only_info_change,
    is_viewport_camera_pose_change_event,
)


def _info_event(*changed_paths, resynced=()):
    return ChangeEvent(
        changed_paths=tuple(changed_paths),
        resynced_paths=tuple(resynced),
        event_type=ChangeEventType.INFO_CHANGE,
    )


class TestGetCommonPrefix:
    def test_single_path_returns_that_path(self):
        e = _info_event("/World/A")
        assert e.get_common_prefix() == "/World/A"

    def test_sibling_paths_return_parent(self):
        e = _info_event("/World/A", "/World/B")
        assert e.get_common_prefix() == "/World"

    def test_nested_paths_return_shallower_ancestor(self):
        e = _info_event("/World/A", resynced=("/World/A/Child",))
        assert e.get_common_prefix() == "/World/A"

    def test_empty_paths_return_root(self):
        e = _info_event()
        assert e.get_common_prefix() == "/"

    def test_root_level_siblings_return_root(self):
        e = _info_event("/World", "/Scene")
        assert e.get_common_prefix() == "/"

    def test_deep_common_ancestor(self):
        e = _info_event("/A/B/C/D", "/A/B/C/E")
        assert e.get_common_prefix() == "/A/B/C"

    def test_no_false_match_on_prefix_substring(self):
        # '/WorldA' and '/WorldB' must NOT share '/World'
        e = _info_event("/WorldA", "/WorldB")
        assert e.get_common_prefix() == "/"

    def test_only_resynced_paths(self):
        e = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World/X", "/World/Y"),
            event_type=ChangeEventType.RESYNC,
        )
        assert e.get_common_prefix() == "/World"

    def test_mixed_changed_and_resynced(self):
        e = ChangeEvent(
            changed_paths=("/World/A",),
            resynced_paths=("/World/B",),
            event_type=ChangeEventType.RESYNC,
        )
        assert e.get_common_prefix() == "/World"

    def test_single_root_path_returns_root(self):
        e = _info_event("/")
        # "/" splits to ["", ""] — common_len = 2 — join gives "/"
        assert e.get_common_prefix() == "/"


class TestViewportCameraPoseSource:
    def test_source_defaults_to_none(self):
        e = _info_event("/World/Camera.xformOp:transform")
        assert e.source is None
        assert not is_viewport_camera_pose_change_event(e)

    def test_viewport_camera_pose_source_matches_pose_properties(self):
        e = ChangeEvent(
            changed_paths=(
                "/World/Camera.xformOp:transform",
                "/World/Camera.omni:kit:centerOfInterest",
                "/World/Camera.focusDistance",
            ),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )
        assert is_viewport_camera_pose_change_event(e)

    def test_viewport_camera_pose_source_rejects_structural_or_non_pose_events(self):
        resync = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World/Camera",),
            event_type=ChangeEventType.RESYNC,
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )
        unrelated = ChangeEvent(
            changed_paths=("/World/Camera.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )
        assert not is_viewport_camera_pose_change_event(resync)
        assert not is_viewport_camera_pose_change_event(unrelated)


class TestCameraPropertyOnlyInfoChange:
    def test_matches_camera_pose_properties(self):
        e = ChangeEvent(
            changed_paths=(
                "/World/Camera.xformOp:transform",
                "/World/Camera.xformOp:translate",
                "/World/Camera.xformOpOrder",
                "/World/Camera.focusDistance",
                "/World/Camera.omni:kit:centerOfInterest",
            ),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert is_camera_property_only_info_change(e)

    def test_matches_camera_visual_properties(self):
        e = ChangeEvent(
            changed_paths=(
                "/World/Camera.focalLength",
                "/World/Camera.horizontalAperture",
                "/World/Camera.verticalAperture",
                "/World/Camera.clippingRange",
                "/World/Camera.fStop",
                "/World/Camera.shutter:open",
                "/World/Camera.shutter:close",
            ),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert is_camera_property_only_info_change(e)

    def test_matches_mixed_camera_pose_and_visual_properties(self):
        e = ChangeEvent(
            changed_paths=(
                "/World/Camera.xformOp:transform",
                "/World/Camera.focalLength",
            ),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )
        assert is_camera_property_only_info_change(e)

    def test_rejects_visibility_property(self):
        e = _info_event("/World/Camera.visibility")
        assert not is_camera_property_only_info_change(e)

    def test_rejects_resynced_paths(self):
        e = _info_event(
            "/World/Camera.xformOp:transform",
            resynced=("/World/Camera",),
        )
        assert not is_camera_property_only_info_change(e)

    def test_rejects_non_info_events(self):
        resync = ChangeEvent(
            changed_paths=("/World/Camera.xformOp:transform",),
            resynced_paths=(),
            event_type=ChangeEventType.RESYNC,
        )
        layer_info = ChangeEvent(
            changed_paths=("/World/Camera.focalLength",),
            resynced_paths=(),
            event_type=ChangeEventType.LAYER_INFO,
        )
        assert not is_camera_property_only_info_change(resync)
        assert not is_camera_property_only_info_change(layer_info)

    def test_rejects_empty_prim_path_and_mixed_non_camera_property(self):
        assert not is_camera_property_only_info_change(_info_event())
        assert not is_camera_property_only_info_change(_info_event("/World/Camera"))
        assert not is_camera_property_only_info_change(
            _info_event(
                "/World/Camera.focalLength",
                "/World/Cube.size",
            )
        )
