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

// Standalone variant: carb/scripting/IPythonThreading.h removed;
// carb::scripting::ReleasePythonGil replaced with pybind11::gil_scoped_release.
//
#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/PolygonMesh.h>
#include <omni/ui/scene/TexturedMesh.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindTexturedMesh.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapTexturedMesh(module& m)
{
    constexpr const char* texturedMeshDoc = OMNIUI_PYBIND_CLASS_DOC(TexturedMesh);
    static constexpr char texturedMeshConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(TexturedMesh, TexturedMesh);
    static constexpr char texturedMeshConstructor1Doc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(TexturedMesh, TexturedMesh01);

    class_<TexturedMesh::TexturedMeshGesturePayload, PolygonMesh::PolygonMeshGesturePayload,
           std::shared_ptr<TexturedMesh::TexturedMeshGesturePayload>>(m, "TexturedMeshGesturePayload")
        .def_property_readonly("u", [](const TexturedMesh::TexturedMeshGesturePayload& self) { return self.u; })
        .def_property_readonly("v", [](const TexturedMesh::TexturedMeshGesturePayload& self) { return self.v; })
        /* */;

    struct TexturedMeshDestructor
    {
        void operator()(TexturedMesh* texturedMesh)
        {
            // TexturedMesh destructor will wait on asset loading, which requires the GIL, so make sure the GIL is not
            // locked when we destroy images.
            //
            // Destructor can be called from both C++ and Python code paths. Only release the GIL if the current
            // thread actually holds it — pybind11's gil_scoped_release calls PyEval_SaveThread unconditionally,
            // which aborts with a Python fatal error when the GIL is not held (seen during scene draw callbacks
            // invoked from Kit's main thread without the GIL).
            if (PyGILState_Check())
            {
                pybind11::gil_scoped_release nogil;
                delete texturedMesh;
            }
            else
            {
                delete texturedMesh;
            }
        }
    };

    class_<TexturedMesh, PolygonMesh, std::shared_ptr<TexturedMesh>>(m, "TexturedMesh", texturedMeshDoc)
        .def(init([](const std::string& sourceUrl, object pyUvs, object pyPos, object pyCol, const std::vector<uint32_t>& vertexCounts,
                     const std::vector<uint32_t>& vertexIndices, bool legacyFLippedV, kwargs kwargs) {
                     auto uvs = pythonListToVector2(pyUvs);
                     auto pos = pythonListToVector3(pyPos);
                     auto color = pythonListToVector4(pyCol);
                     OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(TexturedMesh, TexturedMeshDestructor{}, sourceUrl, std::move(uvs),
                     std::move(pos), std::move(color), vertexCounts, vertexIndices, legacyFLippedV)
            }),
            arg("source_url"), arg("uvs"), arg("positions"), arg("colors"), arg("vertex_counts"),
            arg("vertex_indices"), arg("legacy_flipped_v") = true, texturedMeshConstructorDoc)
        .def(init([](const std::shared_ptr<ImageProvider>& imageProvider, object pyUvs, object pyPos, object pyCol,
                     const std::vector<uint32_t>& vertexCounts, const std::vector<uint32_t>& vertexIndices, bool legacyFLippedV, kwargs kwargs) {
                     auto uvs = pythonListToVector2(pyUvs);
                     auto pos = pythonListToVector3(pyPos);
                     auto color = pythonListToVector4(pyCol);
                     OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(TexturedMesh, TexturedMeshDestructor{}, imageProvider, std::move(uvs),
                     std::move(pos), std::move(color), vertexCounts, vertexIndices, legacyFLippedV)
             }),
             arg("image_provider"), arg("uvs"), arg("positions"), arg("colors"), arg("vertex_counts"),
             arg("vertex_indices"), arg("legacy_flipped_v") = true, texturedMeshConstructor1Doc)
        .def_property("uvs", [](const TexturedMesh& self) { return vector2ToPythonList(self.getUvs()); },
                      [](TexturedMesh& self, const pybind11::handle& obj) { self.setUvs(pythonListToVector2(obj)); },
                      OMNIUI_PYBIND_DOC_TexturedMesh_uvs)
        .def_property("source_url", &TexturedMesh::getSourceUrl, &TexturedMesh::setSourceUrl, OMNIUI_PYBIND_DOC_TexturedMesh_sourceUrl)
        .def_property(
            "image_provider", &TexturedMesh::getImageProvider, &TexturedMesh::setImageProvider, OMNIUI_PYBIND_DOC_TexturedMesh_imageProvider)
        .def_property("image_width", &TexturedMesh::getImageWidth, &TexturedMesh::setImageWidth,
                      OMNIUI_PYBIND_DOC_ImageHelper_imageWidth)
        .def_property("image_height", &TexturedMesh::getImageHeight, &TexturedMesh::setImageHeight,
                      OMNIUI_PYBIND_DOC_ImageHelper_imageHeight)
        .def_property_readonly("gesture_payload", [](const TexturedMesh& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_TexturedMesh_getGesturePayload)
        .def("get_gesture_payload", [](const TexturedMesh& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_TexturedMesh_getGesturePayload)
        .def("get_gesture_payload",
             [](const TexturedMesh& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_TexturedMesh_getGesturePayload01)
        /* */;
}
