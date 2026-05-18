/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/AbstractSlider.h>
#include <omni/ui/bind/BindAbstractSlider.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAbstractSlider(module& m)
{
    enum_<AbstractSlider::DrawMode>(m, "SliderDrawMode", "")
        .value("FILLED", AbstractSlider::DrawMode::eFilled)
        .value("HANDLE", AbstractSlider::DrawMode::eHandle)
        .value("DRAG", AbstractSlider::DrawMode::eDrag);

    constexpr const char* abstractSliderDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractSlider);
    class_<AbstractSlider, Widget, ValueModelHelper, std::shared_ptr<AbstractSlider>>(
        m, "AbstractSlider", abstractSliderDoc);
}
