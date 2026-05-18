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

#include "Api.h"
#include "Property.h"
#include "StyleProperties.h"

#include <cstddef>
#include <cstdint>
#include <array>
#include <string>
#include <unordered_map>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The StyleContainer class encapsulates the look and feel of a GUI.
 *
 * It's a place holder for the future work to support CSS style description. StyleContainer supports various properties,
 * pseudo-states, and subcontrols that make it possible to customize the look of widgets. It can only be edited by
 * merging with another style.
 */
class OMNIUI_CLASS_API StyleContainer
{
public:
    enum class State
    {
        eNormal = 0,
        eHovered,
        ePressed,
        eDisabled,
        eSelected,
        eChecked,
        eDrop,
        eCount
    };

    StyleContainer() = default;

    template <typename... Args>
    StyleContainer(Args... args)
    {
        _initializeBlock(args...);
    }

    /**
     * @brief Preset with a default style.
     */
    OMNIUI_API
    static const StyleContainer& defaultStyle();

    /**
     * @brief Check if the style contains anything.
     */
    OMNIUI_API
    bool valid() const;

    /**
     * @brief Merges another style to this style. The given style is strongest.
     */
    OMNIUI_API
    void merge(const StyleContainer& style);

    /**
     * @brief Find the style state group by type and name. It's pretty slow, so it shouldn't be used in the draw cycle.
     */
    OMNIUI_API
    size_t getStyleStateGroupIndex(const std::string& type, const std::string& name) const;

    /**
     * @brief Get all the types in this StyleContainer.
     */
    OMNIUI_API
    std::vector<std::string> getCachedTypes() const;

    /**
     * @brief Get all the names related to the type in this StyleContainer.
     */
    OMNIUI_API
    std::vector<std::string> getCachedNames(const std::string& type) const;

    /**
     * @brief Get all the available states in the given index in this StyleContainer.
     */
    OMNIUI_API
    std::vector<State> getCachedStates(size_t styleStateGroupIndex) const;

    /**
     * @brief Find the given property in the data structure using the style state group index. If the property is not
     * found, it continues finding in cascading and parent blocks. The style state group index can be obtained with
     * getStyleStateGroupIndex.
     *
     * @tparam T StyleFloatProperty or StyleColorProperty
     * @tparam U float or uint32_t
     */
    template <typename T, typename U>
    bool resolveStyleProperty(
        size_t styleStateGroupIndex, State state, T property, U* result, bool checkParentGroup = true) const;

    /**
     * @brief Get the the mapping between property and its string
     *
     * @tparam T StyleFloatProperty, StyleEnumProperty, StyleColorProperty, StyleStringProperty or State
     */
    template <typename T>
    static const std::unordered_map<std::string, T>& getNameToPropertyMapping();

    /**
     * @brief Get the Property from the string
     *
     * @tparam T StyleFloatProperty, StyleEnumProperty, StyleColorProperty or StyleStringProperty
     */
    template <typename T>
    static T getPropertyEnumeration(const std::string& property);

private:
    /**
     * @brief StyleContainer block represents one single block of properties.
     *
     * It keeps the indices of all possible properties, the values are in the vectors, and the index represents the
     * position of the value in the vector. Thus, since we always know if the property exists and its location, it's
     * possible to access the value very fast. Variadic arguments of the constructor allow creating styles with any
     * number of properties. The initialization usually looks like this:
     *
     *    StyleBlock{ StyleColorProperty::eBackgroundColor, 0xff292929, StyleFloatProperty::eMargin, 3.0f }
     *
     */
    class OMNIUI_CLASS_API StyleBlock
    {
    public:
        /**
         * @brief Construct a new StyleContainer Block object. It's usually looks like this:
         *
         *   StyleBlock{ StyleColorProperty::eBackgroundColor, 0xff292929, StyleFloatProperty::eMargin, 3.0f }
         *
         */
        template <typename... Args>
        StyleBlock(Args... args)
        {
            // TODO: with reserve it will be faster.
            m_floatIndices.fill(SIZE_MAX);
            m_enumIndices.fill(SIZE_MAX);
            m_colorIndices.fill(SIZE_MAX);
            m_stringIndices.fill(SIZE_MAX);
            _initialize(args...);
        }

        /**
         * @brief Query the properties in the block.
         *
         * @tparam T StyleFloatProperty or StyleColorProperty
         * @tparam U float or uint32_t
         * @param property For example StyleFloatProperty::ePadding
         * @param result the pointer to the result where the resolved property will be written
         * @return true when the block contains given property
         * @return false when the block doesn't have the given property
         */
        template <typename T, typename U>
        bool get(T property, U* result) const;

        /**
         * @brief Merge another property into this one.
         *
         * @param styleBlock The given property. It's stronger than the current one.
         */
        void merge(const StyleBlock& styleBlock);

        /**
         * @brief Introducing a new conception of cascading and parenting
         *
         * This relationship can be described in the following diagram. We keep the indices of other nodes when they are
         * available. And it allows fast iterating cascade styles when resolving the properties.
         *
         *      Button  <-------cascade--+ Button:hovered
         *         ^                              ^
         *         |                              |
         *       parent                         parent
         *         |                              |
         *         +                              +
         *      Button::name <--cascade--+ Button::name::hovered
         *
         */
        OMNIUI_PROPERTY(size_t, parentIndex, DEFAULT, SIZE_MAX, READ, getParentIndex, WRITE, setParentIndex);
        OMNIUI_PROPERTY(size_t, cascadeIndex, DEFAULT, SIZE_MAX, READ, getCascadeIndex, WRITE, setCascadeIndex);

    private:
        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleFloatProperty property, const char* value);

        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleFloatProperty property, float value);

        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleColorProperty property, const char* value);

        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleColorProperty property, uint32_t value);

        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleEnumProperty property, uint32_t value);

        /**
         * @brief A helper for variadic construction.
         */
        OMNIUI_API
        void _initialize(StyleStringProperty property, const char* value);

        /**
         * @brief A helper for variadic construction.
         */
        template <typename T, typename U, typename... Args>
        void _initialize(T property, U value, Args... args)
        {
            _initialize(property, value);
            _initialize(args...);
        }

        // The data model of the style block is simple. We keep all the values in the vector and all the indices in the
        // array. It allows us to track which properties are in this block with excellent performance. If the property
        // is not here, its index is SIZE_MAX.
        //
        // +------------------+   +----------+
        // | m_floatIndices   |   | m_floats |
        // |------------------|   |----------|
        // | padding +------------> 0.0      |
        // | margin        +------> 1.0      |
        // | radius        |  |   |          |
        // | thickness +---+  |   |          |
        // +------------------+   +----------+
        //
        std::array<size_t, static_cast<size_t>(StyleFloatProperty::eCount)> m_floatIndices = {};
        std::array<size_t, static_cast<size_t>(StyleColorProperty::eCount)> m_colorIndices = {};
        std::array<size_t, static_cast<size_t>(StyleStringProperty::eCount)> m_stringIndices = {};

        std::vector<uint32_t> m_enums = {};
        std::array<size_t, static_cast<size_t>(StyleEnumProperty::eCount)> m_enumIndices = {};
    };

    /**
     * @brief Find the given property in the given block index. If the property is not found, it continues finding in
     * cascading and parent blocks.
     *
     * @tparam T StyleFloatProperty or StyleColorProperty
     * @tparam U float or uint32_t
     */
    template <typename T, typename U>
    bool _resolveStyleProperty(size_t blockIndex, T property, U* result, bool checkParentGroup) const;

    /**
     * @brief A helper for variadic construction.
     */
    template <typename... Args>
    void _initializeBlock(StyleFloatProperty prop, Args... args)
    {
        static const std::string empty{};
        _initializeBlock(empty, prop, args...);
    }

    /**
     * @brief A helper for variadic construction.
     */
    template <typename... Args>
    void _initializeBlock(StyleEnumProperty prop, Args... args)
    {
        static const std::string empty{};
        _initializeBlock(empty, prop, args...);
    }

    /**
     * @brief A helper for variadic construction.
     */
    template <typename... Args>
    void _initializeBlock(StyleColorProperty prop, Args... args)
    {
        static const std::string empty{};
        _initializeBlock(empty, prop, args...);
    }

    /**
     * @brief A helper for variadic construction.
     */
    template <typename... Args>
    void _initializeBlock(StyleStringProperty prop, Args... args)
    {
        static const std::string empty{};
        _initializeBlock(empty, prop, args...);
    }

    /**
     * @brief A helper for variadic construction.
     */
    template <typename... Args>
    void _initializeBlock(const std::string& scope, Args... args)
    {
        // Can't move it to cpp because of the variadic template
        std::string type;
        std::string name;
        State state;
        StyleContainer::_parseScopeString(scope, type, name, state);

        if (state == State::eCount)
        {
            // TODO: Warning message. BTW, what do we need to use for warnings?
            return;
        }

        auto index = _createStyleStateGroup(type, name);
        m_styleStateGroups[index][static_cast<int32_t>(state)] = m_styleBlocks.size();

        m_styleBlocks.emplace_back(args...);
    }

    /**
     * @brief Create a StyleContainer State Group object and puts it to the internal data structure.
     *
     * @return the index of created or existed StyleContainer State Group object in the data structure.
     */
    OMNIUI_API
    size_t _createStyleStateGroup(const std::string& type, const std::string& name);

    /**
     * @brief Perses a string that looks like "Widget::name:state", split it to the parts and return the parts.
     */
    OMNIUI_API
    static void _parseScopeString(const std::string& input, std::string& type, std::string& name, State& state);

    /**
     * @brief This is the group that contains indices to blocks. The index per state. Also, it has an index of the group
     * that is the parent of this group.
     *
     * It's different from the block. The block has a list of properties. The group has the indices to the block.
     */
    struct StyleStateIndices
    {
    public:
        StyleStateIndices() : m_parent{ SIZE_MAX }
        {
            // By default everything is invalid.
            m_indices.fill(SIZE_MAX);
        }

        size_t& operator[](size_t i)
        {
            // Fast access the indices
            return m_indices[i];
        }

        const size_t& operator[](size_t i) const
        {
            // Fast access the indices
            return m_indices[i];
        }

        size_t getParentIndex() const
        {
            return m_parent;
        }

        void setParentIndex(size_t i)
        {
            m_parent = i;
        }

    private:
        std::array<size_t, static_cast<size_t>(State::eCount)> m_indices;
        size_t m_parent;
    };

    using StyleBlocks = std::unordered_map<std::string, std::unordered_map<std::string, size_t>>;

    // The data structure is pretty simple. We keep all the style blocks in the vector. We have an array with all the
    // possible states (StyleContainer State Group) of the block. The states are hovered, pressed, etc. The
    // StyleContainer State Group has the indices of the style blocks in the data structure. The StyleContainer State
    // Groups are also placed to the vector, and it allows us to keep the index of the StyleContainer State Group in
    // each widget. Also, we have a dictionary that maps the string names to the indices of StyleContainer State Group.
    // See the following diagram for details.
    //
    // The workflow is simple. Once the style is changed, the widget should ask the index of StyleContainer State Group
    // with the method `getStyleStateGroupIndex`, and use this index in the draw cycle to query style properties with
    // the method
    // `_resolveStyleProperty`.
    //
    // +-----------------------------+  +---------------------+  +----------------+
    // | m_styleStateGroupIndicesMap |  | m_styleStateGroups  |  | m_styleBlocks  |
    // |-----------------------------|  |---------------------|  |----------------|
    // | 'Widget'                    |  |              +---------> +-StyleBlock-+ |
    // |   '' +-------------------------> +------------|----+ |  | | padding    | |
    // |   'name'                    |  | | normal     |    | |  | | margin     | |
    // | 'Button'                    |  | | hovered +--+    | |  | | color      | |
    // |   ''                        |  | +-----------------+ |  | | background | |
    // |   'cancel' +-------------------> +-----------------+ |  | +------------+ |
    // |                             |  | | normal +-------------> +-StyleBlock-+ |
    // |                             |  | | hovered         | |  | | padding    | |
    // |                             |  | +-----------------+ |  | | margin     | |
    // |                             |  |                     |  | | color      | |
    // |                             |  |                     |  | | background | |
    // |                             |  |                     |  | +------------+ |
    // +-----------------------------+  +---------------------+  +----------------+
    std::vector<StyleBlock> m_styleBlocks = {};
    std::vector<StyleStateIndices> m_styleStateGroups = {};
    StyleBlocks m_styleStateGroupIndicesMap;

    // The index of the block that is the global override. It's the block with no name and no type.
    size_t m_globalOverrideIndex = SIZE_MAX;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
