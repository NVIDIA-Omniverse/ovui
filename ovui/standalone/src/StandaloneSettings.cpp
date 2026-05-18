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

#include "StandaloneSettings.h"

#include <algorithm>

namespace omni {
namespace ui {
namespace standalone {

// ---------------------------------------------------------------------------
// Getters
// ---------------------------------------------------------------------------

bool StandaloneSettings::getBool(const char* path, bool defaultVal)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_values.find(path);
    if (it != m_values.end() && std::holds_alternative<bool>(it->second))
        return std::get<bool>(it->second);
    return defaultVal;
}

int32_t StandaloneSettings::getInt(const char* path, int32_t defaultVal)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_values.find(path);
    if (it != m_values.end() && std::holds_alternative<int32_t>(it->second))
        return std::get<int32_t>(it->second);
    return defaultVal;
}

float StandaloneSettings::getFloat(const char* path, float defaultVal)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_values.find(path);
    if (it != m_values.end() && std::holds_alternative<float>(it->second))
        return std::get<float>(it->second);
    return defaultVal;
}

std::string StandaloneSettings::getString(const char* path, const char* defaultVal)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_values.find(path);
    if (it != m_values.end() && std::holds_alternative<std::string>(it->second))
        return std::get<std::string>(it->second);
    return defaultVal ? defaultVal : "";
}

// ---------------------------------------------------------------------------
// Setters
// ---------------------------------------------------------------------------

void StandaloneSettings::setBool(const char* path, bool value)
{
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_values[path] = value;
    }
    fireCallbacks(path);
}

void StandaloneSettings::setInt(const char* path, int32_t value)
{
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_values[path] = value;
    }
    fireCallbacks(path);
}

void StandaloneSettings::setFloat(const char* path, float value)
{
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_values[path] = value;
    }
    fireCallbacks(path);
}

void StandaloneSettings::setString(const char* path, const char* value)
{
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_values[path] = std::string(value ? value : "");
    }
    fireCallbacks(path);
}

// ---------------------------------------------------------------------------
// Defaults (set only if key is absent)
// ---------------------------------------------------------------------------

void StandaloneSettings::setDefaultBool(const char* path, bool value)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_values.emplace(path, value);
}

void StandaloneSettings::setDefaultInt(const char* path, int32_t value)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_values.emplace(path, value);
}

void StandaloneSettings::setDefaultFloat(const char* path, float value)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_values.emplace(path, value);
}

void StandaloneSettings::setDefaultString(const char* path, const char* value)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_values.emplace(path, std::string(value ? value : ""));
}

// ---------------------------------------------------------------------------
// Subscriptions
// ---------------------------------------------------------------------------

SettingsSubscriptionId StandaloneSettings::subscribe(const char* path, ChangeCallback callback)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    SettingsSubscriptionId id = m_nextSubId++;
    m_subscriptions.push_back({id, path ? path : "", std::move(callback)});
    return id;
}

void StandaloneSettings::unsubscribe(SettingsSubscriptionId id)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_subscriptions.erase(
        std::remove_if(m_subscriptions.begin(), m_subscriptions.end(),
                        [id](const Subscription& s) { return s.id == id; }),
        m_subscriptions.end());
}

void StandaloneSettings::fireCallbacks(const char* path)
{
    // Copy the matching callbacks under lock, then fire outside the lock
    // to avoid re-entrancy deadlocks.
    std::vector<ChangeCallback> toFire;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        for (auto& sub : m_subscriptions)
        {
            // Match if the subscription path is a prefix of the changed path
            if (sub.pathPrefix.empty() ||
                std::string(path).find(sub.pathPrefix) == 0)
            {
                toFire.push_back(sub.callback);
            }
        }
    }
    for (auto& cb : toFire)
        cb(path);
}

} // namespace standalone
} // namespace ui
} // namespace omni
