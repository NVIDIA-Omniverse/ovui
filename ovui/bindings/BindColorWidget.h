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

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/ColorWidget.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/bind/BindColorWidget.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <utility>
#include <vector>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapColorWidget(module& m)
{
    constexpr const char* colorWidgetDoc = OMNIUI_PYBIND_CLASS_DOC(ColorWidget);
    static constexpr char colorWidgetConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ColorWidget, ColorWidget);
    class_<ColorWidget, Widget, ItemModelHelper, std::shared_ptr<ColorWidget>>(m, "ColorWidget", colorWidgetDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(ColorWidget); }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(ColorWidget, model);
        }))
        .def(init([](float r, float g, float b, kwargs kwargs) {
            std::vector<float> components{ { r, g, b } };
            OMNIUI_PYBIND_INIT(ColorWidget, SimpleListModel::create(std::move(components)));
        }))
        .def(init([](float r, float g, float b, float a, kwargs kwargs) {
            std::vector<float> components{ { r, g, b, a } };
            OMNIUI_PYBIND_INIT(ColorWidget, SimpleListModel::create(std::move(components)));
        }), colorWidgetConstructorDoc);
}
