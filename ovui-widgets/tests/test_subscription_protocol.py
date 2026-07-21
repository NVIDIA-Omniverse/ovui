# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: every concrete ``*Subscription`` class satisfies
:class:`ovui_data_adapters.common.SubscriptionProtocol`.

Step 26 (Rev 4 §10.5 / pre-planning §2.5.1 Option B): the data-adapters
refactor unified subscription handles under a structural protocol —
any object with a no-arg ``cancel()`` returning ``None`` qualifies.
The concrete public ``Subscription`` (Settings) and the private
``_*Subscription`` classes scattered through widgets / openusd
adapters all follow this shape; if a future change accidentally
renames ``cancel`` (or makes it take args / return non-``None``), the
protocol's ``runtime_checkable`` ``isinstance`` check stops yielding
``True`` for that class' instances.

The test inspects each class for a callable ``cancel`` attribute
without args (other than ``self``). Where construction is cheap and
self-contained, it also asserts ``isinstance(instance,
SubscriptionProtocol)`` to exercise the runtime-checkable contract on
a real instance — that catches inheritance bugs the static signature
inspection misses.
"""

from __future__ import annotations

import inspect
from typing import Type

import pytest
from ovui_data_adapters.common import SubscriptionProtocol

# Each entry is (importable dotted path, class name).
SUBSCRIPTION_CLASSES = [
    ("ovui_data_adapters.services.settings", "Subscription"),
    ("ovui_widgets.common.settings", "Subscription"),
    ("ovui_data_adapters.openusd.stage_adapter", "_StageSubscription"),
    ("ovui_data_adapters.openusd.layer_stack_adapter", "_LayerStackSubscription"),
    ("ovui_data_adapters.openusd.property_adapter", "_UsdPropertySubscription"),
    ("ovui_widgets.property.models.attribute_model", "_ValueChangeSubscription"),
    ("ovui_widgets.property.builders.builder_table", "_BuilderSubscription"),
    ("ovui_widgets.property.parts.control_state", "_HandlerSubscription"),
    ("ovui_widgets.property.widget.scheme_registry", "_WidgetSubscription"),
    ("ovui_widgets.property.widget.scheme_registry", "_DelegateSubscription"),
    ("ovui_widgets.content.widget.column_delegate", "_ColumnDelegateSubscription"),
    ("ovui_widgets.content.widget.column_delegate", "_ChangedSubscription"),
    ("ovui_widgets.common.testing.mock_property", "_MockPropertySubscription"),
    ("ovui_widgets.app.testing.mock_backend", "_MockBackendSubscription"),
]


def _resolve_class(module_path: str, class_name: str) -> Type[object]:
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    assert cls is not None, f"missing class: {module_path}.{class_name}"
    return cls


@pytest.mark.parametrize(
    "module_path,class_name",
    SUBSCRIPTION_CLASSES,
    ids=lambda v: v.split(".")[-1],
)
def test_subscription_class_has_cancel_method(module_path: str, class_name: str):
    """Every ``*Subscription`` class must expose a no-arg ``cancel()`` method."""
    cls = _resolve_class(module_path, class_name)
    cancel = getattr(cls, "cancel", None)
    assert callable(cancel), (
        f"{module_path}.{class_name}: missing callable ``cancel`` attribute "
        f"required by SubscriptionProtocol"
    )
    sig = inspect.signature(cancel)
    # ``cancel`` should accept only ``self`` (no required positional args
    # other than self). Default-valued kwargs are allowed.
    required = [
        name for name, p in sig.parameters.items()
        if name != "self"
        and p.default is inspect.Parameter.empty
        and p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    assert not required, (
        f"{module_path}.{class_name}.cancel: unexpected required args "
        f"{required!r} — SubscriptionProtocol expects ``cancel(self) -> None``"
    )


def test_concrete_subscription_satisfies_runtime_checkable_protocol():
    """``Settings.Subscription`` is the cheapest fully-constructible instance.

    Building one and asserting ``isinstance(instance, SubscriptionProtocol)``
    exercises the ``@runtime_checkable`` decorator end-to-end — proves the
    protocol object itself still works, not just that classes have the
    right shape.
    """
    import weakref

    from ovui_widgets.common.settings import Settings, Subscription

    s = Settings()
    sub = Subscription(weakref.ref(s), "fake.key", lambda *_: None)
    assert isinstance(sub, SubscriptionProtocol), (
        "Subscription instance must satisfy SubscriptionProtocol "
        "via runtime_checkable"
    )


def test_runtime_checkable_protocol_rejects_non_conforming_object():
    """A class without ``cancel`` must NOT satisfy the protocol — guards
    against an over-broad protocol that would silently accept anything.
    """
    class _NoCancel:
        def something_else(self):
            pass

    assert not isinstance(_NoCancel(), SubscriptionProtocol), (
        "objects without a ``cancel`` method must not satisfy "
        "SubscriptionProtocol"
    )


def test_runtime_checkable_protocol_accepts_minimal_duck_type():
    """Conversely, a tiny duck-typed object with just ``cancel(self)`` must
    pass — the protocol's whole point is structural conformance.
    """
    class _Tiny:
        def cancel(self) -> None:
            pass

    assert isinstance(_Tiny(), SubscriptionProtocol)
