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

#include <omni/ui/Api.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/StyleStore.h>
#include <omni/ui/Widget.h>
#include <omni/ui/bind/Pybind.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Converts the given python property and adds it to the style.
 *
 * Please see the description of setPythonStyle for the explanation why it's inline.
 */
inline void addPropertyToStyle(StyleContainer& style,
                               const std::string& scopeName,
                               const std::string& propertyName,
                               const pybind11::handle& propertyValue)
{
    using namespace pybind11;

    StyleFloatProperty floatEnum = StyleContainer::getPropertyEnumeration<StyleFloatProperty>(propertyName);
    if (floatEnum != StyleFloatProperty::eCount)
    {
        if (isinstance<float_>(propertyValue) || isinstance<int_>(propertyValue))
        {
            style.merge({ scopeName, floatEnum, propertyValue.cast<float>() });
        }
        else if (isinstance<pybind11::str>(propertyValue))
        {
            style.merge({ scopeName, floatEnum, propertyValue.cast<std::string>().c_str() });
        }
        return;
    }

    StyleEnumProperty valueEnum = StyleContainer::getPropertyEnumeration<StyleEnumProperty>(propertyName);
    if (valueEnum != StyleEnumProperty::eCount)
    {
        style.merge({ scopeName, valueEnum, propertyValue.cast<uint32_t>() });
        return;
    }

    StyleStringProperty stringEnum = StyleContainer::getPropertyEnumeration<StyleStringProperty>(propertyName);
    if (stringEnum != StyleStringProperty::eCount)
    {
        std::string value = propertyValue.cast<std::string>();
        style.merge({ scopeName, stringEnum, value.c_str() });
        return;
    }

    StyleColorProperty colorEnum = StyleContainer::getPropertyEnumeration<StyleColorProperty>(propertyName);
    if (colorEnum != StyleColorProperty::eCount)
    {
        if (isinstance<int_>(propertyValue))
        {
            style.merge({ scopeName, colorEnum, propertyValue.cast<uint32_t>() });
        }
        else if (isinstance<pybind11::str>(propertyValue))
        {
            style.merge({ scopeName, colorEnum, propertyValue.cast<std::string>().c_str() });
        }
    }
}

inline StyleContainer getStyleContainer(const pybind11::handle& style)
{
    using namespace pybind11;

    StyleContainer convertedStyle;
    for (const auto& scope : style.cast<dict>())
    {
        auto scopeName = scope.first.cast<std::string>();
        const auto& scopeValue = scope.second;

        if (isinstance<dict>(scopeValue))
        {
            /* It's a scope */
            for (const auto& property : scopeValue.cast<dict>())
            {
                auto propertyName = property.first.cast<std::string>();
                const auto& propertyValue = property.second;

                addPropertyToStyle(convertedStyle, scopeName, propertyName, propertyValue);
            }
        }
        else
        {
            /* It's a property */
            addPropertyToStyle(convertedStyle, "", scopeName, scopeValue);
        }
    }

    return convertedStyle;
}

/**
 * @brief Converts Python style and applies it to the widget.
 *
 * In python we use regular dictionary as style. It can be like of this forms:
 *
 *    {"Button::okButton:hovered": {"color": 0xff000000}}
 *    {"color": 0xff000000}
 *
 * Unlike C++ version, it supports multiple scopes at once:
 *
 *    {"Button::red": {"color": 0xffff0000}, "Button::okButton:hovered": {"color": 0xff000000}}
 *
 * This function is inline because otherwise it would live in the omni.ui.python library and we would need to link all
 * the python bindings libraries against omni.ui.python. We can't link python bindings to another python bindings. The
 * best solution would be to create third library with this function.
 *
 * It's inline for OMNIUI_PYBIND_INIT_STYLES.
 */
inline void setWidgetStyle(Widget& widget, const pybind11::handle& style)
{
    widget.setStyle(getStyleContainer(style));
}


OMNIUI_API
pybind11::object convertStyleToPython(const std::shared_ptr<StyleContainer>& style);

/**
 * @brief Opposite to setWidgetStyle. Returns python dict that represents the style.
 */
OMNIUI_API
pybind11::object getPythonStyle(Widget& widget);

/**
 * @brief It returns the Python dict that is the style result of merging the
 * styles of all the parents and the local style.
 */
OMNIUI_API
pybind11::object getResolvedPythonStyle(const std::shared_ptr<Widget>& widget);

OMNIUI_NAMESPACE_CLOSE_SCOPE
