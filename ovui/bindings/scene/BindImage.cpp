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
#include <omni/ui/scene/Image.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindImage.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_NS::ImageProvider, ImageProvider);

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapImage(module& m)
{
    constexpr const char* imageDoc = OMNIUI_PYBIND_CLASS_DOC(Image);
    static constexpr char imageConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Image, Image);
    static constexpr char imageConstructor1Doc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Image, Image01);
    static constexpr char imageConstructor2Doc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Image, Image2);

    auto image = class_<Image, Rectangle, std::shared_ptr<Image>>(m, "Image", imageDoc);

    enum_<Image::FillPolicy>(image, "FillPolicy", "")
        .value("STRETCH", Image::FillPolicy::eStretch)
        .value("PRESERVE_ASPECT_FIT", Image::FillPolicy::ePreserveAspectFit)
        .value("PRESERVE_ASPECT_CROP", Image::FillPolicy::ePreserveAspectCrop);

    struct ImageDestructor
    {
        void operator()(Image* image)
        {
            // RasterImage destructor will wait on asset loading, which requires the GIL, so make sure the GIL is not
            // locked when we destroy images.
            //
            // Destructor can be called from both C++ and Python code paths. Only release the GIL if the current
            // thread actually holds it — pybind11's gil_scoped_release calls PyEval_SaveThread unconditionally,
            // which aborts with a Python fatal error when the GIL is not held (seen during scene draw callbacks
            // invoked from Kit's main thread without the GIL).
            if (PyGILState_Check())
            {
                pybind11::gil_scoped_release nogil;
                delete image;
            }
            else
            {
                delete image;
            }
        }
    };

    image
        .def(init([](const std::string& sourceUrl, Float width, Float height, kwargs kwargs)
                  { OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(Image, ImageDestructor{}, sourceUrl, width, height) }),
             arg("source_url"), arg("width") = 1.0, arg("height") = 1.0, imageConstructorDoc)
        .def(init([](const std::shared_ptr<ImageProvider>& imageProvider, Float width, Float height, kwargs kwargs)
                  { OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(Image, ImageDestructor{}, imageProvider, width, height) }),
             arg("image_provider"), arg("width") = 1.0, arg("height") = 1.0, imageConstructor1Doc)
        .def(init([](Float width, Float height, kwargs kwargs) { OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(Image, ImageDestructor{}, width, height) }),
             arg("width") = 1.0, arg("height") = 1.0, imageConstructor2Doc)
        .def_property("source_url", &Image::getSourceUrl, &Image::setSourceUrl, OMNIUI_PYBIND_DOC_Image_sourceUrl)
        .def_property(
            "image_provider", &Image::getImageProvider, &Image::setImageProvider, OMNIUI_PYBIND_DOC_Image_imageProvider)
        .def_property("fill_policy", &Image::getFillPolicy, &Image::setFillPolicy, OMNIUI_PYBIND_DOC_Image_fillPolicy)
        .def_property("image_width", &Image::getImageWidth, &Image::setImageWidth,
                      OMNIUI_PYBIND_DOC_ImageHelper_imageWidth)
        .def_property("image_height", &Image::getImageHeight, &Image::setImageHeight,
                      OMNIUI_PYBIND_DOC_ImageHelper_imageHeight)
        /* */;
}
