/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/IntDrag.h>

#include <limits>

OMNIUI_NAMESPACE_OPEN_SCOPE

IntDrag::IntDrag(std::shared_ptr<AbstractValueModel> model)
    : IntSlider(std::move(model))
{
    // set unbound default min/max for IntDrag only, but not IntSlider
    this->setMin(std::numeric_limits<int64_t>::lowest());
    this->setMax(std::numeric_limits<int64_t>::max());
}

bool IntDrag::_drawUnderlyingItem(int64_t* value, int64_t min, int64_t max)
{
    return ImGui::DragScalar("##hidelabel", ImGuiDataType_S64, value, this->getStep(), &min, &max);
}

UIntDrag::UIntDrag(std::shared_ptr<AbstractValueModel> model)
    : UIntSlider(std::move(model))
{
    // set unbound default min/max for IntDrag only, but not UIntSlider
    this->setMin(std::numeric_limits<uint64_t>::lowest());
    this->setMax(std::numeric_limits<uint64_t>::max());
}

bool UIntDrag::_drawUnderlyingItem(uint64_t* value, uint64_t min, uint64_t max)
{
    return ImGui::DragScalar("##hidelabel", ImGuiDataType_U64, value, this->getStep(), &min, &max);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
