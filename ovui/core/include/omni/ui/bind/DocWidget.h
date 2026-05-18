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

#pragma once

#define OMNIUI_PYBIND_DOC_Widget                                                                                       \
    "The Widget class is the base class of all user interface objects.\n"                                              \
    "The widget is the atom of the user interface: it receives mouse, keyboard and other events, and paints a representation of itself on the screen. Every widget is rectangular. A widget is clipped by its parent and by the widgets in front of it.\n"


#define OMNIUI_PYBIND_DOC_Widget_kModifierFlagWantCaptureKeyboard                                                      \
    "When WantCaptureKeyboard, omni.ui is using the keyboard input exclusively, e.g. InputText active, etc.\n"


#define OMNIUI_PYBIND_DOC_Widget_destroy "Removes all the callbacks and circular references.\n"


#define OMNIUI_PYBIND_DOC_Widget_draw                                                                                                                                                                                                                                  \
    "Execute the rendering code of the widget, that includes the work with inputs and run _drawContent() that can be implemented by derived clrasses.\n"                                                                                                               \
    "It's in the public section because it's not possible to put it to the protected section. If it's in the protected, then other widgets that have child widgets will not be able to call it.\n"                                                                     \
    "Example:\n"                                                                                                                                                                                                                                                       \
    "class Widget { protected: virtual void draw() { } };\n"                                                                                                                                                                                                           \
    "class Frame : public Widget { protected: void draw() override { // error C2248: 'Widget::draw': cannot access protected member declared in class 'Widget' m_child.draw(); }\n"                                                                                    \
    "private: Widget m_child; };\n"                                                                                                                                                                                                                                    \
    "Also, it's not possible to use friendship because friendship is neither inherited nor transitive. It means it's necessary to list all the classes that can use sub-objects explicitly. And in this way, custom extensions will not be able to use sub-objects.\n" \
    "\n"                                                                                                                                                                                                                                                               \
    "\n"                                                                                                                                                                                                                                                               \
    "### Arguments:\n"                                                                                                                                                                                                                                                 \
    "\n"                                                                                                                                                                                                                                                               \
    "    `elapsedTime :`\n"                                                                                                                                                                                                                                            \
    "        The time elapsed (in seconds)\n"


#define OMNIUI_PYBIND_DOC_Widget_getComputedWidth                                                                      \
    "Returns the final computed width of the widget. It includes margins.\n"                                           \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_getComputedContentWidth                                                               \
    "Returns the final computed width of the content of the widget.\n"                                                 \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_setComputedWidth                                                                      \
    "Sets the computed width. It subtract margins and calls setComputedContentWidth.\n"                                \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_setComputedContentWidth                                                                                                                                                                                                 \
    "The widget provides several functions that deal with a widget's geometry. Indicates the content width hint that represents the preferred size of the widget. The widget is free to readjust its geometry to fit the content when it's necessary.\n" \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_getComputedHeight                                                                     \
    "Returns the final computed height of the widget. It includes margins.\n"                                          \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_getComputedContentHeight                                                              \
    "Returns the final computed height of the content of the widget.\n"                                                \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_setComputedHeight                                                                     \
    "Sets the computed height. It subtract margins and calls setComputedContentHeight.\n"                              \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_setComputedContentHeight                                                                                                                                                                                                 \
    "The widget provides several functions that deal with a widget's geometry. Indicates the content height hint that represents the preferred size of the widget. The widget is free to readjust its geometry to fit the content when it's necessary.\n" \
    "It's in puplic section. For the explanation why please see the draw() method.\n"


#define OMNIUI_PYBIND_DOC_Widget_getScreenPositionX                                                                    \
    "Returns the X Screen coordinate the widget was last draw. This is in Screen Pixel size.\n"                         \
    "It's a float because we need negative numbers and precise position considering DPI scale factor.\n"


#define OMNIUI_PYBIND_DOC_Widget_getScreenPositionY                                                                    \
    "Returns the Y Screen coordinate the widget was last draw. This is in Screen Pixel size.\n"                         \
    "It's a float because we need negative numbers and precise position considering DPI scale factor.\n"


#define OMNIUI_PYBIND_DOC_Widget_MouseMoved                                                                            \
    "Sets the function that will be called when the user moves the mouse inside the widget. Mouse move events only occur if a mouse button is pressed while the mouse is being moved. void onMouseMoved(float x, float y, int32_t modifier)\n"


#define OMNIUI_PYBIND_DOC_Widget_MousePressed                                                                          \
    "Sets the function that will be called when the user presses the mouse button inside the widget. The function should be like this: void onMousePressed(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier) Where 'button' is the number of the mouse button pressed. 'modifier' is the flag for the keyboard modifier key.\n"


#define OMNIUI_PYBIND_DOC_Widget_MouseReleased                                                                         \
    "Sets the function that will be called when the user releases the mouse button if this button was pressed inside the widget. void onMouseReleased(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_Widget_MouseDoubleClicked                                                                    \
    "Sets the function that will be called when the user presses the mouse button twice inside the widget. The function specification is the same as in setMousePressedFn. void onMouseDoubleClicked(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_Widget_MouseWheel                                                                            \
    "Sets the function that will be called when the user uses mouse wheel on the focused window. The function specification is the same as in setMousePressedFn. void onMouseWheel(float x, float y, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_Widget_MouseHovered                                                                          \
    "Sets the function that will be called when the user use mouse enter/leave on the focused window. function specification is the same as in setMouseHovedFn. void onMouseHovered(bool hovered)\n"


#define OMNIUI_PYBIND_DOC_Widget_KeyPressed                                                                            \
    "Sets the function that will be called when the user presses the keyboard key when the mouse clicks the widget.\n"


#define OMNIUI_PYBIND_DOC_Widget_Drag                                                                                  \
    "Specify that this Widget is draggable, and set the callback that is attached to the drag operation.\n"


#define OMNIUI_PYBIND_DOC_Widget_AcceptDrop                                                                            \
    "Specify that this Widget can accept specific drops and set the callback that is called to check if the drop can be accepted.\n"


#define OMNIUI_PYBIND_DOC_Widget_Drop                                                                                  \
    "Specify that this Widget accepts drops and set the callback to the drop operation.\n"


#define OMNIUI_PYBIND_DOC_Widget_ComputedContentSizeChanged "Called when the size of the widget is changed.\n"


#define OMNIUI_PYBIND_DOC_Widget_opaqueForMouseEvents                                                                  \
    "If the widgets has callback functions it will by default not capture the events if it is the top most widget and setup this option to true, so they don't get routed to the child widgets either\n"

#define OMNIUI_PYBIND_DOC_Widget_explicitHover                                                                  \
    "If the widgets has callback functions it will by default not capture the events if it is the top most widget and setup this option to true, so they don't get routed to the child widgets either\n"

#define OMNIUI_PYBIND_DOC_Widget_setStyle                                                                              \
    "Set the current style. The style contains a description of customizations to the widget's style.\n"


#define OMNIUI_PYBIND_DOC_Widget_updateStyle                                                                           \
    "Recompute internal cached data that is used for styling. Unlike cascadeStyle, updateStyle is called when the name or type of the widget is changed.\n"


#define OMNIUI_PYBIND_DOC_Widget_cascadeStyle                                                                          \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Widget_onStyleUpdated                                                                        \
    "Called when the style is changed. The child classes can use it to propagate the style to children.\n"


#define OMNIUI_PYBIND_DOC_Widget_useMarginFromStyle                                                                    \
    "The ability to skip margins. It's useful when the widget is a part of compound widget and should be of exactly provided size. Like Rectangle of the Button.\n"


#define OMNIUI_PYBIND_DOC_Widget_scrollHereX                                                                           \
    "Adjust scrolling amount to make current item visible.\n"                                                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `centerRatio :`\n"                                                                                            \
    "        0.0: left, 0.5: center, 1.0: right\n"


#define OMNIUI_PYBIND_DOC_Widget_scrollHereY                                                                           \
    "Adjust scrolling amount to make current item visible.\n"                                                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `centerRatio :`\n"                                                                                            \
    "        0.0: top, 0.5: center, 1.0: bottom\n"


#define OMNIUI_PYBIND_DOC_Widget_scrollHere                                                                            \
    "Adjust scrolling amount in two axes to make current item visible.\n"                                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `centerRatioX :`\n"                                                                                           \
    "        0.0: left, 0.5: center, 1.0: right\n"                                                                     \
    "\n"                                                                                                               \
    "    `centerRatioY :`\n"                                                                                           \
    "        0.0: top, 0.5: center, 1.0: bottom\n"


#define OMNIUI_PYBIND_DOC_Widget_getDpiScale "Return the application DPI factor multiplied by the widget scale.\n"


#define OMNIUI_PYBIND_DOC_Widget_forceWidthDirty "Next frame content width will be forced to recompute.\n"


#define OMNIUI_PYBIND_DOC_Widget_forceHeightDirty "Next frame content height will be forced to recompute.\n"


#define OMNIUI_PYBIND_DOC_Widget_setVisiblePreviousFrame                                                               \
    "Change dirty bits when the visibility is changed. It's public because other widgets have to call it.\n"           \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `visible :`\n"                                                                                                \
    "        True when the widget is colmpletley rendered. False when early exit.\n"                                   \
    "\n"                                                                                                               \
    "    `dirtySize :`\n"                                                                                              \
    "        True to set the size diry bits.\n"


#define OMNIUI_PYBIND_DOC_Widget_visible "This property holds whether the widget is visible.\n"


#define OMNIUI_PYBIND_DOC_Widget_visibleMin                                                                            \
    "If the current zoom factor and DPI is less than this value, the widget is not visible.\n"


#define OMNIUI_PYBIND_DOC_Widget_visibleMax                                                                            \
    "If the current zoom factor and DPI is bigger than this value, the widget is not visible.\n"


#define OMNIUI_PYBIND_DOC_Widget_enabled                                                                               \
    "This property holds whether the widget is enabled. In general an enabled widget handles keyboard and mouse events; a disabled widget does not. And widgets display themselves differently when they are disabled.\n"


#define OMNIUI_PYBIND_DOC_Widget_selected                                                                              \
    "This property holds a flag that specifies the widget has to use eSelected state of the style.\n"


#define OMNIUI_PYBIND_DOC_Widget_checked                                                                               \
    "This property holds a flag that specifies the widget has to use eChecked state of the style. It's on the Widget level because the button can have sub-widgets that are also should be checked.\n"


#define OMNIUI_PYBIND_DOC_Widget_width                                                                                 \
    "This property holds the width of the widget relative to its parent. Do not use this function to find the width of a screen.\n"


#define OMNIUI_PYBIND_DOC_Widget_height                                                                                \
    "This property holds the height of the widget relative to its parent. Do not use this function to find the height of a screen.\n"


#define OMNIUI_PYBIND_DOC_Widget_dragging "This property holds if the widget is being dragged.\n"


#define OMNIUI_PYBIND_DOC_Widget_name "The name of the widget that user can set.\n"


#define OMNIUI_PYBIND_DOC_Widget_styleTypeNameOverride                                                                 \
    "By default, we use typeName to look up the style. But sometimes it's necessary to use a custom name. For example, when a widget is a part of another widget. (Label is a part of Button) This property can override the name to use in style.\n"


#define OMNIUI_PYBIND_DOC_Widget_parent                                                                                \
    "Protected weak pointer to the parent object. We need it to query the parent style. Parent can be a Container or another widget if it holds sub-widgets.\n"


#define OMNIUI_PYBIND_DOC_Widget_style                                                                                 \
    "The local style. When the user calls\n"                                                                           \
    "setStyle()\n"


#define OMNIUI_PYBIND_DOC_Widget_tooltip                                                                               \
    "Set a basic tooltip for the widget, this will simply be a Label, it will follow the Tooltip style\n"


#define OMNIUI_PYBIND_DOC_Widget_Tooltip                                                                               \
    "Set dynamic tooltip that will be created dynamiclly the first time it is needed. the function is called inside a ui.Frame scope that the widget will be parented correctly.\n"


#define OMNIUI_PYBIND_DOC_Widget_tooltipOffsetX                                                                        \
    "Set the X tooltip offset in points. In a normal state, the tooltip position is linked to the mouse position. If the tooltip offset is non zero, the top left corner of the tooltip is linked to the top left corner of the widget, and this property defines the relative position the tooltip should be shown.\n"


#define OMNIUI_PYBIND_DOC_Widget_tooltipOffsetY                                                                        \
    "Set the Y tooltip offset in points. In a normal state, the tooltip position is linked to the mouse position. If the tooltip offset is non zero, the top left corner of the tooltip is linked to the top left corner of the widget, and this property defines the relative position the tooltip should be shown.\n"


#define OMNIUI_PYBIND_DOC_Widget_skipDrawWhenClipped                                                                   \
    "The flag that specifies if it's necessary to bypass the whole draw cycle if the bounding box is clipped with a scrolling frame. It's needed to avoid the limitation of 65535 primitives in a single draw list.\n"


#define OMNIUI_PYBIND_DOC_Widget_scale                                                                                 \
    "The scale factor of the widget.\n"                                                                                \
    "The purpose of this property is to cache the scale factor of the CanvasFarame that uniformly scales its children.\n"


#define OMNIUI_PYBIND_DOC_Widget_identifier                                                                            \
    "An optional identifier of the widget we can use to refer to it in queries.\n"


#define OMNIUI_PYBIND_DOC_Widget_getDragDropPayloadId "Get Payload Id for drag and drop.\n"


#define OMNIUI_PYBIND_DOC_Widget_scrollOnlyWindowHovered                                                                     \
    "When it's false, the scroll callback is called even if other window is hovered.\n"
