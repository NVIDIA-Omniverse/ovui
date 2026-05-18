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

#pragma once

#include "Api.h"
#include "Callback.h"
#include "Length.h"
#include "Object.h"
#include "Property.h"
#include "StyleContainer.h"

#include "Types.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Frame;
class Window;

/**
 * @brief The Widget class is the base class of all user interface objects.
 *
 * The widget is the atom of the user interface: it receives mouse, keyboard and other events, and paints a
 * representation of itself on the screen. Every widget is rectangular. A widget is clipped by its parent and by the
 * widgets in front of it.
 */
class OMNIUI_CLASS_API Widget : public std::enable_shared_from_this<Widget>, protected CallbackHelper<Widget>
{
    OMNIUI_OBJECT_BASE(Widget)

public:
    /**
     * @brief Holds the data which is sent when a drag and drop action is completed.
     */
    struct MouseDropEvent
    {
        /**
         * @brief Position where the drop was made.
         */
        float x;

        /**
         * @brief Position where the drop was made.
         */
        float y;

        /**
         * @brief The data that was dropped on the widget.
         *
         */
        std::string mimeData;
    };

    /**
     * @brief Width/height can be dirty for different reason. To skip
     * computation of children we need to know the reason why the size is
     * recomputed.
     */
    enum class SizeDirtyReason
    {
        eNone = 0,
        eSizeChanged,
        eChildDirty,
        eParentDirty,
    };

    /**
     * @brief We need to know the reason for the re-bake to optimize the process
     * and avoid re-baking in some particular cases.
     */
    enum class BakeDirtyReason
    {
        eNone = 0,
        eChildDirty,
        eContentChanged,
        eEditBegan,
        eEditEnded,
        eLodDirty,
    };

    using Bool3 = bool[3];

    /**
     * @brief Holds widget bounds for mouse events.
     */
    struct BoundingBox
    {
        float min[2];
        float max[2];
    };

    /**
     * @brief When WantCaptureKeyboard, omni.ui is using the keyboard input exclusively, e.g. InputText active, etc.
     */
    OMNIUI_API
    static constexpr uint32_t kModifierFlagWantCaptureKeyboard = (1 << 30);

    /**
     * @brief Conform incoming string with the requirements for being used in .identifier property
     */
    OMNIUI_API
    static std::string normalizeIdentifier(const std::string& str);

    OMNIUI_API
    virtual ~Widget();

    /**
     * @brief Removes all the callbacks and circular references.
     */
    OMNIUI_API
    virtual void destroy();

    // We assume that all the operations with all the widgets should be performed with smart pointers because we have
    // parent-child relationships, and we automatically put new widgets to parents in the create method of every widget.
    // If the object is copied or moved, it will break the Widget-Container hierarchy.
    // No copy
    Widget(const Widget&) = delete;
    // No copy-assignment
    Widget& operator=(const Widget&) = delete;
    // No move constructor and no move-assignments are allowed because of 12.8 [class.copy]/9 and 12.8 [class.copy]/20
    // of the C++ standard

    /**
     * @brief Execute the rendering code of the widget, that includes the work with inputs and run _drawContent() that
     * can be implemented by derived clrasses.
     *
     * @note It's in the public section because it's not possible to put it to the protected section. If it's in the
     * protected, then other widgets that have child widgets will not be able to call it.
     *
     * Even though access control in C++ works on a per-class basis, protected access specifier has some peculiarities.
     * The language specification wants to ensure that it's not possible to access a protected member of some base
     * subobject that belongs to the derived class. We are not supposed to be able to access protected members of some
     * unrelated independent objects of the base type. In particular, it's not possible to access protected members of
     * freestanding objects of the base type. It's only possible to access protected members of base objects that are
     * embedded into derived objects as base subobjects.
     *
     * Example:
     *
     *    class Widget
     *    {
     *    protected:
     *        virtual void draw()
     *        {
     *        }
     *    };
     *
     *    class Frame : public Widget
     *    {
     *    protected:
     *        void draw() override
     *        {
     *            // error C2248: 'Widget::draw': cannot access protected member declared in class 'Widget'
     *            m_child.draw();
     *        }
     *
     *    private:
     *        Widget m_child;
     *    };
     *
     * Also, it's not possible to use friendship because friendship is neither inherited nor transitive. It means it's
     * necessary to list all the classes that can use sub-objects explicitly. And in this way, custom extensions will
     * not be able to use sub-objects.
     *
     * @param elapsedTime The time elapsed (in seconds)
     */
    OMNIUI_API
    void draw(float elapsedTime);

    /**
     * @brief Returns the final computed width of the widget. It includes margins.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    float getComputedWidth() const;

    /**
     * @brief Returns the final computed width of the content of the widget.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    virtual float getComputedContentWidth() const;

    /**
     * @brief Sets the computed width. It subtract margins and calls setComputedContentWidth.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    void setComputedWidth(float width);

    /**
     * @brief The widget provides several functions that deal with a widget's geometry. Indicates the content width hint
     * that represents the preferred size of the widget. The widget is free to readjust its geometry to fit the content
     * when it's necessary.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    virtual void setComputedContentWidth(float width);

    /**
     * @brief Returns the final computed height of the widget. It includes margins.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    float getComputedHeight() const;

    /**
     * @brief Returns the final computed height of the content of the widget.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    virtual float getComputedContentHeight() const;

    /**
     * @brief Sets the computed height. It subtract margins and calls setComputedContentHeight.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    void setComputedHeight(float height);

    /**
     * @brief The widget provides several functions that deal with a widget's geometry. Indicates the content height
     * hint that represents the preferred size of the widget. The widget is free to readjust its geometry to fit the
     * content when it's necessary.
     *
     * @note It's in puplic section. For the explanation why please see the draw() method.
     */
    OMNIUI_API
    virtual void setComputedContentHeight(float height);

    /**
     * @brief Returns the X Screen coordinate the widget was last draw.
     * This is in Screen Pixel size
     *
     * It's float because we need negative numbers and precise position considering DPI scale factor.
     */
    OMNIUI_API
    float getScreenPositionX() const;

    /**
     * @brief Returns the Y Screen coordinate the widget was last draw.
     * This is in Screen Pixel size
     *
     * It's float because we need negative numbers and precise position considering DPI scale factor.
     */
    OMNIUI_API
    float getScreenPositionY() const;

    /**
     * @brief Sets the function that will be called when the user moves the mouse inside the widget. Mouse move events
     * only occur if a mouse button is pressed while the mouse is being moved.
     *     void onMouseMoved(float x, float y, int32_t modifier)
     *
     * TODO: Add "mouse tracking property". If mouse tracking is switched on, mouse move events occur even if no mouse
     * button is pressed.
     */
    OMNIUI_CALLBACK(MouseMoved, void, float, float, int32_t, Bool3);

    /**
     * @brief Sets the function that will be called when the user presses the mouse button inside the widget. The
     * function should be like this:
     *     void onMousePressed(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     * Where:
     *     'button' is the number of the mouse button pressed.
     *     'modifier' is the flag for the keyboard modifier key.
     */
    OMNIUI_CALLBACK(MousePressed, void, float, float, int32_t, KeyboardModifierFlags);

    /**
     * @brief Sets the function that will be called when the user releases the mouse button if this button was pressed
     * inside the widget.
     *     void onMouseReleased(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     */
    OMNIUI_CALLBACK(MouseReleased, void, float, float, int32_t, KeyboardModifierFlags);

    /**
     * @brief Sets the function that will be called when the user presses the mouse button twice inside the widget. The
     * function specification is the same as in setMousePressedFn.
     *     void onMouseDoubleClicked(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     */
    OMNIUI_CALLBACK(MouseDoubleClicked, void, float, float, int32_t, KeyboardModifierFlags);

    /**
     * @brief Sets the function that will be called when the user uses mouse wheel on the focused window. The
     * function specification is the same as in setMousePressedFn.
     *      void onMouseWheel(float x, float y, KeyboardModifierFlags modifier)
     */
    OMNIUI_CALLBACK(MouseWheel, void, float, float, KeyboardModifierFlags);

    /**
     * @brief Sets the function that will be called when the user use mouse enter/leave on the focused window.
     * function specification is the same as in setMouseHovedFn.
     *     void onMouseHovered(bool hovered)
     */
    OMNIUI_CALLBACK(MouseHovered, void, bool);

    /**
     * @brief Sets the function that will be called when the user presses the keyboard key when the mouse clicks the
     * widget.
     */
    OMNIUI_CALLBACK(KeyPressed, void, int32_t, KeyboardModifierFlags, bool);

    /**
     * @brief Specify that this Widget is draggable, and set the callback that is attached to the drag operation.
     */
    OMNIUI_CALLBACK(Drag, std::string);

    /**
     * @brief Specify that this Widget can accept specific drops and set the callback that is called to check if the
     * drop can be accepted.
     */
    OMNIUI_CALLBACK(AcceptDrop, bool, const std::string&);

    /**
     * @brief Specify that this Widget accepts drops and set the callback to the drop operation.
     */
    OMNIUI_CALLBACK(Drop, void, const MouseDropEvent&);

    /**
     * @brief Called when the size of the widget is changed.
     */
    OMNIUI_CALLBACK(ComputedContentSizeChanged, void);

    /**
     * @brief If the widgets has callback functions it will by default not capture the events if it is the top most
     * widget and setup this option to true, so they don't get routed to the child widgets either
     */
    OMNIUI_PROPERTY(bool, opaqueForMouseEvents, DEFAULT, false, READ, isOpaqueForMouseEvents, WRITE, setOpaqueForMouseEvents);

    /**
     * @brief The mouse hover state will be judged more strictly. If there is any overlapping widget,
     * no mouse event will be responded.
     */
    OMNIUI_PROPERTY(bool, explicitHover, DEFAULT, false, READ, isExplicitHover, WRITE, setExplicitHover);

    /**
     * @brief Set the current style. The style contains a description of customizations to the widget's style
     */
    OMNIUI_API
    void setStyle(const StyleContainer& style);
    OMNIUI_API
    void setStyle(StyleContainer&& style);

    /**
     * @brief Recompute internal cached data that is used for styling. Unlike cascadeStyle, updateStyle is called when
     * the name or type of the widget is changed.
     */
    OMNIUI_API
    void updateStyle();

    /**
     * @brief It's called when the style is changed. It should be propagated to children to make the style cached and
     * available to children.
     */
    OMNIUI_API
    virtual void cascadeStyle();

    /**
     * @brief Called when the style is changed. The child classes can use it to propagate the style to children.
     */
    OMNIUI_API
    virtual void onStyleUpdated();

    /**
     * @brief The ability to skip margins. It's useful when the widget is a part of compound widget and should be of
     * exactly provided size. Like Rectangle of the Button.
     */
    OMNIUI_API
    void useMarginFromStyle(bool use);

    /**
     * @brief Adjust scrolling amount to make current item visible.
     *
     * @param[in] centerRatio 0.0: left, 0.5: center, 1.0: right
     */
    OMNIUI_API
    void scrollHereX(float centerRatio = 0.f);

    /**
     * @brief Adjust scrolling amount to make current item visible.
     *
     * @param[in] centerRatio 0.0: top, 0.5: center, 1.0: bottom
     */
    OMNIUI_API
    void scrollHereY(float centerRatio = 0.f);

    /**
     * @brief Adjust scrolling amount in two axes to make current item visible.
     *
     * @param[in] centerRatioX 0.0: left, 0.5: center, 1.0: right
     * @param[in] centerRatioY 0.0: top, 0.5: center, 1.0: bottom
     */
    OMNIUI_API
    void scrollHere(float centerRatioX = 0.f, float centerRatioY = 0.f);

    /**
     * @brief Return the application DPI factor multiplied by the widget scale.
     */
    OMNIUI_API float getDpiScale() const;

    /**
     * @brief Next frame content width will be forced to recompute.
     */
    OMNIUI_API virtual void forceWidthDirty(SizeDirtyReason reason);

    /**
     * @brief Next frame content height will be forced to recompute.
     */
    OMNIUI_API virtual void forceHeightDirty(SizeDirtyReason reason);

    /**
     * @brief Next frame the content will be forced to re-bake.
     */
    OMNIUI_API virtual void forceRasterDirty(BakeDirtyReason reason);

    /**
     * @brief Next frame content width will be forced to recompute.
     */
    OMNIUI_API virtual void forceWidthDirty();

    /**
     * @brief Next frame content height will be forced to recompute.
     */
    OMNIUI_API virtual void forceHeightDirty();

    /**
     * @brief Change dirty bits when the visibility is changed. It's public because other widgets have to call it.
     *
     * @param visible True when the widget is completely rendered. False when early exit.
     * @param dirtySize True to set the size diry bits.
     */
    OMNIUI_API virtual void setVisiblePreviousFrame(bool visible, bool dirtySize = true);

    /**
     * @brief This property holds whether the widget is visible.
     */
    OMNIUI_PROPERTY(
        bool, visible, DEFAULT, true, READ, isVisible, WRITE, setVisible, PROTECTED, NOTIFY, _setVisibleChangedFn);

    /**
     * @brief If the current zoom factor and DPI is less than this value, the widget is not visible.
     */
    OMNIUI_PROPERTY(
        float, visibleMin, DEFAULT, 0.0f, READ, getVisibleMin, WRITE, setVisibleMin, PROTECTED, NOTIFY, _setVisibleMinChangedFn);

    /**
     * @brief If the current zoom factor and DPI is bigger than this value, the widget is not visible.
     */
    OMNIUI_PROPERTY(
        float, visibleMax, DEFAULT, 0.0f, READ, getVisibleMax, WRITE, setVisibleMax, PROTECTED, NOTIFY, _setVisibleMaxChangedFn);

    /**
     * @brief This property holds whether the widget is enabled. In general an enabled widget handles keyboard and mouse
     * events; a disabled widget does not. And widgets display themselves differently when they are disabled.
     */
    OMNIUI_PROPERTY(bool, enabled, DEFAULT, true, READ, isEnabled, WRITE, setEnabled, NOTIFY, setEnabledChangedFn);

    /**
     * @brief This property holds a flag that specifies the widget has to use eSelected state of the style.
     */
    OMNIUI_PROPERTY(bool, selected, DEFAULT, false, READ, isSelected, WRITE, setSelected, NOTIFY, setSelectedChangedFn);

    /**
     * @brief This property holds a flag that specifies the widget has to use eChecked state of the style. It's on the
     * Widget level because the button can have sub-widgets that are also should be checked.
     */
    OMNIUI_PROPERTY(bool, checked, DEFAULT, false, READ, isChecked, WRITE, setChecked, NOTIFY, setCheckedChangedFn);

    /**
     * @brief This property holds the width of the widget relative to its parent. Do not use this function to find the
     * width of a screen.
     *
     * TODO: Widget Geometry documentation for an overview of geometry issues and layouting.
     */
    OMNIUI_PROPERTY(
        Length, width, DEFAULT, Fraction{ 1.0f }, READ, getWidth, WRITE, setWidth, PROTECTED, NOTIFY, _setWidthChangedFn);

    /**
     * @brief This property holds the height of the widget relative to its parent. Do not use this function to find the
     * height of a screen.
     *
     * TODO: Widget Geometry documentation for an overview of geometry issues and layouting.
     */
    OMNIUI_PROPERTY(
        Length, height, DEFAULT, Fraction{ 1.0f }, READ, getHeight, WRITE, setHeight, PROTECTED, NOTIFY, _setHeightChangedFn);

    /**
     * @brief This property holds if the widget is being dragged.
     */
    OMNIUI_PROPERTY(bool, dragging, DEFAULT, false, READ, isDragging, WRITE, setDragging);

    /**
     * @brief The name of the widget that user can set.
     */
    OMNIUI_PROPERTY(std::string, name, READ, getName, WRITE, setName, NOTIFY, setNameChangedFn);

    /**
     * @brief By default, we use typeName to look up the style. But sometimes it's necessary to use a custom name. For
     * example, when a widget is a part of another widget. (Label is a part of Button) This property can override the
     * name to use in style.
     */
    OMNIUI_PROPERTY(std::string,
                    styleTypeNameOverride,
                    READ,
                    getStyleTypeNameOverride,
                    WRITE,
                    setStyleTypeNameOverride,
                    NOTIFY,
                    setStyleTypeNameOverrideChangedFn);

    /**
     * @brief Protected weak pointer to the parent object. We need it to query the parent style. Parent can be a
     * Container or another widget if it holds sub-widgets.
     */
    OMNIUI_PROPERTY(
        Widget*, parent, DEFAULT, nullptr, PROTECTED, READ_VALUE, getParent, WRITE, setParent, NOTIFY, setParentChangedFn);

    /**
     * @brief The local style. When the user calls `setStyle()`, it saves the given style to this property and creates a
     * new style that is the result of the parent style and the given style.
     */
    OMNIUI_PROPERTY(std::shared_ptr<StyleContainer>, style, READ, getStyle, WRITE, setStyle, NOTIFY, setStyleChangedFn);

    /**
     * @brief Set a basic tooltip for the widget, this will simply be a Label, it will follow the Tooltip style
     */
    OMNIUI_PROPERTY(std::string, tooltip, READ, getTooltip, WRITE, setTooltip, PROTECTED, NOTIFY, _setTooltipPropertyChangedFn);

    /**
     * @brief Set dynamic tooltip that will be created dynamiclly the first time it is needed.
     * the function is called inside a ui.Frame scope that the widget will be parented correctly.
     */
    OMNIUI_CALLBACK(Tooltip, void);

    /**
     * @brief Get Payload Id for drag and drop.
     */
    static constexpr const char* const getDragDropPayloadId()
    {
        return "OMNIUI_DRAG_AND_DROP";
    }

    /**
     * @brief Set the X tooltip offset in points. In a normal state, the tooltip position is linked to the mouse
     * position. If the tooltip offset is non zero, the top left corner of the tooltip is linked to the top left corner
     * of the widget, and this property defines the relative position the tooltip should be shown.
     */
    OMNIUI_PROPERTY(float,
                    tooltipOffsetX,
                    DEFAULT,
                    0.0f,
                    READ,
                    getTooltipOffsetX,
                    WRITE,
                    setTooltipOffsetX,
                    NOTIFY,
                    setTooltipOffsetXChangedFn);

    /**
     * @brief Set the Y tooltip offset in points. In a normal state, the tooltip position is linked to the mouse
     * position. If the tooltip offset is non zero, the top left corner of the tooltip is linked to the top left corner
     * of the widget, and this property defines the relative position the tooltip should be shown.
     */
    OMNIUI_PROPERTY(float,
                    tooltipOffsetY,
                    DEFAULT,
                    0.0f,
                    READ,
                    getTooltipOffsetY,
                    WRITE,
                    setTooltipOffsetY,
                    NOTIFY,
                    setTooltipOffsetYChangedFn);

    /**
     * @brief The flag that specifies if it's necessary to bypass the whole draw cycle if the bounding box is clipped
     * with a scrolling frame. It's needed to avoid the limitation of 65535 primitives in a single draw list.
     */
    OMNIUI_PROPERTY(bool, skipDrawWhenClipped, DEFAULT, false, READ, isSkipDrawWhenClipped, WRITE, setSkipDrawWhenClipped);

    /**
     * The scale factor of the widget.
     *
     * The purpose of this property is to cache the scale factor of the CanvasFarame that uniformly scales its children.
     */
    OMNIUI_PROPERTY(float, scale, DEFAULT, 1.0f, WRITE, setScale, PROTECTED, READ, _getScale, NOTIFY, _setScaleChangedFn);

    /**
     * @brief Zoom level of the parent CanvasFrame
     */
    OMNIUI_PROPERTY(float,
                    canvasZoom,
                    DEFAULT,
                    -1.0f,
                    WRITE,
                    setCanvasZoom,
                    PROTECTED,
                    READ,
                    _getCanvasZoom,
                    NOTIFY,
                    _setCanvasZoomChangedFn);

    /**
     * @brief An optional identifier of the widget we can use to refer to it in queries.
     */
    OMNIUI_PROPERTY(std::string, identifier, NOTIFY, setIdentifierChangedFn);

    OMNIUI_API virtual std::string getIdentifier();
    OMNIUI_API virtual void setIdentifier(const std::string& identifer);

    /**
     * @brief When it's false, the scroll callback is called even if other window is hovered.
     */
    OMNIUI_PROPERTY(bool, scrollOnlyWindowHovered, DEFAULT, false, READ, isScrollOnlyWindowHovered, WRITE, setScrollOnlyWindowHovered);


protected:
    friend class DockSpace;
    friend class FontHelper;
    friend class Frame;
    friend class Inspector;
    friend class MainWindow;
    friend class Menu;
    friend class MenuHelper;
    friend class Placer;
    friend class RasterHelper;
    friend class ScrollingFrame;
    friend class Shape;
    friend class Stack;
    friend class TreeView;
    friend class Window;
    struct WidgetData;

    OMNIUI_API
    Widget(WidgetData* = nullptr);

    /**
     * @brief The rendering code of the widget. Should be implemented by derived classes.
     *
     * The difference with draw() is that the _drawContent() method should contain the code to draw the current widget.
     * draw() includes the code that is common for all the widgets, like mouse input, checking visibility, etc.
     *
     * @param elapsedTime The time elapsed (in seconds)
     */
    OMNIUI_API
    virtual void _drawContent(float elapsedTime){}

    /**
     * @brief It returns the style that is result of merging the styles of all the parents and the local style.
     */
    OMNIUI_API
    const std::shared_ptr<StyleContainer>& _getResolvedStyle() const;

    /**
     * @brief Get the Type Name used to query the style. It can be either overrided type name or the widget type. We
     * need to override type name when the widget has constructed with multiple widgets. For example Button is
     * constructed with rectangle and label.
     */
    OMNIUI_API
    const std::string& _getStyleTypeName() const;

    /**
     * @brief Resolves the style property with the style object. It checks override, parent, and cascade styles.
     *
     * @tparam T StyleFloatProperty or StyleColorProperty
     * @tparam U float or uint32_t
     * @param property For example StyleFloatProperty::ePadding
     * @param result the pointer to the result where the resolved property will be written
     * @return true when the style contains given property
     * @return false when the style doesn't have the given property
     */
    template <typename T, typename U>
    OMNIUI_API bool _resolveStyleProperty(T property, U* result) const;

    /**
     * @brief Resolves the style property with the given state.
     */
    template <typename T, typename U>
    OMNIUI_API bool _resolveStyleProperty(T property, StyleContainer::State state, U* result) const;

    /**
     * @brief Returns the current state for the styling.
     */
    OMNIUI_API StyleContainer::State _getStyleState() const;

    /**
     * @brief Enable custom glyph char. Default is disabled - all glyph chars rendered with ImGuiCol_Text. Enable to
     * make all glyph chars be rendered with ImGuiCol_CustomChar (default 0xFFFFFFFF). Recommend to enable before
     * rendering the glyph chars with color defined in svg, and disable when rendering done to make sure others be
     * rendered as expected.
     */
    OMNIUI_API void _enableCustomChar(bool enable) const;

    /**
     * @brief Check if current widget or its parent has accepted drop.
     */
    OMNIUI_API bool _hasAcceptedDrop() const;

    /**
     * m_dirtyWidth = false;
     * m_dirtyHeight = false;
     */
    OMNIUI_API void _undirtyWidthAndHeight(bool force = false);

    /**
     * @brief This function returns a boolean value indicating whether the
     * parent of the widget is a CanvasFrame. CanvasFrame has the capability to
     * scale its child widgets. This information is useful for certain widgets
     * to determine if they should be rendered in a scalable environment.
     *
     * @return bool - true if the parent or any of its ancestors is a
     * CanvasFrame, false otherwise.
     */
    OMNIUI_API virtual bool _isParentCanvasFrame() const;

    /**
     * @brief This method fills an unordered set with the visible minimum and
     * maximum values of the Widget and children.
     */
    OMNIUI_API virtual void _fillVisibleThreshold(void* thresholds) const;

    /**
     * @brief Return current visibleMin/visibleMax LOD id.
     */
    OMNIUI_API virtual size_t _getCurrentLod(float zoom) const;

    /**
     * @brief Return widget bounding box for use with mouse events. Defaults to
     * [0,0]-[computedContentWidth,computedContentHeight]. Used by FreeShapes
     * which otherwise set size to zero for layout and have a local offset for drawing.
     */
    OMNIUI_API virtual BoundingBox _getInteractionBBox() const;

    OMNIUI_API bool isWindowHovered() const;
    OMNIUI_API bool isHovered() const;
    OMNIUI_API bool setHovered(bool hovered);
    OMNIUI_API bool isPressed(uint32_t button) const;
    OMNIUI_API bool isClicked(uint32_t button) const;
    OMNIUI_API bool useMarginFromStyle() const;
    OMNIUI_API SizeDirtyReason isWidthDirty() const;
    OMNIUI_API SizeDirtyReason isHeightDirty() const;

    template <typename T> inline T& _getData() const {
        return static_cast<T&>(*m_data);
    }

private:
    /**
     * @brief Creates m_resolvedStyle, which is the parents style plus the local style. If there is no local style,
     * m_resolvedStyle is empty.
     */
    void _mergeStyleWithParent();

    /**
     * @brief called when the tooltip is needed for the first time, this will create the right widgets in the frame
     */
    void _createToolTipWidgets();

    /**
     * @brief Called every frame when there is dragFn to setup drag area.
     */
    void _performDrag();

    /**
     * @brief Called when there are dropFn and acceptDropFn and mouse enters the widget to check if widget accepts
     * current drag.
     */
    void _performAcceptDrop();

    /**
     * @brief Called when the user makes drop to call dropFn.
     */
    void _performDrop(float x, float y);

    std::unique_ptr<WidgetData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
