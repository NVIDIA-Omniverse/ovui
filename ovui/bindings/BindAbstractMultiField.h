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

#include <omni/ui/AbstractMultiField.h>
#include <omni/ui/bind/BindAbstractMultiField.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAbstractMultiField(module& m)
{
    constexpr const char* abstractMultiFieldDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractMultiField);

    // The base class for MultiField
    class_<AbstractMultiField, Widget, ItemModelHelper, std::shared_ptr<AbstractMultiField>>(
        m, "AbstractMultiField", abstractMultiFieldDoc)
        .def_property("column_count", &AbstractMultiField::getColumnCount, &AbstractMultiField::setColumnCount,
                      OMNIUI_PYBIND_DOC_AbstractMultiField_columnCount)
        .def_property("h_spacing", &AbstractMultiField::getHSpacing, &AbstractMultiField::setHSpacing,
                      OMNIUI_PYBIND_DOC_AbstractMultiField_hSpacing)
        .def_property("v_spacing", &AbstractMultiField::getVSpacing, &AbstractMultiField::setVSpacing,
                      OMNIUI_PYBIND_DOC_AbstractMultiField_vSpacing)
        /* */;
}
