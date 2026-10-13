/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/ProgressBar.h>
#include <omni/ui/bind/BindProgressBar.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapProgressBar(module& m)
{
    constexpr const char* progressBarDoc = OMNIUI_PYBIND_CLASS_DOC(ProgressBar);
    static constexpr char progressBarConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ProgressBar, ProgressBar);
    class_<ProgressBar, Widget, ValueModelHelper, std::shared_ptr<ProgressBar>>(m, "ProgressBar", progressBarDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(ProgressBar, model)
             }),
             arg("model") = nullptr, progressBarConstructorDoc)
        /* */;
}
