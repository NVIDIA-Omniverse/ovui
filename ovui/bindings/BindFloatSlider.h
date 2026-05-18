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
#include <omni/ui/FloatSlider.h>
#include <omni/ui/bind/BindFloatSlider.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFloatSlider(module& m)
{
    constexpr const char* floatSliderDoc = OMNIUI_PYBIND_CLASS_DOC(FloatSlider);
    static constexpr char floatSliderConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FloatSlider, FloatSlider);
    class_<FloatSlider, AbstractSlider, std::shared_ptr<FloatSlider>>(m, "FloatSlider", floatSliderDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FloatSlider, model)
             }),
             arg("model") = nullptr, floatSliderConstructorDoc)
        .def_property("min", &FloatSlider::getMin, &FloatSlider::setMin, OMNIUI_PYBIND_DOC_FloatSlider_min)
        .def_property("max", &FloatSlider::getMax, &FloatSlider::setMax, OMNIUI_PYBIND_DOC_FloatSlider_max)
        .def_property("step", &FloatSlider::getStep, &FloatSlider::setStep, OMNIUI_PYBIND_DOC_FloatSlider_step)
        .def_property("format", &FloatSlider::getFormat, &FloatSlider::setFormat, OMNIUI_PYBIND_DOC_FloatSlider_format)
        .def_property("precision", &FloatSlider::getPrecision, &FloatSlider::setPrecision, OMNIUI_PYBIND_DOC_FloatSlider_precision)
        /* */;
}
