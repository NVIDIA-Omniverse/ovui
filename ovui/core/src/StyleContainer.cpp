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

#include <omni/ui/Profile.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/StyleStore.h>
#include <omni/ui/Workspace.h>

#include <algorithm>
#include <iterator>
#include <stdexcept>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Behaves like printf, returns std::string
 */
template <typename... Args>
static std::string string_format(const std::string& format, Args... args)
{
    // Extra space for '\0'
    int size = snprintf(nullptr, 0, format.c_str(), args...) + 1;
    if (size <= 0)
    {
        throw std::runtime_error("Error during formatting.");
    }
    std::unique_ptr<char[]> buf(new char[size]);
    snprintf(buf.get(), size, format.c_str(), args...);
    // We don't want the '\0' inside
    return std::string(buf.get(), buf.get() + size - 1);
}

/**
 * @brief A helper to merge one indexed data to another. The values from source will overwrite the destination.
 */
template <typename T, typename U>
static void mergeIndexedValues(std::vector<U>& destinationValues,
                               std::array<size_t, static_cast<size_t>(T::eCount)>& destinationIndices,
                               const std::vector<U>& sourceValues,
                               const std::array<size_t, static_cast<size_t>(T::eCount)>& sourceIndices)
{
    for (size_t state = 0; state < static_cast<size_t>(T::eCount); ++state)
    {
        size_t sourceIndex = sourceIndices[state];
        if (sourceIndex == SIZE_MAX)
        {
            continue;
        }

        auto sourceValue = sourceValues[sourceIndex];

        size_t& destinationIndex = destinationIndices[state];
        if (destinationIndex == SIZE_MAX)
        {
            destinationIndex = destinationValues.size();
            destinationValues.push_back(sourceValue);
            continue;
        }

        destinationValues[destinationIndex] = sourceValue;
    }
}

/**
 * @brief A helper to extract property from indexed data.
 */
template <typename T, typename U>
static bool getIndexedValue(const std::vector<U>& values,
                            const std::array<size_t, static_cast<size_t>(T::eCount)>& indices,
                            T property,
                            U* result)
{
    size_t index = indices[static_cast<size_t>(property)];
    if (index != SIZE_MAX)
    {
        *result = values[index];
        return true;
    }

    return false;
}

/**
 * @brief A helper to put the given property to the indexed data.
 */
template <typename T, typename U>
static void _initializeIndexedValue(std::vector<U>& values,
                                    std::array<size_t, static_cast<size_t>(T::eCount)>& indices,
                                    T property,
                                    U value)
{
    size_t& index = indices[static_cast<size_t>(property)];
    if (index == SIZE_MAX)
    {
        index = values.size();
        values.push_back(value);
    }
    else
    {
        values[index] = value;
    }
}

const StyleContainer& StyleContainer::defaultStyle()
{
    static StyleContainer style;
    if (!style.valid())
    {
        // Button
        style.merge({ "Button", StyleColorProperty::eBackgroundColor, 0xff292929, StyleFloatProperty::eMargin, 3.0f,
                      StyleFloatProperty::ePadding, 3.0f, StyleFloatProperty::eBorderRadius, 2.0f });
        style.merge({ "Button.Label", StyleColorProperty::eColor, 0xffcccccc });
        style.merge({ "Button:hovered", StyleColorProperty::eBackgroundColor, 0xff9e9e9e });
        style.merge({ "Button:pressed", StyleColorProperty::eBackgroundColor, 0xc28a8778 });
        style.merge({ "Button:checked", StyleColorProperty::eBackgroundColor, 0xc28a8778 });

        style.merge(
            { "CheckBox", StyleColorProperty::eColor, 0xff333333, StyleColorProperty::eBackgroundColor, 0xffcccccc });
        style.merge({ "CheckBox:disabled", StyleColorProperty::eColor, 0xff737373, StyleColorProperty::eBackgroundColor,
                      0xff8c8c8c });

        // RadioButton
        // TODO: make it always image-based, now it's like a button
        style.merge({ "RadioButton", StyleColorProperty::eBackgroundColor, 0xff292929, StyleFloatProperty::eMargin,
                      3.0f, StyleFloatProperty::ePadding, 3.0f, StyleFloatProperty::eBorderRadius, 2.0f });
        style.merge({ "RadioButton.Label", StyleColorProperty::eColor, 0xffcccccc });
        style.merge({ "RadioButton:hovered", StyleColorProperty::eBackgroundColor, 0xff9e9e9e });
        style.merge({ "RadioButton:pressed", StyleColorProperty::eBackgroundColor, 0xc28a8778 });
        style.merge({ "RadioButton:checked", StyleColorProperty::eBackgroundColor, 0xc28a8778 });

        // Rectangle
        style.merge({ "Rectangle", StyleColorProperty::eBackgroundColor, 0xff292929 });

        // ScrollingFrame
        style.merge({ "ScrollingFrame", StyleFloatProperty::eScrollbarSize, 12.0f });

        // Field
        style.merge(
            { "Field", StyleColorProperty::eBackgroundColor, 0xff24211f, StyleFloatProperty::eBorderRadius, 2.0f });
        style.merge({ "Field:pressed", StyleColorProperty::eBackgroundColor, 0xff383838 });

        // CollapsableFrame
        style.merge({ "CollapsableFrame", StyleColorProperty::eBackgroundColor, 0xff333333,
                      StyleColorProperty::eSecondaryColor, 0xff333333, StyleColorProperty::eColor, 0xffcccccc,
                      StyleFloatProperty::eBorderRadius, 2.0f, StyleFloatProperty::ePadding, 3.0f });
        style.merge({ "CollapsableFrame:hovered", StyleColorProperty::eSecondaryColor, 0xff383838 });
        style.merge({ "CollapsableFrame:hovered", StyleColorProperty::eSecondaryColor, 0xff4d4d4d });

        // TreeView
        style.merge({ "TreeView", StyleColorProperty::eBackgroundColor, 0xff23211f,
                      // Item BG when hovered
                      StyleColorProperty::eBackgroundSelectedColor, 0x664f4d43u,
                      // The color of the resizing line
                      StyleColorProperty::eSecondarySelectedColor, 0xffb0703b });
        style.merge({ "TreeView:selected", StyleColorProperty::eBackgroundColor, 0xff8a8777 });
        style.merge({ "TreeView.Item", StyleColorProperty::eColor, 0xff8a8777 });
        style.merge({ "TreeView.Item:selected", StyleColorProperty::eColor, 0xff23211f });
        style.merge({ "TreeView.Header", StyleColorProperty::eBackgroundColor, 0xff343432, StyleColorProperty::eColor,
                      0xffcccccc, StyleFloatProperty::eFontSize, 13.0f });

        // Tooltip
        style.merge({ "Tooltip", StyleColorProperty::eBackgroundColor, 0xffc7f5fc, StyleColorProperty::eColor,
                      0xff4b493b, StyleFloatProperty::eBorderWidth, 1.0f, StyleFloatProperty::eMarginWidth, 2.0f,
                      StyleFloatProperty::eMarginHeight, 1.0f, StyleFloatProperty::ePadding, 1.0f });

        float menuBarMarginWidth = 6.0f;
        float menuBarMarginHeight = 4.0f;

        // Compensate dpiScale for menu bar.
        // We need to do it because the ImGui menu bar doesn't multiply margin
        // by the scale, and it's 6 for any scale. If we ignore this fact in our
        // modern menu, it's not aligned with the righten side of the menu bar
        // (cache: off, live sync: off). We need to remove it as soon as we move
        // righten side of the menu bar to python.
        menuBarMarginWidth = menuBarMarginWidth / Workspace::getDpiScale();
        menuBarMarginHeight = menuBarMarginHeight / Workspace::getDpiScale();

        // Menu
        style.merge({ "Menu.Window", StyleColorProperty::eBackgroundColor, 0xff3d3b38, StyleFloatProperty::ePadding,
                      0.0f, StyleFloatProperty::eBorderRadius, 4.0f });
        style.merge({ "MenuBar.Item", StyleFloatProperty::eMarginWidth, menuBarMarginWidth,
                      StyleFloatProperty::eMarginHeight, menuBarMarginHeight });
        style.merge({ "Menu.Title", StyleColorProperty::eBackgroundColor, 0xff2a2825, StyleFloatProperty::eBorderRadius,
                      4.0f, StyleEnumProperty::eCornerFlag, 3U });
        style.merge({ "Menu.Title.Line", StyleColorProperty::eColor, 0xff373635});
        style.merge({ "Menu.Separator", StyleColorProperty::eColor, 0xff707070, StyleFloatProperty::eMarginWidth, 6.0f });
        style.merge({ "Menu.Item", StyleColorProperty::eColor, 0xffcccccc, StyleFloatProperty::eMarginHeight, 2.0f,
                      StyleFloatProperty::eMarginWidth, 4.0f });
        style.merge({ "Menu.Item:disabled", StyleColorProperty::eColor, 0xff6f6f6f });
        style.merge({ "Menu.Item.CheckMark", StyleColorProperty::eColor, 0xffcccccc, StyleFloatProperty::eMarginWidth,
                      5.0f, StyleStringProperty::eImageUrl, "${kit}/resources/icons/RenderCheckMark.svg" });
        style.merge({ "Menu.Item.CheckMark:disabled", StyleColorProperty::eColor, 0xff6f6f6f });
        style.merge({ "Menu.Item.ExpandMark", StyleColorProperty::eColor, 0xffcccccc, StyleFloatProperty::eMarginWidth,
                      5.0f, StyleStringProperty::eImageUrl, "${kit}/resources/icons/ExpandMark.svg" });
        style.merge({ "Menu.Item.ExpandMark:disabled", StyleColorProperty::eColor, 0xff6f6f6f });
        style.merge({ "Menu.Item.CloseMark", StyleColorProperty::eColor, 0x0u, StyleFloatProperty::eMargin, 3.0f,
                      StyleStringProperty::eImageUrl, "${kit}/resources/icons/CloseMark.svg" });
        style.merge({ "Menu.Item.CloseMark:checked", StyleColorProperty::eColor, 0xffcccccc });
    }

    return style;
}

bool StyleContainer::valid() const
{
    return !m_styleBlocks.empty() && !m_styleStateGroups.empty();
}

void StyleContainer::merge(const StyleContainer& style)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    // Create new nodes and merge content
    for (const auto& type : style.m_styleStateGroupIndicesMap)
    {
        const std::string& typeStr = type.first;
        auto& destinationNames = m_styleStateGroupIndicesMap[typeStr];
        for (const auto& name : type.second)
        {
            const std::string& nameStr = name.first;

            // Check if we already have blocks with the same type and the same name,
            auto emplaced = destinationNames.emplace(std::piecewise_construct, std::forward_as_tuple(nameStr),
                                                     std::forward_as_tuple(m_styleStateGroups.size()));
            if (emplaced.second)
            {
                // Insertion happened
                if (typeStr.empty() && nameStr.empty())
                {
                    // It's a global override. We need to save its index.
                    m_globalOverrideIndex = m_styleStateGroups.size();
                }

                // Create a new block of indices and set them to SIZE_MAX to indicate they don't exist yet.
                m_styleStateGroups.emplace_back();
            }

            // The destination we are going put blocks.
            // First argument of emplaced result has the iterator to the found/emplaced element.
            auto& destinationIndices = m_styleStateGroups[emplaced.first->second];
            // The source where we are going to take blocks.
            const auto& sourceIndices = style.m_styleStateGroups[name.second];

            for (size_t state = 0; state < static_cast<size_t>(State::eCount); ++state)
            {
                if (sourceIndices[state] == SIZE_MAX)
                {
                    // Nothing in the source. Skip.
                    continue;
                }

                const auto& sourceBlock = style.m_styleBlocks[sourceIndices[state]];

                if (destinationIndices[state] == SIZE_MAX)
                {
                    // Nothing in the destination. Just keep the source and save the Id
                    destinationIndices[state] = m_styleBlocks.size();
                    m_styleBlocks.push_back(sourceBlock);
                    continue;
                }

                // Merge source to the destination
                auto& destinationBlock = m_styleBlocks[destinationIndices[state]];
                destinationBlock.merge(sourceBlock);
            }
        }
    }

    // Set parents
    // TODO: it's super slow, we have to optimize it.
    for (auto& type : m_styleStateGroupIndicesMap)
    {
        auto& names = type.second;

        auto parentFound = names.find({});
        size_t parentGroupIndex;
        if (parentFound != names.end())
        {
            parentGroupIndex = parentFound->second;
        }
        else
        {
            parentGroupIndex = SIZE_MAX;
        }

        for (const auto& name : names)
        {
            const std::string& nameStr = name.first;
            if (nameStr.empty())
            {
                // TODO: Set all to none
                continue;
            }

            auto& indices = m_styleStateGroups[name.second];
            // This is different from StyleBlock::setParentIndex that is later in this code. Now we save the parent of
            // the group. We need to have it in the case if the group doesn't have any block.
            indices.setParentIndex(parentGroupIndex);

            for (size_t state = 0; state < static_cast<size_t>(State::eCount); ++state)
            {
                if (indices[state] == SIZE_MAX)
                {
                    continue;
                }

                if (parentFound == names.end() || m_styleStateGroups[parentGroupIndex][state] == SIZE_MAX)
                {
                    // If parent not found or parent doesn't have the same state. We need to save the parent of the
                    // block because when we resolve the block we know nothing about groups and we want to get the block
                    // index fast without query the geoup.
                    m_styleBlocks[indices[state]].setParentIndex(SIZE_MAX);
                    continue;
                }

                size_t parentIndex = m_styleStateGroups[parentGroupIndex][state];
                m_styleBlocks[indices[state]].setParentIndex(parentIndex);
            }
        }
    }

    // Set cascading
    // TODO: it's super slow, we have to optimize it.
    for (auto& type : m_styleStateGroupIndicesMap)
    {
        auto& names = type.second;

        for (const auto& name : names)
        {
            auto& indices = m_styleStateGroups[name.second];

            size_t normalIndex = static_cast<size_t>(State::eNormal);

            for (size_t state = normalIndex + 1; state < static_cast<size_t>(State::eCount); ++state)
            {
                if (indices[normalIndex] == SIZE_MAX || indices[state] == SIZE_MAX)
                {
                    continue;
                }

                m_styleBlocks[indices[state]].setCascadeIndex(indices[normalIndex]);
            }
        }
    }
}

size_t StyleContainer::getStyleStateGroupIndex(const std::string& type, const std::string& name) const
{
    auto typeFound = m_styleStateGroupIndicesMap.find(type);
    if (typeFound == m_styleStateGroupIndicesMap.end())
    {
        return SIZE_MAX;
    }

    const auto& names = typeFound->second;
    auto nameFound = names.find(name);
    if (nameFound == names.end())
    {
        nameFound = names.find({});
        if (nameFound == names.end())
        {
            return SIZE_MAX;
        }
    }

    return nameFound->second;
}

std::vector<std::string> StyleContainer::getCachedTypes() const
{
    std::vector<std::string> v;
    std::transform(m_styleStateGroupIndicesMap.begin(), m_styleStateGroupIndicesMap.end(), std::back_inserter(v),
                   [](const auto& m) { return m.first; });
    std::sort(v.begin(), v.end());
    return v;
}

std::vector<std::string> StyleContainer::getCachedNames(const std::string& type) const
{
    auto found = m_styleStateGroupIndicesMap.find(type);
    if (found == m_styleStateGroupIndicesMap.end())
    {
        return {};
    }

    std::vector<std::string> v;
    std::transform(
        found->second.begin(), found->second.end(), std::back_inserter(v), [](const auto& m) { return m.first; });
    std::sort(v.begin(), v.end());
    return v;
}

std::vector<StyleContainer::State> StyleContainer::getCachedStates(size_t styleStateGroupIndex) const
{
    if (styleStateGroupIndex == SIZE_MAX)
    {
        return {};
    }

    const auto& styleStateGroup = m_styleStateGroups[styleStateGroupIndex];
    std::vector<State> v;

    for (size_t i = 0; i < static_cast<size_t>(State::eCount); ++i)
    {
        size_t blockIndex = styleStateGroup[i];
        if (blockIndex == SIZE_MAX)
        {
            continue;
        }

        v.push_back(static_cast<State>(i));
    }

    return v;
}

template <typename T, typename U>
bool StyleContainer::resolveStyleProperty(
    size_t styleStateGroupIndex, StyleContainer::State state, T property, U* result, bool checkParentGroup) const
{
    // The difference between this method and another _resolveStyleProperty is that here we pick the correct group.
    // Sometimes there are no named groups, or there is a named group, but there are no parents. Here we find the
    // correct group depending on the input. We don't resolve properties here.
    if (m_globalOverrideIndex != styleStateGroupIndex)
    {
        // Check the global override first.
        if (resolveStyleProperty(m_globalOverrideIndex, state, property, result, checkParentGroup))
        {
            // We have an override.
            return true;
        }
    }

    if (styleStateGroupIndex == SIZE_MAX)
    {
        return false;
    }

    const auto& styleStateGroup = m_styleStateGroups[styleStateGroupIndex];

    // We need to find the index of the block.
    size_t blockIndex = styleStateGroup[static_cast<size_t>(state)];
    if (checkParentGroup && blockIndex == SIZE_MAX)
    {
        // If not found, check the parent group, the same state.
        size_t parentStyleStateGroupIndex = styleStateGroup.getParentIndex();
        if (parentStyleStateGroupIndex != SIZE_MAX)
        {
            const auto& parentStyleStateGroup = m_styleStateGroups[parentStyleStateGroupIndex];
            blockIndex = parentStyleStateGroup[static_cast<size_t>(state)];
        }
    }

    if (checkParentGroup && blockIndex == SIZE_MAX)
    {
        // If not found, try current group, normal state.
        blockIndex = styleStateGroup[static_cast<size_t>(State::eNormal)];
    }

    return _resolveStyleProperty(blockIndex, property, result, checkParentGroup);
}

template <>
OMNIUI_API const std::unordered_map<std::string, StyleFloatProperty>& StyleContainer::getNameToPropertyMapping<StyleFloatProperty>()
{
    static const std::unordered_map<std::string, StyleFloatProperty> kProperties = {
        { "border_radius", StyleFloatProperty::eBorderRadius },
        { "border_width", StyleFloatProperty::eBorderWidth },
        { "font_size", StyleFloatProperty::eFontSize },
        { "margin", StyleFloatProperty::eMargin },
        { "margin_width", StyleFloatProperty::eMarginWidth },
        { "margin_height", StyleFloatProperty::eMarginHeight },
        { "padding", StyleFloatProperty::ePadding },
        { "padding_width", StyleFloatProperty::ePaddingWidth },
        { "padding_height", StyleFloatProperty::ePaddingHeight },
        { "secondary_padding", StyleFloatProperty::eSecondaryPadding },
        { "scrollbar_size", StyleFloatProperty::eScrollbarSize },
        { "shadow_thickness", StyleFloatProperty::eShadowThickness},
        { "shadow_offset_x", StyleFloatProperty::eShadowOffsetX },
        { "shadow_offset_y", StyleFloatProperty::eShadowOffsetY },
    };

    return kProperties;
}

template <>
OMNIUI_API const std::unordered_map<std::string, StyleColorProperty>& StyleContainer::getNameToPropertyMapping<StyleColorProperty>()
{
    static const std::unordered_map<std::string, StyleColorProperty> kProperties = {
        { "background_color", StyleColorProperty::eBackgroundColor },
        { "background_gradient_color", StyleColorProperty::eBackgroundGradientColor },
        { "background_selected_color", StyleColorProperty::eBackgroundSelectedColor },
        { "border_color", StyleColorProperty::eBorderColor },
        { "color", StyleColorProperty::eColor },
        { "selected_color", StyleColorProperty::eSelectedColor },
        { "secondary_color", StyleColorProperty::eSecondaryColor },
        { "secondary_selected_color", StyleColorProperty::eSecondarySelectedColor },
        { "secondary_background_color", StyleColorProperty::eSecondaryBackgroundColor },
        { "debug_color", StyleColorProperty::eDebugColor },
        { "shadow_color", StyleColorProperty::eShadowColor },
    };

    return kProperties;
}

template <>
OMNIUI_API const std::unordered_map<std::string, StyleEnumProperty>& StyleContainer::getNameToPropertyMapping<StyleEnumProperty>()
{
    static const std::unordered_map<std::string, StyleEnumProperty> kProperties = {
        { "corner_flag", StyleEnumProperty::eCornerFlag },
        { "alignment", StyleEnumProperty::eAlignment },
        { "fill_policy", StyleEnumProperty::eFillPolicy },
        { "draw_mode", StyleEnumProperty::eDrawMode },
        { "stack_direction", StyleEnumProperty::eStackDirection },
        { "shadow_flag", StyleEnumProperty::eShadowFlag },
    };

    return kProperties;
}

template <>
OMNIUI_API const std::unordered_map<std::string, StyleStringProperty>& StyleContainer::getNameToPropertyMapping<StyleStringProperty>()
{
    static const std::unordered_map<std::string, StyleStringProperty> kProperties = {
        { "image_url", StyleStringProperty::eImageUrl },
        { "font", StyleStringProperty::eFont },
        { "layout_policy", StyleStringProperty::eLayoutPolicy },
    };

    return kProperties;
}

template <>
OMNIUI_API const std::unordered_map<std::string, StyleContainer::State>& StyleContainer::getNameToPropertyMapping<StyleContainer::State>()
{
    static const std::unordered_map<std::string, State> kStates = {
        { "", State::eNormal },           { "hovered", State::eHovered },   { "pressed", State::ePressed },
        { "disabled", State::eDisabled }, { "selected", State::eSelected }, { "checked", State::eChecked },
        { "drop", State::eDrop },
    };

    return kStates;
}

template <typename T>
T StyleContainer::getPropertyEnumeration(const std::string& property)
{
    const auto& properties = StyleContainer::getNameToPropertyMapping<T>();

    auto found = properties.find(property);
    if (found != properties.end())
    {
        return found->second;
    }

    return T::eCount;
}

template <typename T, typename U>
bool StyleContainer::_resolveStyleProperty(size_t blockIndex, T property, U* result, bool checkParentGroup) const
{
    // The difference between this method and another _resolveStyleProperty is that here we work with properties. If
    // this block doesn't have the requested property, we have links to cascading and parent blocks.
    if (blockIndex == SIZE_MAX || blockIndex >= m_styleBlocks.size())
    {
        return false;
    }

    if (m_styleBlocks[blockIndex].get(property, result))
    {
        return true;
    }

    // Not found, try parent
    size_t blockIndexParent = m_styleBlocks[blockIndex].getParentIndex();
    if (blockIndexParent != SIZE_MAX && m_styleBlocks[blockIndexParent].get(property, result))
    {
        return true;
    }

    if (!checkParentGroup)
    {
        return false;
    }

    // Not found, try cascade, and it will try its parent, etc.
    size_t blockIndexCascade = m_styleBlocks[blockIndex].getCascadeIndex();
    if (_resolveStyleProperty(blockIndexCascade, property, result, checkParentGroup))
    {
        return true;
    }

    // And if cascade doesn't work, try the cascade of parent.
    if (blockIndexParent != SIZE_MAX)
    {
        blockIndexCascade = m_styleBlocks[blockIndexParent].getCascadeIndex();
        return _resolveStyleProperty(blockIndexCascade, property, result, checkParentGroup);
    }

    return false;
}

size_t StyleContainer::_createStyleStateGroup(const std::string& type, const std::string& name)
{
    auto& names = m_styleStateGroupIndicesMap[type];
    auto emplaced = names.emplace(
        std::piecewise_construct, std::forward_as_tuple(name), std::forward_as_tuple(m_styleStateGroups.size()));
    if (emplaced.second)
    {
        // Insertion happened.
        if (type.empty() && name.empty())
        {
            // It's a global override. We need to save its index.
            m_globalOverrideIndex = m_styleStateGroups.size();
        }

        // Create a new block of indices.
        m_styleStateGroups.emplace_back();
    }

    // First argument of emplaced result has the iterator to the found/emplaced element.
    return emplaced.first->second;
}

void StyleContainer::_parseScopeString(const std::string& input, std::string& type, std::string& name, State& state)
{
    // The scope string looks like this: "Widget::name:state". The format of the scope string is from
    // https://doc.qt.io/qt-5/stylesheet-syntax.html

    std::string stateStr;

    // Parse name
    size_t colonPosition = input.find(':');
    if (colonPosition == std::string::npos)
    {
        // No colon. The whole string is type.
        type = input;
    }
    else
    {
        // Type is the substring before colon
        type = input.substr(0, colonPosition);

        // The rest of the string
        std::string buffer = input.substr(colonPosition + 1);
        if (buffer.length() > 1 && buffer[0] == ':')
        {
            // We are here because after the type there is double colon. So the next word is name.
            colonPosition = buffer.find(':', 1);
            name = buffer.substr(1, colonPosition - 1);
            if (colonPosition == std::string::npos)
            {
                // There is no more colon. And it means there is no state.
                buffer.clear();
            }
            else
            {
                // The rest of the string is the state.
                buffer = buffer.substr(colonPosition + 1);
            }
        }

        // The rest of the string is state
        stateStr = buffer;
    }

    // Get state from string;
    auto found = getNameToPropertyMapping<State>().find(stateStr);
    if (found == getNameToPropertyMapping<State>().end())
    {
        state = State::eCount;
    }
    else
    {
        state = found->second;
    }
}

template <>
bool StyleContainer::StyleBlock::get<StyleFloatProperty, float>(StyleFloatProperty property, float* result) const
{
    size_t index = m_floatIndices[static_cast<size_t>(property)];
    if (index != SIZE_MAX)
    {
        *result = FloatStore::getInstance().get(index);
        return true;
    }

    return false;
}

template <>
bool StyleContainer::StyleBlock::get<StyleEnumProperty, uint32_t>(StyleEnumProperty property, uint32_t* result) const
{
    return getIndexedValue<StyleEnumProperty, uint32_t>(m_enums, m_enumIndices, property, result);
}

template <>
bool StyleContainer::StyleBlock::get<StyleColorProperty, uint32_t>(StyleColorProperty property, uint32_t* result) const
{
    size_t index = m_colorIndices[static_cast<size_t>(property)];
    if (index != SIZE_MAX)
    {
        *result = ColorStore::getInstance().get(index);
        return true;
    }

    return false;
}

template <>
bool StyleContainer::StyleBlock::get<StyleStringProperty, const char*>(StyleStringProperty property,
                                                                       const char** result) const
{
    size_t index = m_stringIndices[static_cast<size_t>(property)];
    if (index != SIZE_MAX)
    {
        *result = StringStore::getInstance().get(index);
        return true;
    }

    return false;
}

void StyleContainer::StyleBlock::merge(const StyleContainer::StyleBlock& styleBlock)
{
    mergeIndexedValues<StyleEnumProperty, uint32_t>(m_enums, m_enumIndices, styleBlock.m_enums, styleBlock.m_enumIndices);

    // Merge float indices
    // TODO: separate function
    for (size_t state = 0; state < static_cast<size_t>(StyleFloatProperty::eCount); ++state)
    {
        size_t sourceIndex = styleBlock.m_floatIndices[state];
        if (sourceIndex == SIZE_MAX)
        {
            continue;
        }

        m_floatIndices[state] = sourceIndex;
    }

    // Merge color indices
    for (size_t state = 0; state < static_cast<size_t>(StyleColorProperty::eCount); ++state)
    {
        size_t sourceIndex = styleBlock.m_colorIndices[state];
        if (sourceIndex == SIZE_MAX)
        {
            continue;
        }

        m_colorIndices[state] = sourceIndex;
    }

    // Merge string indices
    for (size_t state = 0; state < static_cast<size_t>(StyleStringProperty::eCount); ++state)
    {
        size_t sourceIndex = styleBlock.m_stringIndices[state];
        if (sourceIndex == SIZE_MAX)
        {
            continue;
        }

        m_stringIndices[state] = sourceIndex;
    }
}

void StyleContainer::StyleBlock::_initialize(StyleFloatProperty property, const char* value)
{
    size_t index = FloatStore::getInstance().find(value);
    m_floatIndices[static_cast<size_t>(property)] = index;
}

void StyleContainer::StyleBlock::_initialize(StyleFloatProperty property, float value)
{
    // The name is the float printed to the string
    std::string name = std::to_string(value);
    // Readonly, so no one can change it
    FloatStore::getInstance().store(name, value, true);
    size_t index = FloatStore::getInstance().find(name);
    m_floatIndices[static_cast<size_t>(property)] = index;
}

void StyleContainer::StyleBlock::_initialize(StyleEnumProperty property, uint32_t value)
{
    _initializeIndexedValue<StyleEnumProperty, uint32_t>(m_enums, m_enumIndices, property, value);
}

void StyleContainer::StyleBlock::_initialize(StyleColorProperty property, const char* value)
{
    size_t index = ColorStore::getInstance().find(value);
    m_colorIndices[static_cast<size_t>(property)] = index;
}

void StyleContainer::StyleBlock::_initialize(StyleColorProperty property, uint32_t value)
{
    // The name in the format 0xAABBGGRR
    std::string name = string_format("0x%x", value);
    // Readonly, so no one can change it
    ColorStore::getInstance().store(name, value, true);
    size_t index = ColorStore::getInstance().find(name);
    m_colorIndices[static_cast<size_t>(property)] = index;
}

void StyleContainer::StyleBlock::_initialize(StyleStringProperty property, const char* value)
{
    size_t index = StringStore::getInstance().find(value);
    if (index == SIZE_MAX)
    {
        StringStore::getInstance().store(value, value);
        index = StringStore::getInstance().find(value);
    }

    m_stringIndices[static_cast<size_t>(property)] = index;
}

template OMNIUI_API bool StyleContainer::resolveStyleProperty<StyleFloatProperty, float>(size_t styleStateGroupIndex,
                                                                                         StyleContainer::State state,
                                                                                         StyleFloatProperty property,
                                                                                         float* result,
                                                                                         bool checkParentGroup) const;

template OMNIUI_API bool StyleContainer::resolveStyleProperty<StyleEnumProperty, uint32_t>(size_t styleStateGroupIndex,
                                                                                           StyleContainer::State state,
                                                                                           StyleEnumProperty property,
                                                                                           uint32_t* result,
                                                                                           bool checkParentGroup) const;

template OMNIUI_API bool StyleContainer::resolveStyleProperty<StyleColorProperty, uint32_t>(size_t styleStateGroupIndex,
                                                                                            StyleContainer::State state,
                                                                                            StyleColorProperty property,
                                                                                            uint32_t* result,
                                                                                            bool checkParentGroup) const;

template OMNIUI_API bool StyleContainer::resolveStyleProperty<StyleStringProperty, const char*>(
    size_t styleStateGroupIndex,
    StyleContainer::State state,
    StyleStringProperty property,
    const char** result,
    bool checkParentGroup) const;

template bool StyleContainer::_resolveStyleProperty<StyleFloatProperty, float>(size_t blockIndex,
                                                                               StyleFloatProperty property,
                                                                               float* result,
                                                                               bool checkParentGroup) const;

template bool StyleContainer::_resolveStyleProperty<StyleEnumProperty, uint32_t>(size_t blockIndex,
                                                                                 StyleEnumProperty property,
                                                                                 uint32_t* result,
                                                                                 bool checkParentGroup) const;

template bool StyleContainer::_resolveStyleProperty<StyleColorProperty, uint32_t>(size_t blockIndex,
                                                                                  StyleColorProperty property,
                                                                                  uint32_t* result,
                                                                                  bool checkParentGroup) const;

template bool StyleContainer::_resolveStyleProperty<StyleStringProperty, const char*>(size_t blockIndex,
                                                                                      StyleStringProperty property,
                                                                                      const char** result,
                                                                                      bool checkParentGroup) const;

template OMNIUI_API StyleFloatProperty
StyleContainer::getPropertyEnumeration<StyleFloatProperty>(const std::string& property);
template OMNIUI_API StyleEnumProperty StyleContainer::getPropertyEnumeration<StyleEnumProperty>(const std::string& property);
template OMNIUI_API StyleColorProperty
StyleContainer::getPropertyEnumeration<StyleColorProperty>(const std::string& property);
template OMNIUI_API StyleStringProperty
StyleContainer::getPropertyEnumeration<StyleStringProperty>(const std::string& property);

OMNIUI_NAMESPACE_CLOSE_SCOPE
