/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/Transform.h>
#include <omni/ui/scene/DepthGroup.h>
#include <omni/ui/scene/DistanceFadeGroup.h>
#include <omni/ui/scene/WidthSpaceGroup.h>
#include <omni/ui/scene/SelectionGroup.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindTransform.h>


using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

#define OMNIUI_PYBIND_INIT_DepthGroup OMNIUI_PYBIND_INIT_Transform
#define OMNIUI_PYBIND_INIT_DistanceFadeGroup OMNIUI_PYBIND_INIT_Transform
#define OMNIUI_PYBIND_INIT_WidthSpaceGroup OMNIUI_PYBIND_INIT_Transform
#define OMNIUI_PYBIND_INIT_SelectionGroup OMNIUI_PYBIND_INIT_Transform

void wrapTransform(module& m)
{
    constexpr const char* transformDoc = OMNIUI_PYBIND_CLASS_DOC(Transform);
    static constexpr char transformConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Transform, Transform);

    auto transform = class_<Transform, AbstractContainer, std::shared_ptr<Transform>>(m, "Transform", transformDoc);

    enum_<Transform::LookAt>(transform, "LookAt")
        .value("NONE", Transform::LookAt::eNone)
        .value("CAMERA", Transform::LookAt::eCamera)
        /**/;

    transform.def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Transform) }), transformConstructorDoc)
        .def(init([](object transform, kwargs kwargs) {
            const auto xform = pythonToMatrix4(transform);
            OMNIUI_PYBIND_INIT(Transform, xform)
        }), transformConstructorDoc)
        .def_property("transform", &Transform::getTransform,
                      [](Transform& self, const pybind11::handle& matrix) { self.setTransform(pythonToMatrix4(matrix)); },
                      OMNIUI_PYBIND_DOC_Transform_transform)
        .def_property("scale_to", &Transform::getScaleTo, &Transform::setScaleTo, OMNIUI_PYBIND_DOC_Transform_scaleTo)
        .def_property("look_at", &Transform::getLookAt, &Transform::setLookAt, OMNIUI_PYBIND_DOC_Transform_lookAt)
        .def_property("basis", &Transform::getBasis, &Transform::setBasis, OMNIUI_PYBIND_DOC_Transform_basis)
        /**/;

    class_<SelectionGroup, Transform, std::shared_ptr<SelectionGroup>>(m, "SelectionGroup",
        "Opaque descendant selection label; zero disables inherited selection. Does not install gestures.")
        .def(init([](uint64_t selection_id, kwargs kwargs) { OMNIUI_PYBIND_INIT(SelectionGroup, selection_id) }),
             arg("selection_id") = uint64_t(0))
        .def_property("selection_id", &SelectionGroup::getSelectionId, &SelectionGroup::setSelectionId);

    enum_<DepthPolicy>(m, "DepthPolicy")
        .value("INHERIT", DepthPolicy::eInherit)
        .value("DEFAULT", DepthPolicy::eDefault)
        .value("TEST_ONLY", DepthPolicy::eTestOnly)
        .value("TEST_AND_WRITE", DepthPolicy::eTestAndWrite)
        .value("OVERLAY", DepthPolicy::eOverlay);
    class_<DepthGroup, Transform, std::shared_ptr<DepthGroup>>(m, "DepthGroup",
        "Scoped depth policy for child shapes. Requires SceneView.supports_depth_groups.")
        .def(init([](DepthPolicy depth_policy, kwargs kwargs) { OMNIUI_PYBIND_INIT(DepthGroup, depth_policy) }),
             arg("depth_policy") = DepthPolicy::eInherit)
        .def_property("depth_policy", &DepthGroup::getDepthPolicy, &DepthGroup::setDepthPolicy);

    enum_<StrokeWidthSpace>(m, "StrokeWidthSpace")
        .value("PIXELS", StrokeWidthSpace::ePixels)
        .value("WORLD", StrokeWidthSpace::eWorld)
        .value("PIXEL_DIAMETER", StrokeWidthSpace::ePixelDiameter);
    class_<WidthSpaceGroup, Transform, std::shared_ptr<WidthSpaceGroup>>(m, "WidthSpaceGroup",
        "Scoped Curve/Line/Points width units. Requires supports_world_space_widths for WORLD and supports_pixel_diameter_widths for PIXEL_DIAMETER.")
        .def(init([](StrokeWidthSpace width_space, Float point_antialiasing_width, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(WidthSpaceGroup, width_space, point_antialiasing_width)
        }), arg("width_space") = StrokeWidthSpace::ePixels, arg("point_antialiasing_width") = 0.0)
        .def_property("width_space", &WidthSpaceGroup::getWidthSpace, &WidthSpaceGroup::setWidthSpace)
        .def_property("point_antialiasing_width", &WidthSpaceGroup::getPointAntialiasingWidth,
                      &WidthSpaceGroup::setPointAntialiasingWidth);

    class_<DistanceFade>(m, "DistanceFade", "Camera-distance opacity fade; zero normal selects world distance.")
        .def(init([](Float start, Float end, const Vector3& plane_normal, bool enabled) {
            return DistanceFade{enabled, start, end, plane_normal};
        }), arg("start") = 0.0, arg("end") = 1.0, arg("plane_normal") = Vector3(0.0), arg("enabled") = true)
        .def_readwrite("enabled", &DistanceFade::enabled)
        .def_readwrite("start", &DistanceFade::start)
        .def_readwrite("end", &DistanceFade::end)
        .def_readwrite("plane_normal", &DistanceFade::planeNormal);
    class_<DistanceFadeGroup, Transform, std::shared_ptr<DistanceFadeGroup>>(m, "DistanceFadeGroup",
        "Scoped world-space Gaussian opacity fade. Requires SceneView.supports_distance_fade.")
        .def(init([](const DistanceFade& fade, kwargs kwargs) { OMNIUI_PYBIND_INIT(DistanceFadeGroup, fade) }),
             arg("fade") = DistanceFade{})
        .def_property("fade", [](const DistanceFadeGroup& group) { return group.getDistanceFade(); },
                      &DistanceFadeGroup::setDistanceFade);
}
