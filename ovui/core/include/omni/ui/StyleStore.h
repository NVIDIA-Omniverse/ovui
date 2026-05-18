/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

inline std::string __toLower(std::string name)
{
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    return name;
}

/**
 * @brief A common template for indexing the style properties of the specific
 * types.
 */
template <typename T>
class StyleStore
{
public:
    OMNIUI_API
    virtual ~StyleStore() = default;

    /**
     * @brief Save the color by name
     */
    OMNIUI_API
    virtual void store(const std::string& name, T color, bool readOnly = false)
    {
        size_t found = this->find(name);
        if (found == SIZE_MAX)
        {
            m_store.emplace_back(__toLower(name), color, readOnly);
        }
        else if (!m_store[found].readOnly)
        {
            m_store[found].value = color;
            m_store[found].readOnly = readOnly;
        }
    }

    /**
     * @brief Return the color by index.
     */
    OMNIUI_API
    T get(size_t id) const
    {
        if (id == SIZE_MAX)
        {
            return static_cast<T>(NULL);
        }

        return m_store[id].value;
    }

    /**
     * @brief Return the index of the color with specific name.
     */
    OMNIUI_API
    size_t find(const std::string& name) const
    {
        std::string lowerName = __toLower(name);
        auto found =
            std::find_if(m_store.begin(), m_store.end(), [&lowerName](const auto& it) { return it.name == lowerName; });
        if (found != m_store.end())
        {
            return std::distance(m_store.begin(), found);
        }

        return SIZE_MAX;
    }

protected:
    StyleStore()
    {
    }

    struct Entry
    {
        Entry(std::string entryName, T entryValue, bool entryReadOnly = false)
            : name{ std::move(entryName) }, value{ entryValue }, readOnly{ entryReadOnly }
        {
        }

        std::string name;
        T value;
        bool readOnly;
    };

    std::vector<Entry> m_store;
};

/**
 * @brief A singleton that stores all the UI Style color properties of omni.ui.
 */
class OMNIUI_CLASS_API ColorStore : public StyleStore<uint32_t>
{
public:
    /**
     * @brief Get the instance of this singleton object.
     */
    OMNIUI_API
    static ColorStore& getInstance();

    // A singleton pattern
    ColorStore(ColorStore const&) = delete;
    void operator=(ColorStore const&) = delete;

private:
    ColorStore();
};

/**
 * @brief A singleton that stores all the UI Style float properties of omni.ui.
 */
class OMNIUI_CLASS_API FloatStore : public StyleStore<float>
{
public:
    /**
     * @brief Get the instance of this singleton object.
     */
    OMNIUI_API
    static FloatStore& getInstance();

    // A singleton pattern
    FloatStore(FloatStore const&) = delete;
    void operator=(FloatStore const&) = delete;

private:
    FloatStore();
};

/**
 * @brief A singleton that stores all the UI Style string properties of omni.ui.
 */
class OMNIUI_CLASS_API StringStore : public StyleStore<const char*>
{
public:
    OMNIUI_API
    ~StringStore() override;

    /**
     * @brief Get the instance of this singleton object.
     */
    OMNIUI_API
    static StringStore& getInstance();

    // A singleton pattern
    StringStore(StringStore const&) = delete;
    void operator=(StringStore const&) = delete;

    OMNIUI_API
    void store(const std::string& name, const char* string_value, bool readOnly = false) override;

private:
    StringStore();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
