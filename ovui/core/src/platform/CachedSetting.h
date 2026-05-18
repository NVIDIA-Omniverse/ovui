/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "IUiSettings.h"
#include "PlatformRegistry.h"

#include <atomic>
#include <cstdint>
#include <string>

namespace omni {
namespace ui {

/// Cached bool setting that auto-subscribes to changes via IUiSettings.
class CachedBoolSetting
{
public:
    CachedBoolSetting(const char* key, bool defaultVal = false)
        : m_key(key)
        , m_value(defaultVal)
    {
        auto* s = PlatformRegistry::instance().settings();
        if (s)
        {
            m_value = s->getBool(key, defaultVal);
            m_subId = s->subscribe(key, [this](const char*) {
                auto* s2 = PlatformRegistry::instance().settings();
                if (s2)
                    m_value = s2->getBool(m_key.c_str(), m_value);
            });
        }
    }

    ~CachedBoolSetting()
    {
        if (m_subId != 0)
        {
            auto* s = PlatformRegistry::instance().settings();
            if (s)
                s->unsubscribe(m_subId);
        }
    }

    bool get() const { return m_value; }

    // Non-copyable, non-movable (subscription pointers)
    CachedBoolSetting(const CachedBoolSetting&) = delete;
    CachedBoolSetting& operator=(const CachedBoolSetting&) = delete;

private:
    std::string m_key;
    bool m_value;
    SettingsSubscriptionId m_subId = 0;
};

/// Cached int32 setting that auto-subscribes to changes via IUiSettings.
class CachedIntSetting
{
public:
    CachedIntSetting(const char* key, int32_t defaultVal = 0)
        : m_key(key)
        , m_value(defaultVal)
    {
        auto* s = PlatformRegistry::instance().settings();
        if (s)
        {
            m_value = s->getInt(key, defaultVal);
            m_subId = s->subscribe(key, [this](const char*) {
                auto* s2 = PlatformRegistry::instance().settings();
                if (s2)
                    m_value = s2->getInt(m_key.c_str(), m_value);
            });
        }
    }

    ~CachedIntSetting()
    {
        if (m_subId != 0)
        {
            auto* s = PlatformRegistry::instance().settings();
            if (s)
                s->unsubscribe(m_subId);
        }
    }

    int32_t get() const { return m_value; }

    CachedIntSetting(const CachedIntSetting&) = delete;
    CachedIntSetting& operator=(const CachedIntSetting&) = delete;

private:
    std::string m_key;
    int32_t m_value;
    SettingsSubscriptionId m_subId = 0;
};

/// Cached float setting that auto-subscribes to changes via IUiSettings.
class CachedFloatSetting
{
public:
    CachedFloatSetting(const char* key, float defaultVal = 0.0f)
        : m_key(key)
        , m_value(defaultVal)
    {
        auto* s = PlatformRegistry::instance().settings();
        if (s)
        {
            m_value = s->getFloat(key, defaultVal);
            m_subId = s->subscribe(key, [this](const char*) {
                auto* s2 = PlatformRegistry::instance().settings();
                if (s2)
                    m_value = s2->getFloat(m_key.c_str(), m_value);
            });
        }
    }

    ~CachedFloatSetting()
    {
        if (m_subId != 0)
        {
            auto* s = PlatformRegistry::instance().settings();
            if (s)
                s->unsubscribe(m_subId);
        }
    }

    float get() const { return m_value; }

    CachedFloatSetting(const CachedFloatSetting&) = delete;
    CachedFloatSetting& operator=(const CachedFloatSetting&) = delete;

private:
    std::string m_key;
    float m_value;
    SettingsSubscriptionId m_subId = 0;
};

/// Cached string setting that auto-subscribes to changes via IUiSettings.
class CachedStringSetting
{
public:
    CachedStringSetting(const char* key, const char* defaultVal = "")
        : m_key(key)
        , m_value(defaultVal ? defaultVal : "")
    {
        auto* s = PlatformRegistry::instance().settings();
        if (s)
        {
            m_value = s->getString(key, defaultVal);
            m_subId = s->subscribe(key, [this](const char*) {
                auto* s2 = PlatformRegistry::instance().settings();
                if (s2)
                    m_value = s2->getString(m_key.c_str(), m_value.c_str());
            });
        }
    }

    ~CachedStringSetting()
    {
        if (m_subId != 0)
        {
            auto* s = PlatformRegistry::instance().settings();
            if (s)
                s->unsubscribe(m_subId);
        }
    }

    const std::string& get() const { return m_value; }

    CachedStringSetting(const CachedStringSetting&) = delete;
    CachedStringSetting& operator=(const CachedStringSetting&) = delete;

private:
    std::string m_key;
    std::string m_value;
    SettingsSubscriptionId m_subId = 0;
};

} // namespace ui
} // namespace omni
