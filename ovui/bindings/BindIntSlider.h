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
#include <omni/ui/IntSlider.h>
#include <omni/ui/bind/BindIntSlider.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapIntSlider(module& m)
{
    constexpr const char* intSliderDoc = OMNIUI_PYBIND_CLASS_DOC(IntSlider);
    constexpr char intSliderConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(IntSlider, IntSlider);
    constexpr const char* uIntSliderDoc = OMNIUI_PYBIND_CLASS_DOC(UIntSlider);
    constexpr char uIntSliderConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(UIntSlider, UIntSlider);

    class_<IntSlider, AbstractSlider, std::shared_ptr<IntSlider>>(m, "IntSlider", intSliderDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(IntSlider, model)
             }),
             arg("model") = nullptr, intSliderConstructorDoc)
        .def_property("min", &IntSlider::getMin, &IntSlider::setMin, OMNIUI_PYBIND_DOC_CommonIntSlider_min)
        .def_property("max", &IntSlider::getMax, &IntSlider::setMax, OMNIUI_PYBIND_DOC_CommonIntSlider_max);

    class_<UIntSlider, AbstractSlider, std::shared_ptr<UIntSlider>>(m, "UIntSlider", uIntSliderDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(UIntSlider, model)
             }),
             arg("model") = nullptr, uIntSliderConstructorDoc)
        .def_property("min", &UIntSlider::getMin, &UIntSlider::setMin, OMNIUI_PYBIND_DOC_CommonIntSlider_min)
        .def_property("max", &UIntSlider::getMax, &UIntSlider::setMax, OMNIUI_PYBIND_DOC_CommonIntSlider_max);
}
