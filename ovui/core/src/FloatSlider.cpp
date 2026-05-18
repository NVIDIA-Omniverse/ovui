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

#include "platform/Assert.h"
#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/FloatSlider.h>
#include <omni/ui/SimpleNumericModel.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct FloatSlider::FloatSliderData : public Widget::WidgetData
{
    ~FloatSliderData() override = default;

    // The cached state of the slider.
    double m_valueCache = 0;
};

FloatSlider::FloatSlider(std::shared_ptr<AbstractValueModel> model)
    : AbstractSlider(std::move(model), new FloatSliderData)
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleFloatModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }

    // TODO: The default step for Floatslider isn't so great for ranges outside [0, 1], but currently there
    //       also isn't a good way to detect if step of 0.01 was explicitly requested, or to auto-adjust
    //       step based on range (min, max) changing at runtime.
#if 0
    const double valueRange = std::abs(this->getMax() - this->getMin());
    if (valueRange >= 10 && this->getStep() == 0.01f)
    {
        double exponent = std::log10(std::abs(this->getMax() - this->getMin()));
        this->setStep(float(std::pow(10.0, exponent)) / 100.f);
    }
#endif
}

const char* FloatSlider::getFormatString(double value, uint32_t maxSymbols)
{
    // We can't use "%.6g" for format because it outputs the number in the different form. It can be 0.0001, 0 and 1e-4.
    // We always need 0.0 and we don't want to have many 0 at the end. So we count the number of `0` at the end of the
    // string and remove them.
    static const char* const formats[] = { "%.1f",  "%.1f",  "%.2f",  "%.3f",  "%.4f",  "%.5f",  "%.6f",
                                           "%.7f",  "%.8f",  "%.9f",  "%.10f", "%.11f", "%.12f", "%.13f",
                                           "%.14f", "%.15f", "%.16f", "%.17f", "%.18f", "%.19f", "%.20f",
                                           "%.21f", "%.22f", "%.23f", "%.24f", "%.25f", "%.26f", "%.27f",
                                           "%.28f", "%.29f", "%.30f", "%.31f", "%.32f" };
    constexpr uint32_t formatsCount = sizeof(formats) / sizeof(*formats);
    maxSymbols = std::min(maxSymbols, formatsCount - 1);

    // Using the shortest representation of float but always use the minimum one digit for the precision
    constexpr size_t size = 64;
    char buffer[64];
    int max_n = snprintf(buffer, size, formats[maxSymbols], value);

    char* endBuffer = buffer + strlen(buffer) - 1;

    char* found = strchr(buffer, '.');
    OMNIUI_ASSERT(found || !std::isfinite(value) || (max_n >= static_cast<int>(size)));

    // Cut 0 from the end of the string.
    while (endBuffer > found && *endBuffer == '0')
    {
        endBuffer--;
    }

    uint32_t precision = static_cast<uint32_t>(std::distance(found, endBuffer));
    precision = std::min(precision, maxSymbols);
    return formats[precision];
}

float FloatSlider::_getValueRatio()
{
    const auto value = _getData<FloatSliderData>().m_valueCache;
    return (float)((value - this->getMin()) / (this->getMax() - this->getMin()));
}

void FloatSlider::onModelUpdated()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(!model))
    {
        OMNIUI_LOG_ERROR("FloatSlider::onModelUpdated had no model");
        return;
    }

    _getData<FloatSliderData>().m_valueCache = model->getValue<double>();

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void FloatSlider::_drawUnderlyingItem()
{
    auto ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    ImGuiWindow* window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);

    // Check if the keyboard input is active before calling ImGui::SliderScalar
    // because when checking after the result will be different after pressing
    // ENTER or TAB (OM-52078)
    const ImGuiID id = window->GetID("##hidelabel");
    bool keyboardInputIsActive = ctx->ActiveId == id && ctx->TempInputId == id;

    double value = _getData<FloatSliderData>().m_valueCache;
    bool result = this->_drawUnderlyingItem(&value, this->getMin(), this->getMax());

    this->_beginModelChange();

    if (result)
    {
        if (m_editActive && !keyboardInputIsActive)
        {
            // Apply step only when editing with mouse.
            value = round(value / this->getStep()) * this->getStep();
        }

        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            // Trying to set the value. If the model accepts it, it will call onModelUpdated and update m_textBuffer.
            model->setValue(value);
        }
        else
        {
            OMNIUI_LOG_ERROR("FloatSlider::_drawUnderlyingItem had no model");
        }
    }

    this->_endModelChange();
}

bool FloatSlider::_drawUnderlyingItem(double* value, double min, double max)
{
    static constexpr char label[] = "##hidelabel";
    // Empty format will make SliderScalar to hide the text
    const char* format = "";
    // Keep the provided value because SliderScalar modifies it.
    double valueGiven = *value;

    auto cursor = ImGui::GetCursorScreenPos();

    auto ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    ImGuiWindow* window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);

    const ImGuiID id = window->GetID(label);
    bool keyboardInputIsActive = ctx->ActiveId == id && ctx->TempInputId == id;
    bool ctrlClicked = isHovered() && ctx->IO.MouseClicked[0] && ctx->IO.KeyCtrl;
    bool isEditingFromKeyboard = (m_editActive && keyboardInputIsActive) || ctrlClicked;

    if (isEditingFromKeyboard)
    {
        // If it's edit from the keyboard, we need to use a regular format for SliderScalar so it draws the text and we
        // don't draw the text overlay.
        format = getFormatString(*value, this->getPrecision());
    }

    // If we have an override, apply it
    const std::string& formatOverride = getFormat();
    if (formatOverride.size() > 0)
    {
        format = formatOverride.c_str();
    }

    bool result = ImGui::SliderScalar(label, ImGuiDataType_Double, value, &min, &max, format);

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
        snprintf(buffer, size, format, valueGiven);
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
