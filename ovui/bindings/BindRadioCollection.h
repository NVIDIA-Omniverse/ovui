/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/RadioCollection.h>
#include <omni/ui/bind/BindRadioCollection.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/DocRadioCollection.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapRadioCollection(module& m)
{
    constexpr const char* radioCollectionDoc = OMNIUI_PYBIND_CLASS_DOC(RadioCollection);
    static constexpr char radioCollectionConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(RadioCollection, RadioCollection);

    class_<RadioCollection, ValueModelHelper, std::shared_ptr<RadioCollection>>(m, "RadioCollection", radioCollectionDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(RadioCollection, model)
             }),
             arg("model") = nullptr, radioCollectionConstructorDoc);
}
