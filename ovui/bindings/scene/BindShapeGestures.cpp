/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include <omni/ui/scene/AbstractGesture.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/ClickGesture.h>
#include <omni/ui/scene/DoubleClickGesture.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/HoverGesture.h>
#include <omni/ui/scene/ScrollGesture.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindScrollGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindGestureManager.h>
#include <omni/ui/scene/bind/BindHoverGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <pybind11/chrono.h>
#include <pybind11/stl.h>

using namespace pybind11;
using namespace omni::ui;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class PyClickGesture : public ClickGesture
{
public:
    static std::shared_ptr<PyClickGesture> create(std::function<void(AbstractShape const*)> onEnded)
    {
        return std::make_shared<PyClickGesture>(std::move(onEnded));
    }

    void onEnded() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, ClickGesture, onEnded, on_ended);
    }

    PyClickGesture(std::function<void(AbstractShape const*)> onEnded) : ClickGesture{ std::move(onEnded) }
    {
    }
};

class PyDoubleClickGesture : public DoubleClickGesture
{
public:
    static std::shared_ptr<PyDoubleClickGesture> create(std::function<void(AbstractShape const*)> onEnded)
    {
        return std::make_shared<PyDoubleClickGesture>(std::move(onEnded));
    }

    void onEnded() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, DoubleClickGesture, onEnded, on_ended);
    }

    PyDoubleClickGesture(std::function<void(AbstractShape const*)> onEnded) : DoubleClickGesture{ std::move(onEnded) }
    {
    }
};

class PyDragGesture : public DragGesture
{
public:
    static std::shared_ptr<PyDragGesture> create()
    {
        return std::make_shared<PyDragGesture>();
    }

    void process() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, DragGesture, process, process);
    }

    void onBegan() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, DragGesture, onBegan, on_began);
    }

    void onChanged() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, DragGesture, onChanged, on_changed);
    }

    void onEnded() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, DragGesture, onEnded, on_ended);
    }
};

class PyHoverGesture : public HoverGesture
{
public:
    static std::shared_ptr<PyHoverGesture> create()
    {
        return std::make_shared<PyHoverGesture>();
    }

    void process() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, HoverGesture, process, process);
    }

    void onBegan() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, HoverGesture, onBegan, on_began);
    }

    void onChanged() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, HoverGesture, onChanged, on_changed);
    }

    void onEnded() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, HoverGesture, onEnded, on_ended);
    }
};

class PyScrollGesture : public ScrollGesture
{
public:
    static std::shared_ptr<PyScrollGesture> create(std::function<void(AbstractShape const*)> onEnded)
    {
        return std::make_shared<PyScrollGesture>(std::move(onEnded));
    }

    void onEnded() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, ScrollGesture, onEnded, on_ended);
    }

    PyScrollGesture(std::function<void(AbstractShape const*)> onEnded) : ScrollGesture{ std::move(onEnded) }
    {
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

#define OMNIUI_PYBIND_DOC_Gesture_preProcess "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_Gesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_onEnded                                                                         \
    "Called if the callback is not set when the user releases the mouse button.\n"


#define OMNIUI_PYBIND_DOC_Gesture_mouseButton "The mouse button this gesture is watching.\n"

#define OMNIUI_PYBIND_DOC_Gesture_mouseButtons "The mouse buttons this gesture is watching.\n"

#define OMNIUI_PYBIND_DOC_Gesture_modifiers "The modifier that should be pressed to trigger this gesture.\n"


#define OMNIUI_PYBIND_DOC_Gesture_OnEnded "Called when the user releases the button.\n"

void wrapShapeGesture(module& m)
{
    constexpr const char* shapeGestureDoc = OMNIUI_PYBIND_CLASS_DOC(ShapeGesture);

    class_<ShapeGesture, AbstractGesture, std::shared_ptr<ShapeGesture>> shapeGesture(m, "ShapeGesture", shapeGestureDoc);
    shapeGesture /* */
        .def("__repr__",
             [](const std::shared_ptr<ShapeGesture>& self) -> std::string { return "<ShapeGesture " + (self ? self->getName(): "") + ">"; })
        .def_property_readonly("sender", &ShapeGesture::getSender)
        .def_property_readonly("raw_input", &ShapeGesture::getRawInput)
        /* */;

    constexpr const char* clickGestureDoc = OMNIUI_PYBIND_CLASS_DOC(ClickGesture);
    static constexpr char clickGestureConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ClickGesture, ClickGesture);

    class_<ClickGesture, PyClickGesture, std::shared_ptr<ClickGesture>> clickGesture(
        m, "ClickGesture", shapeGesture, clickGestureDoc);
    clickGesture /* */
        .def(init(
                 [](std::function<void(AbstractShape const*)> onEnded, kwargs kwargs) -> std::shared_ptr<PyClickGesture> {
                     OMNIUI_PYBIND_INIT(PyClickGesture, onEnded ? wrapPythonCallback(std::move(onEnded)) : nullptr)
                 }),
             arg("_on_ended") = nullptr, clickGestureConstructorDoc)
        .def_property("mouse_button", &ClickGesture::getMouseButton, &ClickGesture::setMouseButton,
                      OMNIUI_PYBIND_DOC_ClickGesture_mouseButton)
        .def_property("mouse_buttons", &ClickGesture::getMouseButtons, &ClickGesture::setMouseButtons,
                      OMNIUI_PYBIND_DOC_ClickGesture_mouseButtons)
        .def_property("modifiers", &ClickGesture::getModifiers, &ClickGesture::setModifiers,
                      OMNIUI_PYBIND_DOC_ClickGesture_modifiers)
        .def("__repr__",
             [](const std::shared_ptr<ClickGesture>& self) -> std::string { return "<ClickGesture " + (self ? self->getName(): "") + ">"; })
        .OMNIUI_PYBIND_DEF_CALLBACK(on_ended, ClickGesture, OnEnded)
        /**/;

    constexpr const char* doubleClickGestureDoc = OMNIUI_PYBIND_CLASS_DOC(DoubleClickGesture);
    static constexpr char doubleClickGestureConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(DoubleClickGesture, DoubleClickGesture);

    class_<DoubleClickGesture, PyDoubleClickGesture, std::shared_ptr<DoubleClickGesture>>(
        m, "DoubleClickGesture", clickGesture, doubleClickGestureDoc)
        .def(init(
                 [](std::function<void(AbstractShape const*)> onEnded,
                    kwargs kwargs) -> std::shared_ptr<PyDoubleClickGesture> {
                     OMNIUI_PYBIND_INIT(PyDoubleClickGesture, onEnded ? wrapPythonCallback(std::move(onEnded)) : nullptr)
                 }),
             arg("_on_ended") = nullptr, doubleClickGestureConstructorDoc)
        .def("__repr__",
             [](const std::shared_ptr<DoubleClickGesture>& self) -> std::string { return "<DoubleClickGesture " + (self ? self->getName(): "") + ">"; })
        .OMNIUI_PYBIND_DEF_CALLBACK(on_ended, DoubleClickGesture, OnEnded)
        /**/;

    constexpr const char* dragGestureDoc = OMNIUI_PYBIND_CLASS_DOC(DragGesture);
    static constexpr char dragGestureConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(DragGesture, DragGesture);

    class_<DragGesture, PyDragGesture, std::shared_ptr<DragGesture>>(m, "DragGesture", shapeGesture, dragGestureDoc)
        .def(init([](kwargs kwargs) -> std::shared_ptr<PyDragGesture> { OMNIUI_PYBIND_INIT(PyDragGesture) }),
             dragGestureConstructorDoc)
        .def_property("mouse_button", &DragGesture::getMouseButton, &DragGesture::setMouseButton,
                      OMNIUI_PYBIND_DOC_DragGesture_mouseButton)
        .def_property("mouse_buttons", &DragGesture::getMouseButtons, &DragGesture::setMouseButtons,
                      OMNIUI_PYBIND_DOC_DragGesture_mouseButtons)
        .def_property("modifiers", &DragGesture::getModifiers, &DragGesture::setModifiers,
                      OMNIUI_PYBIND_DOC_Gesture_modifiers)
        .def_property("check_mouse_moved", &DragGesture::isCheckMouseMoved, &DragGesture::setCheckMouseMoved,
                      OMNIUI_PYBIND_DOC_DragGesture_checkMouseMoved)
        .def("__repr__",
             [](const std::shared_ptr<DragGesture>& self) -> std::string { return "<DragGesture " + (self ? self->getName(): "") + ">"; })
        .OMNIUI_PYBIND_DEF_CALLBACK(on_began, DragGesture, OnBegan)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_changed, DragGesture, OnChanged)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_ended, DragGesture, OnEnded)
        /**/;

    constexpr const char* hoverGestureDoc = OMNIUI_PYBIND_CLASS_DOC(HoverGesture);
    static constexpr char hoverGestureConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(HoverGesture, HoverGesture);

    class_<HoverGesture, PyHoverGesture, std::shared_ptr<HoverGesture>>(m, "HoverGesture", shapeGesture, hoverGestureDoc)
        .def(init([](kwargs kwargs) -> std::shared_ptr<PyHoverGesture> { OMNIUI_PYBIND_INIT(PyHoverGesture) }),
             hoverGestureConstructorDoc)
        .def_property("mouse_button", &HoverGesture::getMouseButton, &HoverGesture::setMouseButton,
                      OMNIUI_PYBIND_DOC_HoverGesture_mouseButton)
        .def_property("mouse_buttons", &HoverGesture::getMouseButtons, &HoverGesture::setMouseButtons,
                      OMNIUI_PYBIND_DOC_HoverGesture_mouseButtons)
        .def_property("modifiers", &HoverGesture::getModifiers, &HoverGesture::setModifiers,
                      OMNIUI_PYBIND_DOC_HoverGesture_modifiers)
        .def("__repr__",
             [](const std::shared_ptr<HoverGesture>& self) -> std::string { return "<HoverGesture " + (self ? self->getName(): "") + ">"; })
        .OMNIUI_PYBIND_DEF_CALLBACK(on_began, HoverGesture, OnBegan)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_changed, HoverGesture, OnChanged)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_ended, HoverGesture, OnEnded)
        /**/;

    constexpr const char* scrollGestureDoc = OMNIUI_PYBIND_CLASS_DOC(ScrollGesture);
    static constexpr char scrollGestureConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ScrollGesture, ScrollGesture);

    class_<ScrollGesture, PyScrollGesture, std::shared_ptr<ScrollGesture>>(
        m, "ScrollGesture", shapeGesture, scrollGestureDoc)
        .def(init([](std::function<void(AbstractShape const*)> onEnded, kwargs kwargs) -> std::shared_ptr<PyScrollGesture> {
                 OMNIUI_PYBIND_INIT(PyScrollGesture, onEnded ? wrapPythonCallback(std::move(onEnded)) : nullptr)
             }),
             arg("_on_ended") = nullptr, scrollGestureConstructorDoc)
        .def_property("mouse_button", &ScrollGesture::getMouseButton, &ScrollGesture::setMouseButton,
                      OMNIUI_PYBIND_DOC_ScrollGesture_mouseButton)
        .def_property("mouse_buttons", &ScrollGesture::getMouseButtons, &ScrollGesture::setMouseButtons,
                      OMNIUI_PYBIND_DOC_ScrollGesture_mouseButtons)
        .def_property("modifiers", &ScrollGesture::getModifiers, &ScrollGesture::setModifiers,
                      OMNIUI_PYBIND_DOC_ScrollGesture_modifiers)
        .def("__repr__",
             [](const std::shared_ptr<ScrollGesture>& self) -> std::string { return "<ScrollGesture " + (self ? self->getName(): "") + ">"; })
        .def_property_readonly(
            "scroll", [](const ScrollGesture& self) { return vector2ToPython(self.getScroll()); },
            OMNIUI_PYBIND_DOC_ScrollGesture_getScroll)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_ended, ScrollGesture, OnEnded)
        /**/;
}
