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
#include <omni/ui/IntDrag.h>
#include <omni/ui/bind/BindIntDrag.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapIntDrag(module& m)
{
    constexpr const char* intDragDoc = OMNIUI_PYBIND_CLASS_DOC(IntDrag);
    static constexpr char intDragConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(IntDrag, IntDrag);
    constexpr const char* uIntDragDoc = OMNIUI_PYBIND_CLASS_DOC(UIntDrag);
    static constexpr char uIntDragConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(UIntDrag, UIntDrag);

    class_<IntDrag, IntSlider, std::shared_ptr<IntDrag>>(m, "IntDrag", intDragDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(IntDrag, model)
             }),
             arg("model") = nullptr, intDragConstructorDoc)
        .def_property("step", &IntDrag::getStep, &IntDrag::setStep, OMNIUI_PYBIND_DOC_IntDrag_step);

    class_<UIntDrag, UIntSlider, std::shared_ptr<UIntDrag>>(m, "UIntDrag", uIntDragDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(UIntDrag, model)
             }),
             arg("model") = nullptr, uIntDragConstructorDoc)
        .def_property("step", &UIntDrag::getStep, &UIntDrag::setStep, OMNIUI_PYBIND_DOC_UIntDrag_step);
}
