/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include <omni/ui/StyleStore.h>
#include <omni/ui/bind/DocColorStore.h>
#include <omni/ui/bind/DocFloatStore.h>
#include <omni/ui/bind/DocStringStore.h>
#include <omni/ui/bind/DocStyleStore.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapColorStore(module& m)
{
    // No shared pointer becasue it's a singleton
    class_<ColorStore>(m, "ColorStore", OMNIUI_PYBIND_DOC_ColorStore)
        .def_static("store", [](std::string name, uint32_t color) { ColorStore::getInstance().store(name, color); },
                    arg("name"), arg("color"), OMNIUI_PYBIND_DOC_StyleStore_store)
        .def_static("find",
                    [](std::string name) {
                        size_t index = ColorStore::getInstance().find(name);
                        return ColorStore::getInstance().get(index);
                    },
                    arg("name"), OMNIUI_PYBIND_DOC_StyleStore_find)
        /* */;

    // No shared pointer becasue it's a singleton
    class_<FloatStore>(m, "FloatStore", OMNIUI_PYBIND_DOC_FloatStore)
        .def_static("store", [](std::string name, float value) { FloatStore::getInstance().store(name, value); },
                    arg("name"), arg("value"), OMNIUI_PYBIND_DOC_StyleStore_store)
        .def_static("find",
                    [](std::string name) {
                        size_t index = FloatStore::getInstance().find(name);
                        return FloatStore::getInstance().get(index);
                    },
                    arg("name"), OMNIUI_PYBIND_DOC_StyleStore_find)
        /* */;

    // No shared pointer becasue it's a singleton
    class_<StringStore>(m, "StringStore", OMNIUI_PYBIND_DOC_StringStore)
        .def_static("store", [](std::string name, const char* string) { StringStore::getInstance().store(name, string); },
                    arg("name"), arg("string"), OMNIUI_PYBIND_DOC_StyleStore_store)
        .def_static("find",
                    [](std::string name) {
                        size_t index = FloatStore::getInstance().find(name);
                        return StringStore::getInstance().get(index);
                    },
                    arg("name"), OMNIUI_PYBIND_DOC_StyleStore_find)
        /* */;
}
