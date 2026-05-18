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

#include "platform/PlatformRegistry.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include "platform/Log.h"
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/ColorWidget.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/SimpleNumericModel.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>
#include <omni/ui/Workspace.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{
constexpr size_t kRgbaComponentsNumber = 4;
constexpr char kColorPickerName[] = "colorPicker";
}


struct ColorWidget::ColorWidgetData : public Widget::WidgetData
{
    ~ColorWidgetData() override = default;

    // The pointer to the popup window in the underlying windowing system.
    omni::ui::windowmanager::IWindowCallbackPtr m_uiWindow;
    AppWindowHandle m_appWindow = nullptr;

    // The cached state of the ColorWidget allows to query the model only if it's changed.
    size_t m_componentsNumber = 0;
    float m_colorBuffer[4] = { 0.0f };

    bool m_popupUsed = false;
};


ColorWidget::ColorWidget(std::shared_ptr<AbstractItemModel> model)
    : Widget(new ColorWidgetData)
    , ItemModelHelper(std::move(model))
{
    auto& data = _getData<ColorWidgetData>();
    static_assert((sizeof(data.m_colorBuffer)/sizeof(data.m_colorBuffer[0])) == kRgbaComponentsNumber,
        "ColorWidget::m_colorBuffer number of components does not match kRgbaComponentsNumber");

    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple one.
        this->setModel(SimpleListModel::create(std::vector<float>{ { 0.0f, 0.0f, 0.0f, 1.0f } }));
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }
}

ColorWidget::~ColorWidget() = default;

void ColorWidget::setComputedContentWidth(float width)
{
    // TODO: We need to set the size from the style. We now take the ColorWidget size from ImGui. It's height because we
    // assume that the widget can't be smaller than the right square button with the arrow.
    Widget::setComputedContentWidth(std::max(ImGui::GetFrameHeight() * this->_getScale(), width));
}

void ColorWidget::setComputedContentHeight(float height)
{
    // TODO: We need to set the size from the style. We now take the ColorWidget size from ImGui.
    Widget::setComputedContentHeight(std::max(ImGui::GetFrameHeight() * this->_getScale(), height));
}

static size_t maxColorChildren(const std::vector<std::shared_ptr<const AbstractItemModel::AbstractItem>>& modelChildItems)
{
    return std::min(kRgbaComponentsNumber, modelChildItems.size());
}

void ColorWidget::onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    constexpr float defaultColor[kRgbaComponentsNumber] = { 0.0f, 0.0f, 0.0f, 1.0f };

    auto& data = _getData<ColorWidgetData>();

    std::copy(std::begin(defaultColor), std::end(defaultColor), std::begin(data.m_colorBuffer));

    // Avoid the current broken return a reference to shared_ptr API omni.ui has for now.
    std::shared_ptr<AbstractItemModel> model = this->getModel();
    if (!model)
    {
        OMNIUI_LOG_WARN("ColorWidget::onModelUpdated called without a model");
        return;
    }

    auto modelChildItems = model->getItemChildren();
    data.m_componentsNumber = maxColorChildren(modelChildItems);

    for (size_t index = 0; index < data.m_componentsNumber; ++index)
    {
        auto subModel = model->getItemValueModel(modelChildItems[index]);
        if (subModel)
        {
            data.m_colorBuffer[index] = static_cast<float>(subModel->getValue<double>());
        }
        else
        {
            OMNIUI_LOG_WARN("ColorWidget::onModelUpdated has no submodel for index: %zu", index);
        }
    }
}

void ColorWidget::_drawPopup(float elapsedTime, ImGuiColorEditFlags flags)
{
    bool changed = false;
    auto& data = _getData<ColorWidgetData>();

    // Temporary buffer. We can't pass m_colorBuffer because ImGui will change it. Only model can change it.
    ImVec4 colorBuffer{ data.m_colorBuffer[0], data.m_colorBuffer[1], data.m_colorBuffer[2], data.m_colorBuffer[3] };

    // We need to create the picker to track if it was opened and closed.
    const float height = ImGui::GetFrameHeight();

    // Avoid the current broken return a reference to shared_ptr API omni.ui has for now.
    std::shared_ptr<AbstractItemModel> model = this->getModel();

    if (!data.m_popupUsed && !ImGui::IsPopupOpen(kColorPickerName))
    {
        ImGui::OpenPopup(kColorPickerName);
        if (model)
        {
            model->processBeginEditCallbacks(nullptr);
        }
        this->forceRasterDirty(BakeDirtyReason::eEditBegan);
        data.m_popupUsed = true;
    }

    if (ImGui::BeginPopup(kColorPickerName)) {
        ImGuiColorEditFlags pickerFlagToForward = ImGuiColorEditFlags_DataTypeMask_ | ImGuiColorEditFlags_PickerMask_ |
                                                    ImGuiColorEditFlags_InputMask_ | ImGuiColorEditFlags_HDR |
                                                    ImGuiColorEditFlags_NoAlpha | ImGuiColorEditFlags_AlphaBar;
        ImGuiColorEditFlags pickerFlags = (flags & pickerFlagToForward) | ImGuiColorEditFlags_DisplayMask_ |
                                            ImGuiColorEditFlags_NoLabel | ImGuiColorEditFlags_AlphaPreviewHalf;
        // 12xheight is the constant from ImGui
        ImGui::SetNextItemWidth(height * 12.0f);
        if (data.m_componentsNumber == 4)
        {
            changed = ImGui::ColorPicker4("##picker", &colorBuffer.x, pickerFlags);
        }
        else
        {
            changed = ImGui::ColorPicker3("##picker", &colorBuffer.x, pickerFlags);
        }

        ImGui::EndPopup();
    }

    if (changed && memcmp(data.m_colorBuffer, &colorBuffer.x, sizeof(data.m_colorBuffer)) != 0)
    {
        // Color is changed. We need to change the model.
        if (model)
        {
            auto modelChildItems = model->getItemChildren();
            for (size_t i = 0, n = maxColorChildren(modelChildItems); i < n; ++i)
            {
                if (data.m_colorBuffer[i] == (&colorBuffer.x)[i])
                {
                    continue;
                }

                auto subModel = model->getItemValueModel(modelChildItems[i]);
                if (subModel)
                {
                    subModel->setValue((&colorBuffer.x)[i]);
                }
                else
                {
                    OMNIUI_LOG_WARN("ColorWidget::_drawPopup has no submodel for index: %zu", i);
                }
            }
        }
        else
        {
            OMNIUI_LOG_WARN("ColorWidget::_drawPopup changed without a model");
        }
    }

    if (data.m_popupUsed && !ImGui::IsPopupOpen(kColorPickerName))
    {
        if (model)
        {
            model->processEndEditCallbacks(nullptr);
        }
        this->forceRasterDirty(BakeDirtyReason::eEditEnded);
        this->_removePopup();
    }
}

void ColorWidget::_removePopup()
{
    auto& data = _getData<ColorWidgetData>();
    if (data.m_appWindow && data.m_uiWindow)
    {
        ui::windowmanager::IWindowCallbackManager* uiWindowManager =
            PlatformRegistry::instance().windowCallbackManager();
        uiWindowManager->removeAppWindowCallback(data.m_appWindow, data.m_uiWindow.get());
    }
    data.m_appWindow = nullptr;
    data.m_uiWindow = nullptr;
}

void ColorWidget::_drawContent(float elapsedTime)
{
    float dpiScale = this->getDpiScale();
    auto cursor = ImGui::GetCursorScreenPos();
    float computedWidth = this->getComputedContentWidth();
    float computedHeight = this->getComputedContentHeight();

    // NoPicker because we create it here
    // NoTooltip because it shows up in the top left corner, rather than by the cursor
    ImGuiColorEditFlags flags = ImGuiColorEditFlags_NoInputs | ImGuiColorEditFlags_NoLabel |
                                ImGuiColorEditFlags_NoSidePreview | ImGuiColorEditFlags_NoDragDrop |
                                ImGuiColorEditFlags_Float | ImGuiColorEditFlags_NoPicker | ImGuiColorEditFlags_NoTooltip;

    ImGui::PushID(this);


    // Temporary buffer. We can't pass m_colorBuffer because ImGui will change it. Only model can change it.
    auto& data = _getData<ColorWidgetData>();
    ImVec4 colorBuffer{ data.m_colorBuffer[0], data.m_colorBuffer[1], data.m_colorBuffer[2], data.m_colorBuffer[3] };

    // Minimal StyleContainer
    int32_t popStyleColors = 0;
    int32_t popStyleVars = 0;

    float borderRadius = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &borderRadius))
    {
        borderRadius *= dpiScale;
    }

    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, borderRadius);
    popStyleVars++;

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
    }

    uint32_t borderColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &borderColor))
    {
        ImGui::PushStyleColor(ImGuiCol_FrameBg, borderColor);

        popStyleColors++;
    }

    uint32_t color;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &color))
    {
        // Set the text color of the tooltip.
        ImGui::PushStyleColor(ImGuiCol_Text, color);

        popStyleColors++;
    }

    uint32_t backgroundColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor))
    {
        // Set the bg color of the tooltip.
        ImGui::PushStyleColor(ImGuiCol_PopupBg, color);

        popStyleColors++;
    }

    ImGui::ColorButton("##hidelabel", colorBuffer, flags, { computedWidth, computedHeight });

    // Draw rectangle
    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        // Draw a border on top of rectangle.
        ImVec2 rectMax{ cursor.x + computedWidth, cursor.y + computedHeight };
        ImGui::GetWindowDrawList()->AddRect(
            cursor, rectMax, borderColor, borderRadius, ImDrawFlags_RoundCornersAll, borderWidth);
    }

    ImGui::PopStyleColor(popStyleColors);
    ImGui::PopStyleVar(popStyleVars);

    if (this->isEnabled() && isHovered() && ImGui::IsMouseReleased(0))
    {
        data.m_popupUsed = false;  // reset so clicking the color button can bring up a new popup
        if (static_cast<bool>(data.m_uiWindow) == false)
        {
            auto uiWindowManager = PlatformRegistry::instance().windowCallbackManager();
            data.m_appWindow = Workspace::AppWindow::instance().getCurrent();

            // Setup the AppWindow callback with a weak-ptr to this.
            //
            data.m_uiWindow = ui::windowmanager::createAppWindowCallback(data.m_appWindow, uiWindowManager, kColorPickerName,
                0, 0, ui::windowmanager::DockPreference::eDisabled,
                [weakPtr = weak_from_this(), flags](float elapsedTime) {
                    std::shared_ptr<ColorWidget> sharedThis = std::static_pointer_cast<ColorWidget>(weakPtr.lock());
                    if (sharedThis)
                    {
                        sharedThis->_drawPopup(elapsedTime, flags);
                    }
                });
        }
        else
        {
            OMNIUI_LOG_WARN("ColorWidget::_drawContent already has a valid omni::ui::windowmanager::IWindowCallbackPtr");
        }
    }

    ImGui::PopID();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
