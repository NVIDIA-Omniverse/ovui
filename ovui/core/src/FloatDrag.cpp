/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "platform/Assert.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/FloatDrag.h>

#include <cmath>
#include <limits>

OMNIUI_NAMESPACE_OPEN_SCOPE

FloatDrag::FloatDrag(std::shared_ptr<AbstractValueModel> model)
    : FloatSlider(std::move(model))
{
    // set unbound default min/max for FloatDrag only, but not FloatSlider
    this->setMin(std::numeric_limits<double>::lowest());
    this->setMax(std::numeric_limits<double>::max());
}

bool FloatDrag::_drawUnderlyingItem(double* value, double min, double max)
{
    // TODO: This method is very close to FloatSlider::_drawUnderlyingItem. We need to use shared code.
    //

    static constexpr char label[] = "##hidelabel";
    // Empty format will make SliderScalar to hide the text
    const char* format = "";
    // Keep the provided value because SliderScalar modifies it.
    const double& derefValue = *value;

    auto cursor = ImGui::GetCursorScreenPos();

    auto ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    ImGuiWindow* window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);

    const ImGuiID id = window->GetID(label);
    bool keyboardInputIsActive = ctx->ActiveId == id && ctx->TempInputId == id;
    bool ctrlClicked = isHovered() && ctx->IO.MouseClicked[0] && ctx->IO.KeyCtrl;
    bool doubleClicked = isHovered() && ctx->IO.MouseDoubleClicked[0];
    bool isEditingFromKeyboard = (m_editActive && keyboardInputIsActive) || ctrlClicked || doubleClicked;

    if (isEditingFromKeyboard)
    {
        // If it's edit from the keyboard, we need to use a regular format for SliderScalar so it draws the text and we
        // don't draw the text overlay.
        format = getFormatString(*value, this->getPrecision());
    }

    // Block dragging if it's infinity or nan with step = 0. Also set min/max to value. Non-zero difference between
    // these makes DragBehaviorT do changes to value even with step = 0
    bool nonfinite = !std::isfinite(derefValue);
    float step = nonfinite ? 0.f : this->getStep();
    if (nonfinite)
    {
        min = derefValue;
        max = derefValue;
    }

    // If we have an override, apply it
    const std::string& formatOverride = getFormat();
    if (formatOverride.size() > 0)
    {
        format = formatOverride.c_str();
    }

    bool result = ImGui::DragScalar("##hidelabel", ImGuiDataType_Double, value, step, &min, &max, format);

    if (!isEditingFromKeyboard)
    {
        // Form a text do display
        constexpr size_t size = 64;
        char buffer[64];

        // Empty format string -> getFormatString()
        if (format[0] == 0)
        {
            format = getFormatString(*value, this->getPrecision());
        }
        snprintf(buffer, size, format, derefValue);
        char* endBuffer = buffer + strlen(buffer);

        const ImGuiStyle& style = ctx->Style;

        float width = this->getComputedContentWidth();
        ImVec2 textSize = ImGui::CalcTextSize(buffer, nullptr, true);

        // Rect is the same as in SliderScalar
        const ImRect availableFrame(
            cursor, ImVec2(cursor.x + width, cursor.y + textSize.y + style.FramePadding.y * 2.0f));

        // Display the text in the middle of the rect
        ImGui::RenderTextClipped(availableFrame.Min, availableFrame.Max, buffer, endBuffer, NULL, ImVec2(0.5f, 0.5f));
    }

    return result;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
