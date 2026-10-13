/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Internal dispatch scope. No model layout or virtual interface change.
#pragma once

#include <omni/ui/AbstractValueModel.h>

OMNIUI_NAMESPACE_OPEN_SCOPE
namespace detail
{
class ScopedValueModelEditCancellation
{
public:
    explicit ScopedValueModelEditCancellation(const AbstractValueModel* model) noexcept;
    ~ScopedValueModelEditCancellation() noexcept;
    ScopedValueModelEditCancellation(const ScopedValueModelEditCancellation&) = delete;
    ScopedValueModelEditCancellation& operator=(const ScopedValueModelEditCancellation&) = delete;
private:
    const AbstractValueModel* m_previous;
};
}
OMNIUI_NAMESPACE_CLOSE_SCOPE
