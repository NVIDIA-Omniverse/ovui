# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for app-hosted widget registry."""

from ovui_widgets.app.widget_registry import AppWidgetRegistry


def test_widget_registry_replays_existing_widgets_and_notifies_lifecycle():
    registry = AppWidgetRegistry()
    first = object()
    second = object()
    events = []

    first_handle = registry.add(first)
    subscription = registry.subscribe(
        lambda event: events.append((event.action, event.widget))
    )

    assert events == [("added", first)]
    assert registry.iter_widgets() == (first,)

    second_handle = registry.add(second)
    registry.add(second)

    assert events == [("added", first), ("added", second)]
    assert registry.iter_widgets() == (first, second)

    assert second_handle.remove() is True
    assert second_handle.remove() is False
    assert events == [
        ("added", first),
        ("added", second),
        ("removed", second),
    ]

    subscription.cancel()
    assert first_handle.remove() is True
    assert events == [
        ("added", first),
        ("added", second),
        ("removed", second),
    ]


def test_widget_registry_clear_removes_in_reverse_order():
    registry = AppWidgetRegistry()
    first = object()
    second = object()
    registry.add(first)
    registry.add(second)
    events = []
    registry.subscribe(
        lambda event: events.append((event.action, event.widget)),
        replay_existing=False,
    )

    registry.clear()

    assert events == [("removed", second), ("removed", first)]
    assert registry.iter_widgets() == ()


def test_widget_registry_isolates_subscriber_failures(capsys):
    registry = AppWidgetRegistry()
    widget = object()
    events = []

    def broken(_event):
        raise RuntimeError("boom")

    registry.subscribe(broken, replay_existing=False)
    registry.subscribe(lambda event: events.append(event.action), replay_existing=False)

    registry.add(widget)

    assert events == ["added"]
    assert len(registry.failures) == 1
    assert registry.failures[0].action == "added"
    assert registry.failures[0].widget is widget
    assert isinstance(registry.failures[0].error, RuntimeError)
    assert "subscriber failed during added" in capsys.readouterr().err
