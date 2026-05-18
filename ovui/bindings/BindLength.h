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

#include <omni/ui/Length.h>
#include <omni/ui/bind/BindLength.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapLength(module& m)
{
    constexpr const char* lengthDoc = OMNIUI_PYBIND_CLASS_DOC(Length);
    static constexpr char lengthConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Length, Length);

    class_<Length>(m, "Length", lengthDoc)
        .def(init<float, UnitType>())
        .def(init([](float value) -> Length {
            return { value, UnitType::ePixel };
        }))
        .def(init([](int32_t value) -> Length {
                 return { (float)value, UnitType::ePixel };
             }),
             lengthConstructorDoc)
        .def_readwrite("value", &Length::value, "(float) Value")
        .def_readwrite("unit", &Length::unit, "(:obj:`.UnitType.`) Unit.")
        .def("__repr__",
             [](const Length& self) {
                 return std::to_string(self.value) + (self.unit == UnitType::eFraction ? "fr" :
                                                      self.unit == UnitType::ePercent  ? "%" :
                                                                                         "px");
             })
        .def("__str__",
             [](const Length& self) {
                 return std::to_string(self.value) + (self.unit == UnitType::eFraction ? "fr" :
                                                      self.unit == UnitType::ePercent  ? "%" :
                                                                                         "px");
             })
        .def("__float__", [](const Length& self) { return self.value; })
        .def("__mul__",
             [](const Length& self, float v) {
                 return Length{ self.value * v, self.unit };
             },
             arg("value"))
        .def("__imul__",
             [](const Length& self, float v) {
                 return Length{ self.value * v, self.unit };
             },
             arg("value"))
        .def("__rmul__",
             [](const Length& self, float v) {
                 return Length{ v * self.value, self.unit };
             },
             arg("value"))
        .def("__truediv__",
             [](const Length& self, float v) {
                 return Length{ self.value / v, self.unit };
             },
             arg("value"))
        .def("__itruediv__",
             [](const Length& self, float v) {
                 return Length{ self.value / v, self.unit };
             },
             arg("value"))
        .def("__rtruediv__",
             [](const Length& self, float v) {
                 return Length{ v / self.value, self.unit };
             },
             arg("value"))
        .def("__add__", [](const Length& self, float v) -> float { return self.value + v; }, arg("value"))
        .def("__iadd__", [](const Length& self, float v) -> float { return self.value + v; }, arg("value"))
        .def("__radd__", [](const Length& self, float v) -> float { return v + self.value; }, arg("value"))
        .def("__sub__", [](const Length& self, float v) -> float { return self.value - v; }, arg("value"))
        .def("__isub__", [](const Length& self, float v) -> float { return self.value - v; }, arg("value"))
        .def("__rsub__", [](const Length& self, float v) -> float { return v - self.value; }, arg("value"));

    enum_<UnitType>(m, "UnitType", R"(
            Unit types.

            Widths, heights or other UI length can be specified in pixels or relative to window (or child window) size.
        )")
        .value("PIXEL", UnitType::ePixel)
        .value("PERCENT", UnitType::ePercent)
        .value("FRACTION", UnitType::eFraction);

    constexpr const char* percentDoc = OMNIUI_PYBIND_CLASS_DOC(Percent);
    static constexpr char percentConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Percent, Percent);
    class_<Percent, Length>(m, "Percent", percentDoc).def(init<float>(), arg("value"), percentConstructorDoc);

    constexpr const char* pixelDoc = OMNIUI_PYBIND_CLASS_DOC(Pixel);
    static constexpr char pixelConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Pixel, Pixel);
    class_<Pixel, Length>(m, "Pixel", pixelDoc).def(init<float>(), arg("value"), pixelConstructorDoc);

    constexpr const char* fractionDoc = OMNIUI_PYBIND_CLASS_DOC(Fraction);
    static constexpr char fractionConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Fraction, Fraction);
    class_<Fraction, Length>(m, "Fraction", fractionDoc).def(init<float>(), arg("value"), fractionConstructorDoc);
}
