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

#include <omni/ui/platform/Assert.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/bind/BindStyleContainer.h>

#include <algorithm>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Fills the given dict with properties/values if they exist.
 */
template <typename T, typename U>
void fillStyleProperties(const StyleContainer& style,
                         size_t styleGroupIndex,
                         StyleContainer::State state,
                         pybind11::dict& dict)
{
    const auto& properties = StyleContainer::getNameToPropertyMapping<T>();

    for (size_t i = 0; i < static_cast<size_t>(T::eCount); ++i)
    {
        // Check the property exists
        U result;
        if (!style.resolveStyleProperty(styleGroupIndex, state, static_cast<T>(i), &result, false))
        {
            continue;
        }

        // Get the state property name
        auto found =
            find_if(properties.begin(), properties.end(), [i](const auto& p) { return p.second == static_cast<T>(i); });
        OMNIUI_ASSERT(found != properties.end());

        dict[found->first.c_str()] = result;
    }
}

pybind11::object convertStyleToPython(const std::shared_ptr<StyleContainer>& style)
{
    using namespace pybind11;
    const auto& states = StyleContainer::getNameToPropertyMapping<StyleContainer::State>();

    dict result;

    for (const auto& type : style->getCachedTypes())
    {
        for (const auto& name : style->getCachedNames(type))
        {
            size_t styleGroupIndex = style->getStyleStateGroupIndex(type, name);
            if (styleGroupIndex == SIZE_MAX)
            {
                continue;
            }

            std::string styleString = type;
            if (!name.empty())
            {
                styleString += "::" + name;
            }

            for (StyleContainer::State state : style->getCachedStates(styleGroupIndex))
            {
                // Convert state to string
                auto found = std::find_if(states.begin(), states.end(), [state](const auto& s) {
                    return s.second == static_cast<StyleContainer::State>(state);
                });
                OMNIUI_ASSERT(found != states.end());
                std::string stateString = found->first;

                if (stateString.empty())
                {
                    stateString = styleString;
                }
                else
                {
                    stateString = styleString + ":" + stateString;
                }

                dict properties;
                dict* target = stateString.empty() ? &result : &properties;
                fillStyleProperties<StyleFloatProperty, float>(*style, styleGroupIndex, state, *target);
                fillStyleProperties<StyleEnumProperty, uint32_t>(*style, styleGroupIndex, state, *target);
                fillStyleProperties<StyleColorProperty, uint32_t>(*style, styleGroupIndex, state, *target);
                fillStyleProperties<StyleStringProperty, const char*>(*style, styleGroupIndex, state, *target);

                if (!stateString.empty())
                {
                    result[stateString.c_str()] = *target;
                }
            }
        }
    }

    return result;
}

pybind11::object getPythonStyle(Widget& widget)
{
    const auto& style = widget.getStyle();
    if (!style)
    {
        return pybind11::cast<pybind11::none>(Py_None);
    }

    return convertStyleToPython(style);
}

pybind11::object getResolvedPythonStyle(const std::shared_ptr<Widget>& widget)
{
    const auto& style = Inspector::getResolvedStyle(widget);
    if (!style)
    {
        return pybind11::cast<pybind11::none>(Py_None);
    }

    return convertStyleToPython(style);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
