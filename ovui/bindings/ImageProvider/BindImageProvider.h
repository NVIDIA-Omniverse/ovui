/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ImageProvider/ImageProvider.h>

#include <pybind11/pybind11.h>
#include "../PlatformBindings.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>

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

#ifndef OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY
#define OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY " Call it on the UI thread; from another thread use publish_on_ui_thread."
#endif

namespace
{


/// A Python change of publish_on_ui_thread. It keeps the provider object alive until the change has run,
/// so that Python cannot destroy the provider while its change waits or runs. The change can outlive the
/// interpreter when nothing runs the queue, so it is released at interpreter exit, while Python still
/// works. After that a run does nothing.
struct PyPublishedUpdate
{
    PyPublishedUpdate(function f, object p) : fn(std::move(f)), provider(std::move(p)) {}
    ~PyPublishedUpdate()
    {
        if (!fn && !provider)
            return;
        if (Py_IsInitialized())
        {
            gil_scoped_acquire gil;
            fn = function();
            provider = object();
        }
        else
        {
            // The interpreter has ended: its objects cannot be released.
            fn.release();
            provider.release();
        }
    }
    /// Set at interpreter exit. Read without the GIL.
    std::atomic<bool> released{ false };
    /// Changed only with the GIL held.
    function fn;
    object provider;
};

/// All Python changes that may still hold Python objects. Used only with the GIL held.
std::vector<std::weak_ptr<PyPublishedUpdate>>& pyPublishedUpdates()
{
    static std::vector<std::weak_ptr<PyPublishedUpdate>> updates;
    return updates;
}

/// Runs at interpreter exit (Python ``atexit``), with the GIL held.
void releasePyPublishedUpdates()
{
    // Copy first: releasing a provider can destroy it, and that destroys its waiting changes.
    std::vector<std::shared_ptr<PyPublishedUpdate>> alive;
    for (const auto& weak : pyPublishedUpdates())
    {
        if (auto update = weak.lock())
            alive.push_back(std::move(update));
    }
    pyPublishedUpdates().clear();
    for (const auto& update : alive)
    {
        update->released = true;
        update->fn = function();
        update->provider = object();
    }
}

uint64_t publishPyUpdate(object self, function update, bool replacePending)
{
    ImageProvider* provider = self.cast<ImageProvider*>();
    auto holder = std::make_shared<PyPublishedUpdate>(std::move(update), self);
    auto& all = pyPublishedUpdates();
    all.erase(std::remove_if(all.begin(), all.end(), [](const auto& weak) { return weak.expired(); }), all.end());
    all.push_back(holder);
    return provider->publishOnUiThread(
        [holder](ImageProvider&) {
            if (holder->released)
                return;
            gil_scoped_acquire gil;
            if (!holder->fn)
                return;
            try
            {
                holder->fn(holder->provider);
            }
            catch (error_already_set& error)
            {
                // There is no Python caller to raise to: the change was given earlier, on another thread.
                // Report it the way Python reports such errors, with the traceback.
                error.discard_as_unraisable("ImageProvider.publish_on_ui_thread change");
            }
        },
        replacePending);
}

} // namespace

void wrapImageProvider(module& m)
{
    // Release the Python changes that still wait while the interpreter still works.
    module_::import("atexit").attr("register")(cpp_function(&releasePyPublishedUpdates));

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
             [](ImageProvider* self, void* texReference, uint32_t width, uint32_t height, PixelFormatObject format) {
                 self->setImageData(texReference, { width, height }, pixelFormatFromPython(format));
             },
             "Sets the texture reference, the size and the format." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def("set_image_data",
             [](ImageProvider* self, rtx::resourcemanager::RpResource& rpRsrc, int64_t presentationKey, void* metadata) {
                 self->setImageData(rpRsrc, static_cast<uint64_t>(presentationKey));
             }, arg("rp_resource"), arg("presentation_key") = 0, arg("metadata") = nullptr,
             "Sets the image from a GPU resource." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def("clear_presentation_key", &ImageProvider::clearPresentationKey,
             "Leave presentation-key mode. The texture reference and the managed resource do not change."
             OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def("publish_on_ui_thread", &publishPyUpdate, arg("update"), arg("replace_pending") = false,
             "Gives a change of this provider to the UI thread. It can be called on any thread, for example a "
             "render thread. The UI thread calls update(provider) before it draws, so update can call "
             "set_image_data, set_bytes_data_from_gpu and the other setters, and the image, its size and its "
             "format change together. update must keep what it uses (pixels, GPU memory) alive until it has "
             "run; it is released on the UI thread after it ran, or on the calling thread when a newer change "
             "replaces it. The changes of one provider run in order and none is dropped, except with "
             "replace_pending=True: then the change replaces the last waiting change of this provider that was "
             "also given with replace_pending=True (a mailbox for frames). An exception of update is reported "
             "through sys.unraisablehook. The provider is kept alive until its changes have run. Returns the "
             "number of the change; compare it with applied_publication_id.")
        .def_property_readonly("applied_publication_id", &ImageProvider::getAppliedPublicationId,
                               "The highest number from publish_on_ui_thread whose change has run (or was replaced "
                               "by a later one that has run). It can be read on any thread.")
        .def_static("apply_published_updates", &ImageProvider::applyPublishedUpdates,
                    "Runs the changes given with publish_on_ui_thread to all providers. Call it on the UI thread. "
                    "The ovui frame does it once per frame before the draw, so an app does not need it. The "
                    "calling thread becomes the UI thread of the thread checks: a call on another thread moves "
                    "the checks to that thread. Returns how many ran.")
        .def_static("off_ui_thread_call_count", &ImageProvider::getOffUiThreadCallCount,
                    "How many changing calls of image providers ran on a thread that is not the UI thread. A "
                    "test can check that it stays 0.")
        .def_static("set_presentation_key_lease_ms", &ImageProvider::setPresentationKeyLeaseMs, arg("ms"),
                    "Opt in to a lease: time in ms that a presentation key stays in use without a new set_image_data call. The default 0 means no lease.")
        .def_static("retire_presentation_key", &ImageProvider::retirePresentationKey, arg("key"),
                    "Retire a presentation key for all providers that hold it.")
        .def_property_readonly("presentation_key", &ImageProvider::getPresentationKey,
                               "The stored presentation key, or 0 when the provider is not in key mode.")
        .def("destroy",
             [](ImageProvider* self) {
                 self->clearPresentationKey();
                 self->setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
             },
             "Removes the image." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def("get_managed_resource",
             [](ImageProvider* self) -> void* { return static_cast<void*>(self->getManagedResource()); },
             return_value_policy::reference,
             "The managed GPU resource. Read it on the UI thread: the next change can release it.")
        /**/;
}
