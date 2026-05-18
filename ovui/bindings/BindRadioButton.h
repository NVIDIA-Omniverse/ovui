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

#include <omni/ui/RadioButton.h>
#include <omni/ui/bind/BindRadioButton.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/DocRadioButton.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapRadioButton(module& m)
{
    constexpr const char* radioButtonDoc = OMNIUI_PYBIND_CLASS_DOC(RadioButton);
    constexpr char radioButtonConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(RadioButton, RadioButton);

    class_<RadioButton, Button, std::shared_ptr<RadioButton>>(m, "RadioButton", radioButtonDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(RadioButton) }), radioButtonConstructorDoc)
        .def_property("radio_collection", &RadioButton::getRadioCollection, &RadioButton::setRadioCollection,
                      OMNIUI_PYBIND_DOC_RadioButton_radioCollection);
}
