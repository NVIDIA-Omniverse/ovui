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

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/Subscription.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <imgui/imgui.h>

#include <cstdint>

#include "PlatformBindings.h"

#ifdef OMNIUI_PYBIND_EMBEDDED
#    include <pybind11/embed.h>
#    define OMNIUI_PYBIND_MODULE PYBIND11_EMBEDDED_MODULE
#else
#    define OMNIUI_PYBIND_MODULE PYBIND11_MODULE
#endif

#include "BindAbstractField.h"
#include "BindAbstractItemDelegate.h"
#include "BindAbstractItemModel.h"
#include "BindAbstractMultiField.h"
#include "BindAbstractSlider.h"
#include "BindAbstractValueModel.h"
#include "BindAlignment.h"
#include "BindArrowHelper.h"
#include "BindAxis.h"
#include "BindBezierCurve.h"
#include "BindButton.h"
#include "BindCanvasFrame.h"
#include "BindCheckBox.h"
#include "BindCircle.h"
#include "BindCollapsableFrame.h"
#include "BindColorWidget.h"
#include "BindComboBox.h"
#include "BindContainer.h"
#include "BindDockSpace.h"
#include "BindEllipse.h"
#include "BindFloatDrag.h"
#include "BindFloatField.h"
#include "BindFloatSlider.h"
#include "BindFont.h"
#include "BindFrame.h"
#include "BindFreeShape.h"
#include "BindGlyph.h"
#include "BindGrid.h"
#include "BindHGrid.h"
#include "BindHStack.h"
#include "BindImage.h"
#include "BindImageWithProvider.h"
#include "BindInspector.h"
#include "BindIntDrag.h"
#include "BindIntField.h"
#include "BindIntSlider.h"
#include "BindInvisibleButton.h"
#include "BindItemModelHelper.h"
#include "BindLabel.h"
#include "BindMarkdownWidget.h"
#include "BindStringFieldLimited.h"
#include "BindLength.h"
#include "BindLine.h"
#include "BindMainWindow.h"
#include "BindMenu.h"
#include "BindMenuBar.h"
#include "BindMenuDelegate.h"
#include "BindMenuHelper.h"
#include "BindMenuItem.h"
#include "BindMenuItemCollection.h"
#include "BindMultiDragField.h"
#include "BindMultiField.h"
#include "BindOffsetLine.h"
#include "BindPixelFormat.h"
#include "BindPlacer.h"
#include "BindPlot.h"
#include "BindProgressBar.h"
#include "BindRadioButton.h"
#include "BindRadioCollection.h"
#include "BindRasterPolicy.h"
#include "BindRectangle.h"
#include "BindScrollBarPolicy.h"
#include "BindScrollingFrame.h"
#include "BindSeparator.h"
#include "BindShadowFlag.h"
#include "BindShape.h"
#include "BindShapeAnchorHelper.h"
#include "BindSimpleListModel.h"
#include "BindSpacer.h"
#include "BindStack.h"
#include "BindStringField.h"
#include "BindStyle.h"
#include "BindStyleContainer.h"
#include "BindStyleStore.h"
#include "BindToolBar.h"
#include "BindToolButton.h"
#include "BindTreeView.h"
#include "BindTriangle.h"
#include "BindValueModelHelper.h"
#include "BindVGrid.h"
#include "BindVStack.h"
#include "BindWidget.h"
#include "BindWindow.h"
#include "BindWindowHandle.h"
#include "BindWorkspace.h"
#include "BindZStack.h"

#include "ImageProvider/BindByteImageProvider.h"
#include "ImageProvider/BindDynamicTextureProvider.h"
#include "ImageProvider/BindImageProvider.h"
#include "ImageProvider/BindRasterImageProvider.h"
#include "ImageProvider/BindVectorImageProvider.h"

namespace
{
ImVec4 colorStoreValueToImVec4(uint32_t color)
{
    return ImVec4(
        static_cast<float>(color & 0xFF) / 255.0f,
        static_cast<float>((color >> 8) & 0xFF) / 255.0f,
        static_cast<float>((color >> 16) & 0xFF) / 255.0f,
        static_cast<float>((color >> 24) & 0xFF) / 255.0f);
}
}

OMNIUI_PYBIND_MODULE(_ui, m)
{
    OMNIUI_BIND(Alignment);
    OMNIUI_BIND(RasterPolicy);
    OMNIUI_BIND(Axis);
    OMNIUI_BIND(CornerFlag);
    OMNIUI_BIND(ShadowFlag);
    OMNIUI_BIND(Length);
    OMNIUI_BIND(ScrollBarPolicy);

    // Register Subscription type so pybind11 can convert std::shared_ptr<Subscription> return values
    pybind11::class_<omni::ui::Subscription, std::shared_ptr<omni::ui::Subscription>>(m, "Subscription")
        .def("unsubscribe", &omni::ui::Subscription::unsubscribe);

    OMNIUI_BIND(AbstractValueModel);
    OMNIUI_BIND(AbstractItemModel);
    OMNIUI_BIND(AbstractItemDelegate);
    OMNIUI_BIND(ValueModelHelper);
    OMNIUI_BIND(RadioCollection);
    OMNIUI_BIND(Widget);
    OMNIUI_BIND(Container);
    OMNIUI_BIND(Stack);
    OMNIUI_BIND(HStack);
    OMNIUI_BIND(VStack);
    OMNIUI_BIND(ZStack);
    OMNIUI_BIND(Grid);
    OMNIUI_BIND(HGrid);
    OMNIUI_BIND(VGrid);
    OMNIUI_BIND(Frame);
    OMNIUI_BIND(CollapsableFrame);
    OMNIUI_BIND(ScrollingFrame);
    OMNIUI_BIND(CanvasFrame);
    OMNIUI_BIND(InvisibleButton);
    OMNIUI_BIND(Button);
    OMNIUI_BIND(ToolButton);
    OMNIUI_BIND(RadioButton);
    OMNIUI_BIND(AbstractSlider);
    OMNIUI_BIND(FloatSlider);
    OMNIUI_BIND(IntSlider);
    OMNIUI_BIND(FloatDrag);
    OMNIUI_BIND(IntDrag);
    OMNIUI_BIND(CheckBox);
    OMNIUI_BIND(ItemModelHelper);
    OMNIUI_BIND(SimpleListModel);
    OMNIUI_BIND(ColorWidget);
    OMNIUI_BIND(TreeView);
    OMNIUI_BIND(ComboBox);
    OMNIUI_BIND(AbstractMultiField);
    OMNIUI_BIND(MultiField);
    OMNIUI_BIND(MultiDragField);
    OMNIUI_BIND(Shape);
    OMNIUI_BIND(ShapeAnchorHelper);
    OMNIUI_BIND(Field);
    OMNIUI_BIND(FloatField);
    OMNIUI_BIND(IntField);
    OMNIUI_BIND(StringField);
    OMNIUI_BIND(StringFieldLimited);
    OMNIUI_BIND(ArrowHelper);
    OMNIUI_BIND(BezierCurve);
    OMNIUI_BIND(Rectangle);
    OMNIUI_BIND(Circle);
    OMNIUI_BIND(Ellipse);
    OMNIUI_BIND(Triangle);
    OMNIUI_BIND(Line);
    OMNIUI_BIND(FreeShape);
    OMNIUI_BIND(OffsetLine);
    OMNIUI_BIND(Spacer);
    OMNIUI_BIND(Label);
    OMNIUI_BIND(MarkdownWidget);
    OMNIUI_BIND(Image);
    OMNIUI_BIND(ImageWithProvider);
    OMNIUI_BIND(PixelFormat);
    OMNIUI_BIND(ImageProvider);
    OMNIUI_BIND(ByteImageProvider);
    OMNIUI_BIND(RasterImageProvider);
    OMNIUI_BIND(VectorImageProvider);
    OMNIUI_BIND(DynamicTextureProvider);
    OMNIUI_BIND(MenuDelegate);
    OMNIUI_BIND(MenuHelper);
    OMNIUI_BIND(Menu);
    OMNIUI_BIND(MenuBar);
    OMNIUI_BIND(MenuItem);
    OMNIUI_BIND(MenuItemCollection);
    OMNIUI_BIND(Separator);
    OMNIUI_BIND(WindowHandle);
    OMNIUI_BIND(Window);
    OMNIUI_BIND(MainWindow);
    OMNIUI_BIND(Workspace);
    OMNIUI_BIND(Placer);
    OMNIUI_BIND(Plot);
    OMNIUI_BIND(ToolBar);
    OMNIUI_BIND(Font);
    OMNIUI_BIND(Glyph);
    OMNIUI_BIND(ProgressBar);
    OMNIUI_BIND(DockSpace);
    OMNIUI_BIND(Style);
    OMNIUI_BIND(Inspector);
    OMNIUI_BIND(ColorStore);

    m.def(
        "apply_imgui_docking_style",
        [](float visualWidth,
           float hoverPadding,
           float tabCloseMinWidthSelected,
           float tabCloseMinWidthUnselected,
           float tabBarOverlineSize,
           float tabRounding,
           float tabHeight,
           float tabBorderSize,
           float tabBarBorderSize,
           float dockTabInactiveSeparatorInset,
           bool dockTabUseTabColors,
           bool dockTabSingleTabUsesSelectedColor,
           bool dockTabDrawInactiveSeparators,
           bool tabUseRectangularShape,
           uint32_t dockTabTextColor,
           uint32_t splitterHandleColor,
           uint32_t splitterHandleHoveredColor,
           uint32_t dockTabHoveredColor,
           uint32_t dockTabColor,
           uint32_t dockTabSelectedColor,
           uint32_t dockTabSelectedOverlineColor,
           uint32_t dockTabDimmedColor,
           uint32_t dockTabDimmedSelectedColor,
           uint32_t dockTabDimmedSelectedOverlineColor) {
            if (ImGui::GetCurrentContext() == nullptr)
                return false;

            ImGuiStyle& style = ImGui::GetStyle();
            style.DockingSeparatorSize = visualWidth;
            style.WindowBorderHoverPadding = hoverPadding;
            style.TabCloseButtonMinWidthSelected = tabCloseMinWidthSelected;
            style.TabCloseButtonMinWidthUnselected = tabCloseMinWidthUnselected;
            style.TabBarOverlineSize = tabBarOverlineSize;
            style.TabRounding = tabRounding;
            style.TabBorderSize = tabBorderSize;
            style.TabBarBorderSize = tabBarBorderSize;
            style.DockingNodeHasCloseButton = false;
            style.DockingTabBarHeight = tabHeight;
            style.DockingTabBarUseTabColors = dockTabUseTabColors;
            style.DockingTabBarUseSelectedColorForSingleTab = dockTabSingleTabUsesSelectedColor;
            style.DockingTabBarShowInactiveTabSeparators = dockTabDrawInactiveSeparators;
            style.DockingTabInactiveSeparatorInset = dockTabInactiveSeparatorInset;
            style.TabUseRectangularShape = tabUseRectangularShape;

            const ImVec4 splitter = colorStoreValueToImVec4(splitterHandleColor);
            const ImVec4 splitterHovered = colorStoreValueToImVec4(splitterHandleHoveredColor);
            const ImVec4 selected = colorStoreValueToImVec4(dockTabSelectedColor);
            style.Colors[ImGuiCol_Text] = colorStoreValueToImVec4(dockTabTextColor);
            style.Colors[ImGuiCol_Border] = splitter;
            style.Colors[ImGuiCol_Separator] = splitter;
            style.Colors[ImGuiCol_SeparatorHovered] = splitterHovered;
            style.Colors[ImGuiCol_SeparatorActive] = splitterHovered;
            style.Colors[ImGuiCol_ResizeGrip] = splitter;
            style.Colors[ImGuiCol_ResizeGripHovered] = splitterHovered;
            style.Colors[ImGuiCol_ResizeGripActive] = splitterHovered;
            style.Colors[ImGuiCol_TitleBg] = selected;
            style.Colors[ImGuiCol_TitleBgActive] = selected;
            style.Colors[ImGuiCol_TitleBgCollapsed] = selected;
            style.Colors[ImGuiCol_TabHovered] = colorStoreValueToImVec4(dockTabHoveredColor);
            style.Colors[ImGuiCol_Tab] = colorStoreValueToImVec4(dockTabColor);
            style.Colors[ImGuiCol_TabSelected] = selected;
            style.Colors[ImGuiCol_TabSelectedOverline] = colorStoreValueToImVec4(dockTabSelectedOverlineColor);
            style.Colors[ImGuiCol_TabDimmed] = colorStoreValueToImVec4(dockTabDimmedColor);
            style.Colors[ImGuiCol_TabDimmedSelected] = colorStoreValueToImVec4(dockTabDimmedSelectedColor);
            style.Colors[ImGuiCol_TabDimmedSelectedOverline] =
                colorStoreValueToImVec4(dockTabDimmedSelectedOverlineColor);
            return true;
        },
        pybind11::arg("visual_width"),
        pybind11::arg("hover_padding"),
        pybind11::arg("tab_close_min_width_selected"),
        pybind11::arg("tab_close_min_width_unselected"),
        pybind11::arg("tab_bar_overline_size"),
        pybind11::arg("tab_rounding"),
        pybind11::arg("tab_height"),
        pybind11::arg("tab_border_size"),
        pybind11::arg("tab_bar_border_size"),
        pybind11::arg("dock_tab_inactive_separator_inset"),
        pybind11::arg("dock_tab_use_tab_colors"),
        pybind11::arg("dock_tab_single_tab_uses_selected_color"),
        pybind11::arg("dock_tab_draw_inactive_separators"),
        pybind11::arg("tab_use_rectangular_shape"),
        pybind11::arg("dock_tab_text_color"),
        pybind11::arg("splitter_handle_color"),
        pybind11::arg("splitter_handle_hovered_color"),
        pybind11::arg("dock_tab_hovered_color"),
        pybind11::arg("dock_tab_color"),
        pybind11::arg("dock_tab_selected_color"),
        pybind11::arg("dock_tab_selected_overline_color"),
        pybind11::arg("dock_tab_dimmed_color"),
        pybind11::arg("dock_tab_dimmed_selected_color"),
        pybind11::arg("dock_tab_dimmed_selected_overline_color"),
        "Apply OVUI docking splitter and document-tab style tokens.");

    omni::ui::registerPlatformBindings(m);

    // Capability probe — true iff a backend implementing the fromGpu=true
    // branch of ByteImageProvider.set_bytes_data_from_gpu is registered.
    // Lets downstream callers (e.g. ovgear ZeroCopyState) decide whether to
    // attempt tier-2 without scraping stderr for "fromGpu not supported".
    m.def("has_gpu_byte_image", []() {
        auto* g = omni::ui::PlatformRegistry::instance().byteImageGpu();
        return g != nullptr && g->supportsFromGpu();
    }, "Whether ByteImageProvider.set_bytes_data_from_gpu is wired to a real CUDA-Vulkan path.");
}
