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
#include <omni/ui/scene/PolygonMesh.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindPolygonMesh.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapPolygonMesh(module& m)
{
    constexpr const char* polygonMeshDoc = OMNIUI_PYBIND_CLASS_DOC(PolygonMesh);
    static constexpr char polygonMeshConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(PolygonMesh, PolygonMesh);

    class_<PolygonMesh::PolygonMeshGesturePayload, AbstractGesture::GesturePayload,
           std::shared_ptr<PolygonMesh::PolygonMeshGesturePayload>>(m, "PolygonMeshGesturePayload")
        .def_property_readonly("face_id", [](const PolygonMesh::PolygonMeshGesturePayload& self)
                               { return self.faceId; })
        .def_property_readonly("s", [](const PolygonMesh::PolygonMeshGesturePayload& self) { return self.s; })
        .def_property_readonly("t", [](const PolygonMesh::PolygonMeshGesturePayload& self) { return self.t; })
        /* */;

    class_<PolygonMesh, AbstractShape, std::shared_ptr<PolygonMesh>>(m, "PolygonMesh", polygonMeshDoc)
        .def(init(
            [](object positions, object colors, const std::vector<uint32_t>& vertexCounts,
                const std::vector<uint32_t>& vertexIndices, kwargs kwargs)
            {
                auto pos = pythonListToVector3(positions);
                auto col = pythonListToVector4(colors);
                OMNIUI_PYBIND_INIT(PolygonMesh, std::move(pos), std::move(col), vertexCounts, vertexIndices)
            }), arg("positions"), arg("colors"), arg("vertex_counts"), arg("vertex_indices"), polygonMeshConstructorDoc)
        .def_property("positions", [](const PolygonMesh& self) { return vector3ToPythonList(self.getPositions()); },
                      [](PolygonMesh& self, const pybind11::handle& obj) { self.setPositions(pythonListToVector3(obj)); },
                      OMNIUI_PYBIND_DOC_PolygonMesh_positions)
        .def_property("colors", [](const PolygonMesh& self) { return vector4ToPythonList(self.getColors()); },
                      [](PolygonMesh& self, const pybind11::handle& obj) { self.setColors(pythonListToVector4(obj)); },
                      OMNIUI_PYBIND_DOC_PolygonMesh_colors)
        .def_property("vertex_counts", &PolygonMesh::getVertexCounts, &PolygonMesh::setVertexCounts,
                      OMNIUI_PYBIND_DOC_PolygonMesh_vertexCounts)
        .def_property("vertex_indices", &PolygonMesh::getVertexIndices, &PolygonMesh::setVertexIndices,
                      OMNIUI_PYBIND_DOC_PolygonMesh_vertexIndices)
        .def_property("thicknesses", &PolygonMesh::getThicknesses, &PolygonMesh::setThicknesses,
                      OMNIUI_PYBIND_DOC_PolygonMesh_thicknesses)
        .def_property("intersection_thicknesses", &PolygonMesh::getIntersectionThickness, &PolygonMesh::setIntersectionThickness, OMNIUI_PYBIND_DOC_PolygonMesh_intersectionThickness)
        .def_property(
            "wireframe", &PolygonMesh::isWireframe, &PolygonMesh::setWireframe, OMNIUI_PYBIND_DOC_PolygonMesh_wireframe)
        .def_property_readonly("gesture_payload", [](const PolygonMesh& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_PolygonMesh_getGesturePayload)
        .def("get_gesture_payload", [](const PolygonMesh& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_PolygonMesh_getGesturePayload)
        .def("get_gesture_payload",
             [](const PolygonMesh& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_PolygonMesh_getGesturePayload01);
}
