/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_CallbackHelper                                                                                                                                                                                                                                                                                                                        \
    "Base class for the objects that should automatically clean up the callbacks. It collects all the callbacks created with OMNIUI_CALLBACK and is able to clean all of them. We use it to destroy the callbacks if the parent object is destroyed, and it helps to break circular references created by pybind11 because pybind11 can't use weak pointers.\n" \
    "\n"
