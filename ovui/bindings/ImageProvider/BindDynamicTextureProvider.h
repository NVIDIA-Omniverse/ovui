/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>

#include <omni/ui/ImageProvider/DynamicTextureProvider.h>

#include <memory>
#include <string>

namespace py = pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapDynamicTextureProvider(py::module& m)
{
    py::class_<DynamicTextureProvider, ByteImageProvider, std::shared_ptr<DynamicTextureProvider>>(
        m, "DynamicTextureProvider",
        R"doc(Image provider backed by a named dynamic GPU texture resource.

``DynamicTextureProvider`` is a :class:`ByteImageProvider` that, in addition to
displaying its pixel data inside an :class:`ImageWithProvider` widget, publishes
the data to the renderer's resource manager under a stable dynamic texture URI
of the form ``dynamic://<texture_name>``. Materials, shaders, or any other
subsystem that references that URI will receive the latest pixels uploaded to
this provider, making it the canonical way to feed CPU- or GPU-generated images
into RTX materials at runtime.

Pixel data is supplied through the inherited
:meth:`ByteImageProvider.set_bytes_data`,
:meth:`ByteImageProvider.set_raw_bytes_data`, and
:meth:`ByteImageProvider.set_bytes_data_from_gpu` methods. Each upload replaces
the contents of the named texture and is broadcast to every GPU device by
default. Reusing the same ``texture_name`` from anywhere in the application
targets the same underlying texture resource.

Example::

    import omni.ui as ui

    # 2x2 RGBA8 checkerboard published as ``dynamic://my_texture``.
    pixels = [0, 0, 0, 255, 255, 0, 0, 255,
              0, 255, 0, 255, 0, 0, 255, 255]
    provider = ui.DynamicTextureProvider("my_texture")
    provider.set_bytes_data(pixels, [2, 2])

    with ui.Window("Dynamic Texture").frame:
        ui.ImageWithProvider(provider, fill_policy=ui.IwpFillPolicy.IWP_STRETCH)

    # A USD/MDL material whose diffuse input is set to
    # ``dynamic://my_texture`` will now sample these pixels.
)doc")
        .def(py::init(
                 [](const std::string& textureName) {
                     pybind11::gil_scoped_release gil;
                     return ImageProvider::create<DynamicTextureProvider>(textureName);
                 }),
             py::arg("texture_name"),
             R"doc(Construct a ``DynamicTextureProvider`` bound to a named dynamic texture.

Args:
    texture_name: Name of the dynamic texture resource that this provider will
        own and update. The renderer references the texture as
        ``dynamic://<texture_name>``; passing a name that already begins with
        the ``dynamic://`` prefix is also accepted and will not be prefixed a
        second time. Any subsequent call to ``set_bytes_data`` (or related
        upload methods inherited from :class:`ByteImageProvider`) replaces the
        contents of this texture, and every material, shader, or
        ``ImageWithProvider`` that references the same URI will see the new
        pixels on the next frame.
)doc")
        /**/;
}
