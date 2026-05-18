# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.content.backends — BackendAdapter ABC and supporting types.

See the content browser implementation step 1 "Introduce BackendAdapter ABC and data types".
"""

import dataclasses
from enum import Enum, Flag, IntEnum, IntFlag

import pytest

from ovwidgets.content.backends import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# Concrete minimal implementation used only in tests
# ──────────────────────────────────────────────────────────────────────────────

class _ConcreteBackend(BackendAdapter):
    """Minimal viable ``BackendAdapter`` subclass — just enough to
    instantiate. Mirrors the ``_ConcreteStage`` pattern in
    ``tests/test_adapters.py``."""

    def supports_url(self, url):
        return True

    def stat(self, url):
        return (BackendResult.OK, None)

    def list_dir(self, url):
        return (BackendResult.OK, [])

    def create_folder(self, url):
        return BackendResult.OK

    def copy(self, src_url, dst_url, overwrite=False):
        return BackendResult.OK

    def move(self, src_url, dst_url, overwrite=False):
        return BackendResult.OK

    def delete(self, url):
        return BackendResult.OK

    def normalize_url(self, url):
        return url

    def join_url(self, base, child):
        return base + "/" + child

    def parent_url(self, url):
        return None

    def basename(self, url):
        return url.rsplit("/", 1)[-1]


# ──────────────────────────────────────────────────────────────────────────────
# Public-API import surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_backend_adapter_importable(self):
        assert BackendAdapter is not None

    def test_backend_result_importable(self):
        assert BackendResult is not None

    def test_backend_file_flags_importable(self):
        assert BackendFileFlags is not None

    def test_backend_list_entry_importable(self):
        assert BackendListEntry is not None

    def test_backend_change_event_importable(self):
        assert BackendChangeEvent is not None

    def test_package_all_is_complete(self):
        # The ABC plus its data types form the minimum surface. Concrete
        # backends register themselves additively — ``LocalFSBackend``
        # joined the set in the content browser implementation step 2.
        import ovwidgets.content.backends as pkg
        assert {
            "BackendAdapter",
            "BackendChangeEvent",
            "BackendFileFlags",
            "BackendListEntry",
            "BackendResult",
        }.issubset(set(pkg.__all__))


# ──────────────────────────────────────────────────────────────────────────────
# BackendResult
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendResult:
    EXPECTED_MEMBERS = [
        "OK",
        "ERROR_NOT_FOUND",
        "ERROR_ACCESS_DENIED",
        "ERROR_ALREADY_EXISTS",
        "ERROR_CONNECTION",
        "ERROR_NOT_SUPPORTED",
        "ERROR",
    ]

    @pytest.mark.parametrize("name", EXPECTED_MEMBERS)
    def test_member_exists(self, name):
        assert hasattr(BackendResult, name)

    def test_member_count(self):
        assert len(list(BackendResult)) == len(self.EXPECTED_MEMBERS)

    def test_all_members_distinct(self):
        values = [BackendResult[name].value for name in self.EXPECTED_MEMBERS]
        assert len(set(values)) == len(values)

    def test_is_enum(self):
        # Plan §Step 1: "Enum, not string subclass."
        assert issubclass(BackendResult, Enum)

    def test_is_not_int_enum(self):
        # Plan §Step 1: prefer plain Enum over IntEnum to prevent
        # accidental int arithmetic.
        assert not issubclass(BackendResult, IntEnum)

    def test_is_not_str_subclass(self):
        # Plan §Step 1: deliberately NOT a str subclass — unlike
        # omni.client.Result. Prevents accidental string comparisons.
        assert not issubclass(BackendResult, str)

    def test_ok_is_truthy_via_equality(self):
        # Sanity: OK is a member and compares equal only to itself.
        assert BackendResult.OK == BackendResult.OK
        assert BackendResult.OK != BackendResult.ERROR

    def test_error_distinct_from_specific_errors(self):
        # The generic ERROR must not collide with any specific error.
        assert BackendResult.ERROR != BackendResult.ERROR_NOT_FOUND
        assert BackendResult.ERROR != BackendResult.ERROR_ACCESS_DENIED
        assert BackendResult.ERROR != BackendResult.ERROR_ALREADY_EXISTS
        assert BackendResult.ERROR != BackendResult.ERROR_CONNECTION
        assert BackendResult.ERROR != BackendResult.ERROR_NOT_SUPPORTED


# ──────────────────────────────────────────────────────────────────────────────
# BackendFileFlags
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendFileFlags:
    EXPECTED_MEMBERS = [
        "NONE",
        "IS_FOLDER",
        "IS_HIDDEN",
        "IS_SYMLINK",
        "IS_READABLE",
        "IS_WRITABLE",
    ]

    @pytest.mark.parametrize("name", EXPECTED_MEMBERS)
    def test_member_exists(self, name):
        assert hasattr(BackendFileFlags, name)

    def test_none_is_zero(self):
        assert BackendFileFlags.NONE.value == 0

    def test_all_non_none_members_nonzero(self):
        for name in self.EXPECTED_MEMBERS:
            if name == "NONE":
                continue
            assert BackendFileFlags[name].value != 0

    def test_all_members_distinct(self):
        # Each non-NONE flag must be a distinct bit.
        non_none = [BackendFileFlags[n] for n in self.EXPECTED_MEMBERS if n != "NONE"]
        values = [m.value for m in non_none]
        assert len(set(values)) == len(values)

    def test_flags_combine(self):
        combined = BackendFileFlags.IS_FOLDER | BackendFileFlags.IS_READABLE
        assert BackendFileFlags.IS_FOLDER in combined
        assert BackendFileFlags.IS_READABLE in combined
        assert BackendFileFlags.IS_HIDDEN not in combined
        assert BackendFileFlags.IS_WRITABLE not in combined

    def test_is_flag(self):
        # Plan §Step 1: "Store as a Flag, not IntFlag".
        assert issubclass(BackendFileFlags, Flag)

    def test_is_not_intflag(self):
        # Matches the ItemFlags / BadgeFlags convention in
        # ovwidgets.app/adapters.py — avoid silent int coercion.
        assert not issubclass(BackendFileFlags, IntFlag)

    def test_none_is_falsy(self):
        assert not BackendFileFlags.NONE

    def test_non_none_is_truthy(self):
        assert BackendFileFlags.IS_FOLDER

    def test_readable_and_writable_compose(self):
        # Typical local-file case: readable + writable, not hidden,
        # not symlink, not folder.
        rw = BackendFileFlags.IS_READABLE | BackendFileFlags.IS_WRITABLE
        assert BackendFileFlags.IS_READABLE in rw
        assert BackendFileFlags.IS_WRITABLE in rw
        assert BackendFileFlags.IS_FOLDER not in rw


# ──────────────────────────────────────────────────────────────────────────────
# BackendListEntry
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendListEntry:
    EXPECTED_FIELDS = ["name", "flags", "size", "modified_time", "created_time"]

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(BackendListEntry)

    def test_is_frozen(self):
        # Plan §Step 1 uses @dataclass(frozen=True).
        params = getattr(BackendListEntry, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_exact_field_set(self):
        names = [f.name for f in dataclasses.fields(BackendListEntry)]
        assert names == self.EXPECTED_FIELDS

    def test_construction(self):
        entry = BackendListEntry(
            name="foo.usd",
            flags=BackendFileFlags.IS_READABLE,
            size=1024,
            modified_time=1700000000.0,
            created_time=1600000000.0,
        )
        assert entry.name == "foo.usd"
        assert entry.flags == BackendFileFlags.IS_READABLE
        assert entry.size == 1024
        assert entry.modified_time == 1700000000.0
        assert entry.created_time == 1600000000.0

    def test_mutation_raises(self):
        entry = BackendListEntry(
            name="a",
            flags=BackendFileFlags.NONE,
            size=0,
            modified_time=0.0,
            created_time=0.0,
        )
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            entry.name = "b"

    def test_hashable(self):
        entry = BackendListEntry(
            name="a",
            flags=BackendFileFlags.NONE,
            size=0,
            modified_time=0.0,
            created_time=0.0,
        )
        s = {entry}
        assert entry in s

    def test_equality(self):
        e1 = BackendListEntry(
            name="a", flags=BackendFileFlags.NONE, size=0,
            modified_time=0.0, created_time=0.0,
        )
        e2 = BackendListEntry(
            name="a", flags=BackendFileFlags.NONE, size=0,
            modified_time=0.0, created_time=0.0,
        )
        assert e1 == e2

    def test_inequality_by_name(self):
        e1 = BackendListEntry(
            name="a", flags=BackendFileFlags.NONE, size=0,
            modified_time=0.0, created_time=0.0,
        )
        e2 = BackendListEntry(
            name="b", flags=BackendFileFlags.NONE, size=0,
            modified_time=0.0, created_time=0.0,
        )
        assert e1 != e2

    def test_folder_entry_composition(self):
        entry = BackendListEntry(
            name="Assets",
            flags=BackendFileFlags.IS_FOLDER | BackendFileFlags.IS_READABLE,
            size=0,
            modified_time=0.0,
            created_time=0.0,
        )
        assert BackendFileFlags.IS_FOLDER in entry.flags
        assert BackendFileFlags.IS_READABLE in entry.flags


# ──────────────────────────────────────────────────────────────────────────────
# BackendChangeEvent
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendChangeEvent:
    EXPECTED_FIELDS = ["url", "event_type", "entry"]

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(BackendChangeEvent)

    def test_is_frozen(self):
        params = getattr(BackendChangeEvent, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_exact_field_set(self):
        names = [f.name for f in dataclasses.fields(BackendChangeEvent)]
        assert names == self.EXPECTED_FIELDS

    def test_construction_with_entry(self):
        entry = BackendListEntry(
            name="a", flags=BackendFileFlags.NONE, size=0,
            modified_time=0.0, created_time=0.0,
        )
        evt = BackendChangeEvent(
            url="file:///tmp",
            event_type="created",
            entry=entry,
        )
        assert evt.url == "file:///tmp"
        assert evt.event_type == "created"
        assert evt.entry is entry

    def test_construction_with_none_entry(self):
        # Plan: entry may be None, e.g. deletion events where the
        # underlying backend doesn't retain the entry metadata.
        evt = BackendChangeEvent(
            url="file:///tmp",
            event_type="deleted",
            entry=None,
        )
        assert evt.entry is None

    def test_event_type_is_string(self):
        # Plan §Step 1: "kept as a string rather than an enum so
        # adapters can emit backend-specific subtypes".
        evt = BackendChangeEvent(
            url="file:///tmp",
            event_type="locked",   # Nucleus-only hypothetical subtype.
            entry=None,
        )
        assert isinstance(evt.event_type, str)

    def test_mutation_raises(self):
        evt = BackendChangeEvent(url="x", event_type="created", entry=None)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            evt.url = "y"

    def test_equality(self):
        a = BackendChangeEvent(url="x", event_type="created", entry=None)
        b = BackendChangeEvent(url="x", event_type="created", entry=None)
        assert a == b


# ──────────────────────────────────────────────────────────────────────────────
# BackendAdapter — abstract-ness and method presence
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendAdapterAbstract:
    """Verifies BackendAdapter is abstract and lists the exact set of
    abstract methods. ``subscribe_changes`` is concrete (default no-op)
    and must NOT appear in ``__abstractmethods__``."""

    REQUIRED_ABSTRACT = [
        "supports_url",
        "stat",
        "list_dir",
        "create_folder",
        "copy",
        "move",
        "delete",
        "normalize_url",
        "join_url",
        "parent_url",
        "basename",
    ]

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BackendAdapter()  # type: ignore[abstract]

    def test_abstractmethods_set_is_nonempty(self):
        assert BackendAdapter.__abstractmethods__

    @pytest.mark.parametrize("method_name", REQUIRED_ABSTRACT)
    def test_method_is_abstract(self, method_name):
        assert method_name in BackendAdapter.__abstractmethods__

    @pytest.mark.parametrize("method_name", REQUIRED_ABSTRACT)
    def test_method_exists(self, method_name):
        assert hasattr(BackendAdapter, method_name)

    def test_subscribe_changes_is_concrete(self):
        # Plan §Step 1: subscribe_changes has a default no-op
        # implementation — backends without change notification can
        # skip it.
        assert "subscribe_changes" not in BackendAdapter.__abstractmethods__
        assert hasattr(BackendAdapter, "subscribe_changes")

    def test_no_extra_abstract_methods(self):
        # The ABC's abstract-method set is exactly REQUIRED_ABSTRACT —
        # if a new abstract method is added the plan needs updating.
        assert set(BackendAdapter.__abstractmethods__) == set(self.REQUIRED_ABSTRACT)


# ──────────────────────────────────────────────────────────────────────────────
# BackendAdapter — concrete subclass behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestBackendAdapterConcrete:
    def test_subclass_instantiable(self):
        # Once every abstract method is implemented the subclass can
        # be instantiated.
        backend = _ConcreteBackend()
        assert isinstance(backend, BackendAdapter)

    def test_supports_url(self):
        backend = _ConcreteBackend()
        assert backend.supports_url("file:///tmp") is True

    def test_stat_returns_tuple(self):
        backend = _ConcreteBackend()
        result = backend.stat("file:///tmp")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == BackendResult.OK
        assert result[1] is None

    def test_list_dir_returns_empty(self):
        backend = _ConcreteBackend()
        code, entries = backend.list_dir("file:///tmp")
        assert code == BackendResult.OK
        assert entries == []

    def test_create_folder(self):
        backend = _ConcreteBackend()
        assert backend.create_folder("file:///tmp/new") == BackendResult.OK

    def test_copy(self):
        backend = _ConcreteBackend()
        assert backend.copy("a", "b") == BackendResult.OK

    def test_copy_overwrite_flag(self):
        backend = _ConcreteBackend()
        assert backend.copy("a", "b", overwrite=True) == BackendResult.OK

    def test_move(self):
        backend = _ConcreteBackend()
        assert backend.move("a", "b") == BackendResult.OK

    def test_delete(self):
        backend = _ConcreteBackend()
        assert backend.delete("file:///tmp/x") == BackendResult.OK

    def test_join_url(self):
        backend = _ConcreteBackend()
        assert backend.join_url("file:///tmp", "foo") == "file:///tmp/foo"

    def test_parent_url(self):
        # The minimal stub returns None; exercises the return-type
        # path ``Optional[str]``.
        backend = _ConcreteBackend()
        assert backend.parent_url("file:///tmp") is None

    def test_basename(self):
        backend = _ConcreteBackend()
        assert backend.basename("file:///tmp/foo.usd") == "foo.usd"

    def test_normalize_url_identity_for_stub(self):
        backend = _ConcreteBackend()
        assert backend.normalize_url("anything") == "anything"


# ──────────────────────────────────────────────────────────────────────────────
# BackendAdapter.subscribe_changes default — cancel-able object
# ──────────────────────────────────────────────────────────────────────────────

class TestSubscribeChangesDefault:
    def test_returns_object_with_cancel(self):
        backend = _ConcreteBackend()
        sub = backend.subscribe_changes("file:///tmp", lambda evt: None)
        assert hasattr(sub, "cancel")
        assert callable(sub.cancel)

    def test_cancel_is_idempotent(self):
        backend = _ConcreteBackend()
        sub = backend.subscribe_changes("file:///tmp", lambda evt: None)
        sub.cancel()
        sub.cancel()  # Second call must not raise.

    def test_del_does_not_raise(self):
        backend = _ConcreteBackend()
        sub = backend.subscribe_changes("file:///tmp", lambda evt: None)
        # Explicitly invoke the finaliser.
        sub.__del__()

    def test_callback_is_not_invoked(self):
        # Default no-op subscription must never fire the callback —
        # if it did, a backend without real change notification would
        # be silently fabricating events.
        backend = _ConcreteBackend()
        seen = []
        backend.subscribe_changes("file:///tmp", lambda evt: seen.append(evt))
        assert seen == []

    def test_subscribe_not_abstract_but_present(self):
        # Combined invariant: the method is on the ABC and not
        # abstract, so every concrete backend inherits the no-op
        # default unless it chooses to override.
        assert hasattr(BackendAdapter, "subscribe_changes")
        assert "subscribe_changes" not in BackendAdapter.__abstractmethods__
