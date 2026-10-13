# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Application-contributed commands for the existing Inspector dispatcher."""

from dataclasses import dataclass
import re
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict


class Arguments(BaseModel):
    """Strict JSON arguments shared by built-in and application command providers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


@dataclass(frozen=True)
class Command:
    """A documented operation, invoked on the application's owning event loop.

    Handlers may be synchronous or async. Async handlers may await frames or
    I/O; other Inspector mutations remain queued until that handler completes.
    They must not call Inspector HTTP endpoints or enqueue work behind themselves.
    """

    name: str
    description: str
    arguments: type[BaseModel]
    handler: Callable[..., Any]
    read_only: bool = False
    category: str = "application"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name):
            raise ValueError("Command names must be lowercase identifiers")
        if not self.description.strip() or not callable(self.handler):
            raise ValueError("A command needs a description and a callable handler")
        if not issubclass(self.arguments, BaseModel):
            raise TypeError("Command arguments must be a Pydantic model")

    def describe(self):
        return {
            "name": self.name,
            "description": self.description,
            "method": "POST",
            "endpoint": f"/commands/{self.name}",
            "input_schema": self.arguments.model_json_schema(),
            "read_only": self.read_only,
            "category": self.category,
        }


class Registration:
    """Removable registration. Removal prevents queued calls from starting."""

    def __init__(self, command, remove):
        self.command = command
        self._remove = remove
        self.active = True

    def remove(self):
        self._remove(self)
