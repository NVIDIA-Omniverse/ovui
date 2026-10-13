# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Load the shared Inspector supplied by ovui, without bundling a second copy."""

import asyncio
import sys
from contextlib import contextmanager
from importlib import import_module
from importlib.metadata import entry_points
from importlib.resources import as_file


@contextmanager
def inspector_runtime():
    """Honor a configured Inspector first, otherwise use ovui's skill provider.

    The resource context stays alive for the application's lifetime, including
    when an installed skill must be extracted from a resource archive.
    """
    try:
        inspector = import_module("ovuiinspect")
    except ModuleNotFoundError as exc:
        if exc.name != "ovuiinspect":
            raise
    else:
        yield inspector
        return

    providers = list(entry_points(group="ovui.skills", name="omniverse-ui-inspector"))
    if len(providers) != 1:
        raise RuntimeError(
            "Install a matched ovui distribution with one omniverse-ui-inspector "
            "skill provider, or add the shared Inspector skill directory to PYTHONPATH."
        )
    resource = providers[0].load()()
    if not resource.joinpath("ovuiinspect", "__init__.py").is_file():
        raise RuntimeError(
            "The installed ovui Inspector skill has no runtime. For an editable ovui "
            "checkout, add its skills/omniverse-ui-inspector directory to PYTHONPATH."
        )
    with as_file(resource) as directory:
        search_path = str(directory)
        sys.path.insert(0, search_path)
        try:
            yield import_module("ovuiinspect")
        finally:
            sys.path.remove(search_path)


async def await_inspector_tasks(tasks):
    """Complete detached command cleanup before destroying host resources.

    Detach already cancels the commands. Further cancellation of the host must
    not cancel their cleanup a second time or release USD/media underneath it.
    """
    if not tasks:
        return
    completion = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while not completion.done():
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            cancelled = True
    completion.result()
    if cancelled:
        raise asyncio.CancelledError()
