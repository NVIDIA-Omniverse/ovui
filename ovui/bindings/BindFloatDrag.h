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

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/FloatDrag.h>
#include <omni/ui/bind/BindFloatDrag.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFloatDrag(module& m)
{
    constexpr const char* floatDragDoc = OMNIUI_PYBIND_CLASS_DOC(FloatDrag);
    static constexpr char floatDragConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FloatDrag, FloatDrag);
    class_<FloatDrag, FloatSlider, std::shared_ptr<FloatDrag>>(m, "FloatDrag", floatDragDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FloatDrag, model)
             }),
             arg("model") = nullptr, floatDragConstructorDoc)
        /* */;
}
