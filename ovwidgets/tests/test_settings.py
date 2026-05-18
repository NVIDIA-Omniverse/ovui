# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.common.settings — Settings class and Subscription."""

import gc
import json
import os

import pytest

from ovwidgets.common.settings import Settings, Subscription

# ── get / set basics ──────────────────────────────────────────────────────────

class TestGetSet:
    def test_get_unknown_returns_none(self):
        s = Settings()
        assert s.get("no.such.key") is None

    def test_get_unknown_with_default(self):
        s = Settings()
        assert s.get("no.such.key", 42) == 42

    def test_get_unknown_with_none_default(self):
        s = Settings()
        assert s.get("no.such.key", None) is None

    def test_set_get_string(self):
        s = Settings()
        s.set("test.key", "hello")
        assert s.get("test.key") == "hello"

    def test_set_get_int(self):
        s = Settings()
        s.set("count", 7)
        assert s.get("count") == 7

    def test_set_get_float(self):
        s = Settings()
        s.set("ratio", 3.14)
        assert s.get("ratio") == pytest.approx(3.14)

    def test_set_get_bool_true(self):
        s = Settings()
        s.set("flag", True)
        assert s.get("flag") is True

    def test_set_get_bool_false(self):
        s = Settings()
        s.set("flag", False)
        assert s.get("flag") is False

    def test_set_get_list(self):
        s = Settings()
        s.set("items", [1, 2, 3])
        assert s.get("items") == [1, 2, 3]

    def test_set_get_dict(self):
        s = Settings()
        s.set("data", {"a": 1})
        assert s.get("data") == {"a": 1}

    def test_set_get_none(self):
        s = Settings()
        s.set("nullable", None)
        assert s.get("nullable") is None

    def test_set_overwrites_previous(self):
        s = Settings()
        s.set("x", "first")
        s.set("x", "second")
        assert s.get("x") == "second"

    def test_get_default_not_used_when_key_exists(self):
        s = Settings()
        s.set("x", 0)
        assert s.get("x", 99) == 0


# ── Default settings ──────────────────────────────────────────────────────────

class TestDefaults:
    def test_has_ui_theme(self):
        assert Settings().get("ui.theme") == "dark"

    def test_has_recent_files(self):
        assert Settings().get("app.recent_files") == []

    def test_has_layout_save_path(self):
        assert Settings().get("layout.save_path") == "~/.ovgear/layout.json"

    def test_has_camera_fov(self):
        assert Settings().get("viewport.camera.fov") == pytest.approx(45.0)

    def test_has_camera_near(self):
        assert Settings().get("viewport.camera.near") == pytest.approx(0.1)

    def test_has_camera_far(self):
        assert Settings().get("viewport.camera.far") == pytest.approx(10000.0)

    def test_defaults_are_independent_instances(self):
        s1 = Settings()
        s2 = Settings()
        s1.get("app.recent_files").append("file.usd")
        assert s2.get("app.recent_files") == []

    def test_all_six_default_keys_present(self):
        s = Settings()
        keys = [
            "ui.theme", "app.recent_files", "layout.save_path",
            "viewport.camera.fov", "viewport.camera.near", "viewport.camera.far",
        ]
        for key in keys:
            assert s.get(key) is not None or s.get(key) == []


# ── Subscriber notifications ──────────────────────────────────────────────────

class TestSubscribers:
    def test_subscriber_called_on_change(self):
        s = Settings()
        calls = []
        sub = s.subscribe("x", lambda k, v: calls.append((k, v)))
        s.set("x", 42)
        assert calls == [("x", 42)]

    def test_subscriber_receives_key_and_value(self):
        s = Settings()
        received = {}
        sub = s.subscribe("my.key", lambda k, v: received.update({"k": k, "v": v}))
        s.set("my.key", "hello")
        assert received == {"k": "my.key", "v": "hello"}

    def test_subscriber_not_called_when_value_unchanged(self):
        s = Settings()
        s.set("x", 5)
        calls = []
        sub = s.subscribe("x", lambda k, v: calls.append(v))
        s.set("x", 5)
        assert calls == []

    def test_subscriber_called_on_first_set_of_new_key(self):
        s = Settings()
        calls = []
        sub = s.subscribe("new.key", lambda k, v: calls.append(v))
        s.set("new.key", "first_value")
        assert calls == ["first_value"]

    def test_multiple_subscribers_all_called(self):
        s = Settings()
        calls_a, calls_b = [], []
        sub_a = s.subscribe("x", lambda k, v: calls_a.append(v))
        sub_b = s.subscribe("x", lambda k, v: calls_b.append(v))
        s.set("x", 99)
        assert calls_a == [99]
        assert calls_b == [99]

    def test_subscriber_not_called_for_other_key(self):
        s = Settings()
        calls = []
        sub = s.subscribe("key_a", lambda k, v: calls.append(v))
        s.set("key_b", "other")
        assert calls == []

    def test_subscriber_called_multiple_times(self):
        s = Settings()
        calls = []
        sub = s.subscribe("x", lambda k, v: calls.append(v))
        s.set("x", 1)
        s.set("x", 2)
        s.set("x", 3)
        assert calls == [1, 2, 3]

    def test_subscriber_not_called_for_existing_default_unchanged(self):
        s = Settings()
        calls = []
        sub = s.subscribe("ui.theme", lambda k, v: calls.append(v))
        s.set("ui.theme", "dark")  # same as default
        assert calls == []

    def test_subscriber_called_when_default_changes(self):
        s = Settings()
        calls = []
        sub = s.subscribe("ui.theme", lambda k, v: calls.append(v))
        s.set("ui.theme", "light")
        assert calls == ["light"]


# ── Subscription cancellation ─────────────────────────────────────────────────

class TestSubscriptionCancellation:
    def test_cancel_stops_notifications(self):
        s = Settings()
        calls = []
        sub = s.subscribe("x", lambda k, v: calls.append(v))
        s.set("x", 1)
        sub.cancel()
        s.set("x", 2)
        assert calls == [1]

    def test_cancel_twice_doesnt_crash(self):
        s = Settings()
        sub = s.subscribe("x", lambda k, v: None)
        sub.cancel()
        sub.cancel()

    def test_cancel_one_doesnt_affect_other(self):
        s = Settings()
        calls_a, calls_b = [], []
        sub_a = s.subscribe("x", lambda k, v: calls_a.append(v))
        sub_b = s.subscribe("x", lambda k, v: calls_b.append(v))
        sub_a.cancel()
        s.set("x", 7)
        assert calls_a == []
        assert calls_b == [7]

    def test_setting_key_still_works_after_cancel(self):
        s = Settings()
        sub = s.subscribe("x", lambda k, v: None)
        sub.cancel()
        s.set("x", "new_value")
        assert s.get("x") == "new_value"

    def test_subscription_is_subscription_instance(self):
        s = Settings()
        sub = s.subscribe("x", lambda k, v: None)
        assert isinstance(sub, Subscription)

    def test_auto_cancel_on_gc(self):
        s = Settings()
        calls = []

        def cb(k, v):
            calls.append(v)

        sub = s.subscribe("x", cb)
        del sub
        gc.collect()
        s.set("x", 99)
        assert calls == []

    def test_cancel_before_any_notification(self):
        s = Settings()
        calls = []
        sub = s.subscribe("x", lambda k, v: calls.append(v))
        sub.cancel()
        s.set("x", 1)
        assert calls == []


# ── get_string ────────────────────────────────────────────────────────────────

class TestGetString:
    def test_get_string_returns_string(self):
        s = Settings()
        s.set("name", "alice")
        assert s.get_string("name") == "alice"

    def test_get_string_converts_int(self):
        s = Settings()
        s.set("count", 42)
        assert s.get_string("count") == "42"

    def test_get_string_converts_float(self):
        s = Settings()
        s.set("fov", 45.0)
        assert s.get_string("fov") == "45.0"

    def test_get_string_missing_key_returns_empty_string(self):
        s = Settings()
        assert s.get_string("missing") == ""

    def test_get_string_missing_key_custom_default(self):
        s = Settings()
        assert s.get_string("missing", "fallback") == "fallback"

    def test_get_string_returns_str_type(self):
        s = Settings()
        s.set("val", 123)
        result = s.get_string("val")
        assert type(result) is str

    def test_get_string_bool_true(self):
        s = Settings()
        s.set("flag", True)
        assert s.get_string("flag") == "True"


# ── Persistence ───────────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_creates_valid_json(self, tmp_path):
        s = Settings()
        path = str(tmp_path / "settings.json")
        s.save_to_file(path)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_load_restores_values(self, tmp_path):
        s1 = Settings()
        s1.set("my.key", "my_value")
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        assert s2.get("my.key") == "my_value"

    def test_round_trip_multiple_types(self, tmp_path):
        s1 = Settings()
        s1.set("str_key", "hello")
        s1.set("int_key", 42)
        s1.set("float_key", 3.14)
        s1.set("list_key", [1, 2, 3])
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        assert s2.get("str_key") == "hello"
        assert s2.get("int_key") == 42
        assert s2.get("float_key") == pytest.approx(3.14)
        assert s2.get("list_key") == [1, 2, 3]

    def test_load_notifies_subscribers_for_changed_keys(self, tmp_path):
        data = {"ui.theme": "light", "custom.key": "value"}
        path = str(tmp_path / "settings.json")
        with open(path, "w") as f:
            json.dump(data, f)

        s = Settings()
        notifications = []
        sub = s.subscribe("ui.theme", lambda k, v: notifications.append(v))
        s.load_from_file(path)
        assert notifications == ["light"]

    def test_load_does_not_notify_unchanged_keys(self, tmp_path):
        data = {"ui.theme": "dark"}  # same as default
        path = str(tmp_path / "settings.json")
        with open(path, "w") as f:
            json.dump(data, f)

        s = Settings()
        calls = []
        sub = s.subscribe("ui.theme", lambda k, v: calls.append(v))
        s.load_from_file(path)
        assert calls == []

    def test_load_nonexistent_file_raises(self, tmp_path):
        s = Settings()
        with pytest.raises(Exception):
            s.load_from_file(str(tmp_path / "nonexistent.json"))

    def test_save_creates_parent_directories(self, tmp_path):
        s = Settings()
        nested = str(tmp_path / "a" / "b" / "c" / "settings.json")
        s.save_to_file(nested)
        assert os.path.exists(nested)

    def test_save_includes_all_defaults(self, tmp_path):
        s = Settings()
        path = str(tmp_path / "settings.json")
        s.save_to_file(path)
        with open(path) as f:
            data = json.load(f)
        assert data["ui.theme"] == "dark"
        assert data["viewport.camera.fov"] == pytest.approx(45.0)
        assert data["app.recent_files"] == []

    def test_load_merges_with_existing(self, tmp_path):
        s = Settings()
        s.set("existing.key", "existing_value")

        path = str(tmp_path / "settings.json")
        with open(path, "w") as f:
            json.dump({"new.key": "new_value"}, f)

        s.load_from_file(path)
        assert s.get("existing.key") == "existing_value"
        assert s.get("new.key") == "new_value"

    def test_round_trip_full_save_load(self, tmp_path):
        s1 = Settings()
        s1.set("ui.theme", "light")
        s1.set("viewport.camera.fov", 60.0)
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        assert s2.get("ui.theme") == "light"
        assert s2.get("viewport.camera.fov") == pytest.approx(60.0)

    def test_save_to_cwd_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = Settings()
        s.save_to_file("settings.json")
        assert os.path.exists(str(tmp_path / "settings.json"))


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_key_with_dots_is_flat_string(self):
        s = Settings()
        s.set("a.b.c", "val")
        assert s.get("a.b.c") == "val"
        assert s.get("a") is None

    def test_empty_string_key(self):
        s = Settings()
        s.set("", "empty_key_value")
        assert s.get("") == "empty_key_value"

    def test_set_none_value(self):
        s = Settings()
        s.set("nullable", None)
        assert s.get("nullable") is None

    def test_set_none_twice_no_notification(self):
        s = Settings()
        s.set("nullable", None)
        calls = []
        sub = s.subscribe("nullable", lambda k, v: calls.append(v))
        s.set("nullable", None)
        assert calls == []

    def test_large_list_value(self):
        s = Settings()
        big = list(range(10000))
        s.set("big.list", big)
        assert s.get("big.list") == big

    def test_nested_dict_value(self):
        s = Settings()
        nested = {"a": {"b": {"c": 42}}}
        s.set("nested", nested)
        assert s.get("nested") == nested

    def test_subscriber_modifies_settings_during_notification(self):
        s = Settings()

        def recursive_cb(k, v):
            if v < 3:
                s.set("x", v + 1)

        sub = s.subscribe("x", recursive_cb)
        s.set("x", 0)
        assert s.get("x") == 3

    def test_bool_false_not_confused_with_missing(self):
        s = Settings()
        s.set("flag", False)
        assert s.get("flag") is False
        assert s.get("flag", True) is False

    def test_zero_not_confused_with_missing(self):
        s = Settings()
        s.set("count", 0)
        assert s.get("count", 99) == 0

    def test_empty_string_value_not_confused_with_missing(self):
        s = Settings()
        s.set("name", "")
        assert s.get("name", "default") == ""

    def test_set_bool_true_to_same_no_notification(self):
        s = Settings()
        s.set("flag", True)
        calls = []
        sub = s.subscribe("flag", lambda k, v: calls.append(v))
        s.set("flag", True)
        assert calls == []

    def test_settings_instances_are_independent(self):
        s1 = Settings()
        s2 = Settings()
        s1.set("key", "from_s1")
        assert s2.get("key") is None

    def test_subscribe_same_callback_twice(self):
        s = Settings()
        calls = []
        cb = lambda k, v: calls.append(v)
        sub1 = s.subscribe("x", cb)
        sub2 = s.subscribe("x", cb)
        s.set("x", 1)
        assert calls == [1, 1]

    def test_subscriber_on_key_that_never_gets_set(self):
        s = Settings()
        calls = []
        sub = s.subscribe("unset.key", lambda k, v: calls.append(v))
        assert calls == []

    def test_many_subscribers(self):
        s = Settings()
        calls = []
        subs = [s.subscribe("x", lambda k, v, i=i: calls.append(i)) for i in range(50)]
        s.set("x", "fire")
        assert len(calls) == 50
        assert sorted(calls) == list(range(50))
