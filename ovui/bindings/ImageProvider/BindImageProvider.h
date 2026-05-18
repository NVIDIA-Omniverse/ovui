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

#include <omni/ui/ImageProvider/ImageProvider.h>

#include <pybind11/pybind11.h>

#include <cstdint>
#include <memory>

// Minimal complete type so pybind11 can generate typeid for RpResource parameters.
// The real RpResource definition is opaque; we only pass it by reference.
namespace rtx
{
namespace resourcemanager
{
class RpResource
{
};
}
}

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapImageProvider(module& m)
{
    class_<ImageProvider, std::shared_ptr<ImageProvider>>(
        m, "ImageProvider",
        "ImageProvider class, the goal of this class is to provide ImGui reference for the image to be rendered.")
        .def(init([](kwargs kwargs) {
            pybind11::gil_scoped_release gil;
            return ImageProvider::create<ImageProvider>();
        }), "doc")
        .def_property_readonly("is_reference_valid", &ImageProvider::isReferenceValid,
                               "Returns true if ImGui reference is valid, false otherwise.")
        .def_property_readonly("width", &ImageProvider::getWidth, "Gets image width.")
        .def_property_readonly("height", &ImageProvider::getHeight, "Gets image height.")
        .def("set_image_data",
             [](ImageProvider* self, void* texReference, uint32_t width, uint32_t height, PixelFormat format) {
                 self->setImageData(texReference, { width, height }, format);
             })
        .def("set_image_data",
             [](ImageProvider* self, rtx::resourcemanager::RpResource& rpRsrc, int64_t presentationKey, void* metadata) {
                 self->setImageData(rpRsrc, static_cast<uint64_t>(presentationKey));
             }, arg("rp_resource"), arg("presentation_key") = 0, arg("metadata") = nullptr)
        .def("destroy",
             [](ImageProvider* self) {
                 self->setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
             })
        .def("get_managed_resource",
             [](ImageProvider* self) -> void* { return static_cast<void*>(self->getManagedResource()); },
             return_value_policy::reference)
        /**/;
}
