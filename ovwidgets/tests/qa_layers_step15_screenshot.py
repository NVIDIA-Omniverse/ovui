# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 15.

Proves the stage attach / detach lifecycle: the same
:class:`LayerModel` is re-targeted across file-open calls — its event
subscription moves to the new adapter, the old tree is fully discarded
(no dangling :class:`LayerItem` references, no stale cache keys), and
``set_adapter(None)`` clears the tree without leaking subscriptions.

1. **Shot 1** — ``/tmp/ovgear_layers_step15_1.png``: file A open
   (``layers_step14_root.usda``). The Layers tree renders root →
   ``sub1`` → ``sub2``. Verifies that :meth:`LayerWindow.set_adapter`
   drove :meth:`LayerModel.set_adapter` end-to-end through
   :func:`Application.open_file`.
2. **Shot 2** — ``/tmp/ovgear_layers_step15_2.png``: file B open
   (``layers_step15_second.usda``) over the same window. The tree
   now shows file B's layers; the original model instance is reused
   (identity preserved), but its adapter handle and
   ``_sublayers_cache`` reflect B's identifiers only. Proves Step
   15's in-place retarget.
3. **Shot 3** — ``/tmp/ovgear_layers_step15_3.png``: detach via
   ``layer_window.set_adapter(None)``. The placeholder label
   returns, ``model._event_sub is None``, and the previously-attached
   adapter has zero subscribers left.

Weakref checks run against file A's ``LayerItem`` instances to prove
no dangling references survive the adapter swap — screenshots are the
visual proof; the asserts printed to stdout are the primary truth.
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import weakref

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.layers import LayerModel

USD_A = os.path.join(
    os.path.dirname(__file__), "data", "layers_step14_root.usda"
)
USD_B = os.path.join(
    os.path.dirname(__file__), "data", "layers_step15_second.usda"
)
OUT_1 = "/tmp/ovgear_layers_step15_1.png"
OUT_2 = "/tmp/ovgear_layers_step15_2.png"
OUT_3 = "/tmp/ovgear_layers_step15_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_A
    task = asyncio.ensure_future(app.run_async())

    await _drive(80)

    lw = app._layer_window
    if lw is None:
        raise RuntimeError("Application._layer_window not initialised")

    if app._property_window is not None:
        app._property_window.visible = False
    lw.visible = True
    if lw.window is not None:
        lw.window.focus()
        lw.window.frame.rebuild()
    await _drive(20)

    model = lw._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(
            f"Expected LayerModel after file A open, got {type(model).__name__}"
        )
    adapter_a = lw._adapter
    if adapter_a is None:
        raise RuntimeError("File A did not wire an adapter onto LayerWindow")

    root_a = model.root_item
    if root_a is None or not root_a.identifier.endswith("layers_step14_root.usda"):
        raise RuntimeError(
            f"Unexpected file A root: {root_a!r}"
        )
    if len(root_a.sublayers) != 1 or not root_a.sublayers[0].identifier.endswith(
        "layers_step14_sub1.usda"
    ):
        raise RuntimeError(
            f"File A sublayers wrong: {[s.identifier for s in root_a.sublayers]}"
        )

    # Weakrefs to file A's items — must be reclaimable once Step 15's
    # detach walk runs on the next adapter swap.
    ref_root_a = weakref.ref(root_a)
    ref_sub1_a = weakref.ref(root_a.sublayers[0])
    ref_sub2_a = weakref.ref(root_a.sublayers[0].sublayers[0])
    cache_a_keys = set(model._sublayers_cache.keys())

    print(f"File A attached; cache keys = {sorted(os.path.basename(k) for k in cache_a_keys)}")
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — open file B. ``Application.open_file`` drives
    # ``LayerWindow.set_adapter`` which re-targets the model in place.
    model_id_before = id(model)
    del root_a  # drop our local strong reference so weakrefs can die
    app.open_file(USD_B)
    await _drive(20)

    if lw._model is not model:
        raise RuntimeError(
            "LayerModel was rebuilt instead of re-targeted across open_file"
        )
    if id(lw._model) != model_id_before:
        raise RuntimeError("Model identity drifted across set_adapter")

    adapter_b = lw._adapter
    if adapter_b is adapter_a:
        raise RuntimeError("Adapter was not replaced by open_file")
    if model.adapter is not adapter_b:
        raise RuntimeError("Model still points at the old adapter")

    root_b = model.root_item
    if root_b is None or not root_b.identifier.endswith(
        "layers_step15_second.usda"
    ):
        raise RuntimeError(f"Unexpected file B root: {root_b!r}")
    # File B has exactly one sublayer that points to the step14 sub2 file.
    if len(root_b.sublayers) != 1 or not root_b.sublayers[0].identifier.endswith(
        "layers_step14_sub2.usda"
    ):
        raise RuntimeError(
            f"File B sublayers wrong: {[s.identifier for s in root_b.sublayers]}"
        )

    # File A's identifiers must be gone from the cache.
    cache_b_keys = set(model._sublayers_cache.keys())
    lingering = {k for k in cache_a_keys if "layers_step14_root" in k or "layers_step14_sub1" in k}
    if any(k in cache_b_keys for k in lingering):
        raise RuntimeError(
            f"Stale file-A identifiers survived in cache: {lingering & cache_b_keys}"
        )

    # Weakref check — file A's LayerItem instances must be collectable.
    gc.collect()
    if ref_root_a() is not None or ref_sub1_a() is not None or ref_sub2_a() is not None:
        raise RuntimeError(
            "File A LayerItem(s) still alive after re-target — leak"
        )
    print(
        f"File B attached; cache keys = "
        f"{sorted(os.path.basename(k) for k in cache_b_keys)}"
    )

    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — detach. set_adapter(None) must empty the tree and drop
    # the adapter subscription.
    subs_before = getattr(adapter_b, "_subscribers", None)
    lw.set_adapter(None)
    if lw.window is not None:
        lw.window.frame.rebuild()
    await _drive(20)

    if model.adapter is not None:
        raise RuntimeError("Detach failed — model still has an adapter")
    if model.root_item is not None or model.session_item is not None:
        raise RuntimeError("Detach failed — tree still populated")
    if model._event_sub is not None:
        raise RuntimeError("Detach failed — event subscription alive")
    if subs_before is not None and len(subs_before) != 0:
        raise RuntimeError(
            f"Old adapter retained {len(subs_before)} subscribers after detach"
        )

    print("Detached cleanly; tree empty, subscription cancelled")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Layers Step 15 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
