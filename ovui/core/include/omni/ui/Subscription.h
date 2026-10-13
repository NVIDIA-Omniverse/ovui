/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once
#include <functional>

namespace omni { namespace ui {

/// RAII subscription handle. Calls unsubscribe callback on destruction.
class Subscription {
public:
    Subscription() = default;
    explicit Subscription(std::function<void()> unsubFn) : m_unsub(std::move(unsubFn)) {}
    ~Subscription() { if (m_unsub) m_unsub(); }
    Subscription(const Subscription&) = delete;
    Subscription& operator=(const Subscription&) = delete;
    Subscription(Subscription&& o) noexcept : m_unsub(std::move(o.m_unsub)) { o.m_unsub = nullptr; }
    Subscription& operator=(Subscription&& o) noexcept { if (m_unsub) m_unsub(); m_unsub = std::move(o.m_unsub); o.m_unsub = nullptr; return *this; }
    void unsubscribe() { if (m_unsub) { m_unsub(); m_unsub = nullptr; } }
private:
    std::function<void()> m_unsub;
};

}} // namespace omni::ui
