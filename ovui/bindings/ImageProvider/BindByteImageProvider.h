/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <pybind11/pybind11.h>
#include "../PlatformBindings.h"
#include <pybind11/functional.h>

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/platform/Log.h>
#include <pybind11/functional.h>
#include <pybind11/numpy.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <limits>
#include <memory>
#include <vector>

namespace py = pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

#ifndef OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY
#define OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY " Call it on the UI thread; from another thread use publish_on_ui_thread."
#endif

namespace
{

// shared dispatch for the validator's reject path. In strict mode
// (caller passed strict=True from python) raise ValueError; otherwise log and
// return false so the caller can skip the GPU upload silently. The fmt string
// must be safe to consume twice (printf-style).
template <typename... Args>
static bool _rejectImageBuffer(bool strict, const char* fmt, Args... args)
{
    char msg[512];
    if constexpr (sizeof...(Args) == 0)
    {
        // No varargs: gcc's -Werror=format-security forbids snprintf(buf, sz, fmt) with a
        // non-literal fmt and no extra args, so route the plain message through "%s".
        std::snprintf(msg, sizeof(msg), "%s", fmt);
    }
    else
    {
        std::snprintf(msg, sizeof(msg), fmt, args...);
    }
    if (strict)
    {
        throw pybind11::value_error(msg);
    }
    OMNIUI_LOG_ERROR("%s", msg);
    return false;
}

// validate that the python-side `sizes` argument and the byte
// buffer we are about to forward to ByteImageProvider::setBytesData are
// consistent BEFORE the call. Without this, an undersized python sequence
// (or a malformed `sizes`) reaches carb::graphics::ResourceLoader::loadTexture
// which does `memcpy(dst, src, stride * height)` and reads past the end of
// our buffer, crashing the process inside VCRUNTIME140!memcpy_repmovs.
//
// `byteCount` is the size in BYTES of the buffer the caller is about to hand
// to setBytesData (i.e. `bytes.size() * sizeof(element)`). Returns true if
// it's safe to proceed, false if we should reject the call (with an actionable
// OMNIUI_LOG_ERROR already emitted). If `strict` is true, a rejection raises
// pybind11::value_error (-> python ValueError) instead of returning false.
// `stride` is the per-row byte pitch the renderer will actually use:
//   * `-1` means "auto-calculate" (use width * texelSize bytes per row, the same default
//     ByteImageProvider::setBytesData applies via kAutoCalculateStride).
//   * any other negative value is invalid — reject up front.
//   * `0` is invalid (a zero-byte row pitch is malformed and would underflow further math).
//   * a positive value is the explicit row pitch; it must be at least width * texelSize
//     (else rows overlap), and the required byte count becomes stride * height instead of
//     width * height * texelSize — the renderer downstream does `memcpy(dst, src, stride * height)`,
//     so the buffer-vs-sizes check has to be against the pitch the renderer will actually walk.
static bool _validatePythonImageBuffer(const char* caller,
                                       const std::vector<uint32_t>& sizes,
                                       PixelFormat format,
                                       size_t byteCount,
                                       int stride = -1,
                                       bool strict = false)
{
    if (sizes.size() < 2)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call, `sizes` must contain at least [width, height] "
                                  "(got %zu entries). Skipping GPU upload to avoid renderer crash.",
                                  caller, sizes.size());
    }
    const uint32_t width = sizes[0];
    const uint32_t height = sizes[1];
    if (width == 0 || height == 0)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call with zero-size image (sizes=%u x %u). "
                                  "Skipping GPU upload to avoid renderer crash.",
                                  caller, width, height);
    }
    if (format == PixelFormat::eUnknown)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call with Format::eUnknown (sizes=%u x %u). "
                                  "Skipping GPU upload to avoid renderer crash.",
                                  caller, width, height);
    }

    const size_t formatSize = getPixelFormatSize(format);
    if (formatSize == 0)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call with unsupported format=%u (sizes=%u x %u). "
                                  "Skipping GPU upload to avoid renderer crash.",
                                  caller, static_cast<uint32_t>(format), width, height);
    }
    // Overflow-safe required-byte computation. With uint32_t width/height and 1-16 byte texels a
    // size_t wrap is only theoretical (would need width*height*texel > 2^64), but the worst-case
    // consequence is an undersized buffer slipping past this guard and crashing in memcpy
    // downstream — exactly what this check exists to prevent. Use a portable division-based
    // check that compiles on MSVC as well (cannot use __builtin_mul_overflow there).
    const size_t widthSz = static_cast<size_t>(width);
    const size_t heightSz = static_cast<size_t>(height);
    const size_t texelSz = static_cast<size_t>(formatSize);
    constexpr size_t kSizeMax = std::numeric_limits<size_t>::max();
    if ((widthSz != 0 && heightSz > kSizeMax / widthSz) ||
        ((widthSz * heightSz) != 0 && texelSz > kSizeMax / (widthSz * heightSz)))
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call, required byte count overflows size_t (sizes=%u x %u, "
                                  "format=%u, texel=%u bytes). Skipping GPU upload to avoid renderer crash.",
                                  caller, width, height,
                                  static_cast<uint32_t>(format),
                                  static_cast<unsigned>(formatSize));
    }
    const size_t pixelCount = widthSz * heightSz;
    const size_t rowSize = widthSz * texelSz;

    // Resolve required byte count against the row pitch the renderer will actually walk.
    size_t requiredBytes = pixelCount * texelSz;
    const char* pitchDescription = "row size";
    if (stride < -1)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call with invalid negative stride=%d (only -1 is the auto-calc "
                                  "sentinel). Skipping GPU upload to avoid renderer crash.",
                                  caller, stride);
    }
    else if (stride == 0)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call with stride=0 (a zero-byte row pitch is malformed). "
                                  "Skipping GPU upload to avoid renderer crash.",
                                  caller);
    }
    else if (stride > 0)
    {
        const size_t strideSz = static_cast<size_t>(stride);
        if (strideSz < rowSize)
        {
            return _rejectImageBuffer(strict,
                                      "%s: rejected call, stride=%zu < row size %zu (width=%u * %u-byte format=%u); "
                                      "rows would overlap. Skipping GPU upload to avoid renderer crash.",
                                      caller, strideSz, rowSize, width,
                                      static_cast<unsigned>(formatSize),
                                      static_cast<uint32_t>(format));
        }
        if (heightSz != 0 && strideSz > kSizeMax / heightSz)
        {
            return _rejectImageBuffer(strict,
                                      "%s: rejected call, stride*height overflows size_t (stride=%zu, height=%u). "
                                      "Skipping GPU upload to avoid renderer crash.",
                                      caller, strideSz, height);
        }
        requiredBytes = strideSz * heightSz;
        pitchDescription = "stride*height";
    }

    if (byteCount < requiredBytes)
    {
        return _rejectImageBuffer(strict,
                                  "%s: rejected call, supplied buffer is %zu bytes but %s for %u x %u x %u-byte format=%u "
                                  "needs %zu bytes. Skipping GPU upload to avoid renderer crash.",
                                  caller, byteCount, pitchDescription, width, height,
                                  static_cast<unsigned>(formatSize),
                                  static_cast<uint32_t>(format),
                                  requiredBytes);
    }
    return true;
}

/// A Python callback of subscribe_upload_events. The provider can outlive the
/// interpreter: native code can keep it, and the upload state of every
/// provider lives until the process ends. Releasing a Python object after the
/// interpreter has ended aborts the process, so every callback is released at
/// interpreter exit, while Python still works. After that a call does nothing.
struct PyUploadCallback
{
    explicit PyUploadCallback(py::function f) : fn(std::move(f)) {}
    ~PyUploadCallback()
    {
        if (!fn)
            return;
        if (Py_IsInitialized())
        {
            py::gil_scoped_acquire gil;
            fn = py::function();
        }
        else
        {
            // The interpreter has ended: its objects cannot be released.
            fn.release();
        }
    }
    /// Set at interpreter exit. Read without the GIL.
    std::atomic<bool> released{ false };
    /// Changed only with the GIL held.
    py::function fn;
};

/// All callbacks that may still hold Python objects. Used only with the GIL held.
std::vector<std::weak_ptr<PyUploadCallback>>& pyUploadCallbacks()
{
    static std::vector<std::weak_ptr<PyUploadCallback>> callbacks;
    return callbacks;
}

/// Runs at interpreter exit (Python ``atexit``), with the GIL held.
void releasePyUploadCallbacks()
{
    for (const auto& weak : pyUploadCallbacks())
    {
        if (auto callback = weak.lock())
        {
            callback->released = true;
            callback->fn = py::function();
        }
    }
    pyUploadCallbacks().clear();
}

uint64_t subscribePyUploadEvents(ByteImageProvider* self, py::function callback)
{
    auto holder = std::make_shared<PyUploadCallback>(std::move(callback));
    auto& all = pyUploadCallbacks();
    all.erase(std::remove_if(all.begin(), all.end(), [](const auto& weak) { return weak.expired(); }), all.end());
    all.push_back(holder);
    return self->subscribeUploadEvents([holder](const ByteImageUploadEvent& e) {
        if (holder->released)
            return;
        py::gil_scoped_acquire gil;
        if (!holder->fn)
            return;
        try
        {
            holder->fn(e.kind, e.uploadId, e.requestedDeviceMask, e.uploadedDeviceMask);
        }
        catch (py::error_already_set& error)
        {
            // There is no Python caller to raise to: the upload has already
            // happened. Report it the way Python reports such errors, with the
            // traceback, through sys.unraisablehook.
            error.discard_as_unraisable("ByteImageProvider upload event subscriber");
        }
    });
}

/// True when the backend accepted the pixels, False when they were refused
/// (last_upload_result.cause says why), None when there is no GPU backend: no
/// renderer, and that is not a failure.
py::object uploadAnswer(const ByteImageUploadResult& result)
{
    if (result.status == UploadStatus::eNoBackend)
        return py::none();
    return py::bool_(result.accepted());
}

} // namespace

static py::object _setBytesData(ByteImageProvider* self,
                                const py::sequence& bytesSeq,
                                const std::vector<uint32_t>& sizes,
                                PixelFormatObject nativeFormat,
                                int stride,
                                bool strict = false)
{
    PixelFormat format = pixelFormatFromPython(nativeFormat);
    const size_t bytesSeqSize = bytesSeq.size();
    if (bytesSeqSize == 0)
    {
        // empty buffer is a zero-byte buffer, which the validator would reject. Honor
        // strict so callers opted into the exception contract see ValueError instead of a silent skip.
        _rejectImageBuffer(strict,
                           "ByteImageProvider.set_bytes_data: rejected call, empty byte sequence "
                           "(at least one element required). Skipping GPU upload.");
        return uploadAnswer(self->rejectUpload("set_bytes_data: the byte sequence is empty"));
    }

    const auto bytesSeqEntryAccessor = bytesSeq[0];
    if (py::isinstance<py::sequence>(bytesSeqEntryAccessor))
    {
        py::sequence bytesSeqEntry = bytesSeqEntryAccessor.cast<py::sequence>();
        const size_t bytesSeqEntrySize = bytesSeqEntry.size();
        if (bytesSeqEntrySize == 0)
        {
            // empty per-pixel tuple makes pixelTupleSize=0, so every subsequent
            // copy / validator call is a zero-byte upload. Honor strict.
            _rejectImageBuffer(strict,
                               "ByteImageProvider.set_bytes_data: rejected call, empty per-pixel "
                               "tuple in byte sequence. Skipping GPU upload.");
            return uploadAnswer(self->rejectUpload("set_bytes_data: the first pixel tuple is empty"));
        }

        const py::handle& pixelTupleEntryHandle = bytesSeqEntry[0];
        if (py::isinstance<py::int_>(pixelTupleEntryHandle))
        {
            // The sequence fed is an array of tuples (colors), integer channels, e.g. [[128, 128, 128, 128], [255, 255,
            // 255, 255], ...]
            std::vector<uint8_t> bytes;
            std::vector<uint8_t> pixelTuple = bytesSeqEntry.cast<std::vector<uint8_t>>();
            const size_t pixelTupleSize = pixelTuple.size();
            bytes.resize(bytesSeqSize * pixelTupleSize);
            size_t offset = 0;
            for (auto it = bytesSeq.begin(); it != bytesSeq.end(); it++)
            {
                pixelTuple = it->cast<std::vector<uint8_t>>();
                // reject a ragged tuple sequence (a later entry having a different
                // channel count than the first one) before it can overrun `bytes`. Uses a
                // subtraction-based bounds check so the guard cannot be bypassed by a size_t wrap.
                const size_t tupleSize = pixelTuple.size();
                if (tupleSize != pixelTupleSize || offset > bytes.size() || tupleSize > (bytes.size() - offset))
                {
                    _rejectImageBuffer(strict,
                                       "ByteImageProvider.set_bytes_data (uint8 tuples): rejected ragged "
                                       "tuple input (expected %zu channels per pixel, got %zu). Skipping "
                                       "GPU upload to avoid renderer crash.",
                                       pixelTupleSize, tupleSize);
                    return uploadAnswer(self->rejectUpload("set_bytes_data: the pixel tuples do not all have the same number of channels"));
                }
                for (auto it2 = pixelTuple.begin(); it2 != pixelTuple.end(); it2++)
                {
                    bytes[offset] = *it2;
                    ++offset;
                }
            }
            if (format == PixelFormat::eUnknown)
                format = PixelFormat::eRGBA8_UNORM;
            // gate the renderer call on a buffer-vs-sizes check.
            if (!_validatePythonImageBuffer("ByteImageProvider.set_bytes_data (uint8 tuples)",
                                            sizes, format, bytes.size() * sizeof(uint8_t), stride, strict))
            {
                return uploadAnswer(self->rejectUpload("set_bytes_data: the sizes, format or stride do not match the byte sequence"));
            }
            return uploadAnswer(self->uploadBytesData(bytes.data(), { sizes[0], sizes[1] }, stride, format));
        }
        else if (py::isinstance<py::float_>(pixelTupleEntryHandle))
        {
            // The sequence fed is an array of tuples (colors), floating point channels, e.g. [[0.5, 0.5, 0.5, 0.5],
            // [1.0, 1.0, 1.0, 1.0], ...]
            std::vector<float> bytes;
            std::vector<float> pixelTuple = bytesSeqEntry.cast<std::vector<float>>();
            const size_t pixelTupleSize = pixelTuple.size();
            bytes.resize(bytesSeqSize * pixelTupleSize);
            size_t offset = 0;
            for (auto it = bytesSeq.begin(); it != bytesSeq.end(); it++)
            {
                pixelTuple = it->cast<std::vector<float>>();
                // same ragged-tuple guard as the uint8 path above.
                const size_t tupleSize = pixelTuple.size();
                if (tupleSize != pixelTupleSize || offset > bytes.size() || tupleSize > (bytes.size() - offset))
                {
                    _rejectImageBuffer(strict,
                                       "ByteImageProvider.set_bytes_data (float tuples): rejected ragged "
                                       "tuple input (expected %zu channels per pixel, got %zu). Skipping "
                                       "GPU upload to avoid renderer crash.",
                                       pixelTupleSize, tupleSize);
                    return uploadAnswer(self->rejectUpload("set_bytes_data: the pixel tuples do not all have the same number of channels"));
                }
                for (auto it2 = pixelTuple.begin(); it2 != pixelTuple.end(); it2++)
                {
                    bytes[offset] = *it2;
                    ++offset;
                }
            }
            if (format == PixelFormat::eUnknown)
                format = PixelFormat::eRGBA32_FLOAT;
            // gate the renderer call on a buffer-vs-sizes check.
            if (!_validatePythonImageBuffer("ByteImageProvider.set_bytes_data (float tuples)",
                                            sizes, format, bytes.size() * sizeof(float), stride, strict))
            {
                return uploadAnswer(self->rejectUpload("set_bytes_data: the sizes, format or stride do not match the byte sequence"));
            }
            return uploadAnswer(self->uploadBytesData((const uint8_t*)bytes.data(), { sizes[0], sizes[1] }, stride, format));
        }
        return uploadAnswer(
            self->rejectUpload("set_bytes_data: the pixel tuples hold values that are not int or float"));
    }
    else if (py::isinstance<py::int_>(bytesSeqEntryAccessor))
    {
        // The sequence fed is an array of flattened integer channel values, e.g. [128, 128, 128, 128, 255, 255, 255,
        // 255, ...]
        std::vector<uint8_t> bytes = bytesSeq.cast<std::vector<uint8_t>>();
        if (format == PixelFormat::eUnknown)
            format = PixelFormat::eRGBA8_UNORM;
        // gate the renderer call on a buffer-vs-sizes check.
        if (!_validatePythonImageBuffer("ByteImageProvider.set_bytes_data (uint8 flat)",
                                        sizes, format, bytes.size() * sizeof(uint8_t), stride, strict))
        {
            return uploadAnswer(self->rejectUpload("set_bytes_data: the sizes, format or stride do not match the byte sequence"));
        }
        return uploadAnswer(self->uploadBytesData(bytes.data(), { sizes[0], sizes[1] }, stride, format));
    }
    else if (py::isinstance<py::float_>(bytesSeqEntryAccessor))
    {
        // The sequence fed is an array of flattened floating point channel values, e.g. [0.5, 0.5, 0.5,
        // 0.5, 1.0, 1.0, 1.0, 1.0, ...]
        std::vector<float> bytes = bytesSeq.cast<std::vector<float>>();
        if (format == PixelFormat::eUnknown)
            format = PixelFormat::eRGBA32_FLOAT;
        // gate the renderer call on a buffer-vs-sizes check.
        if (!_validatePythonImageBuffer("ByteImageProvider.set_bytes_data (float flat)",
                                        sizes, format, bytes.size() * sizeof(float), stride, strict))
        {
            return uploadAnswer(self->rejectUpload("set_bytes_data: the sizes, format or stride do not match the byte sequence"));
        }
        return uploadAnswer(self->uploadBytesData((const uint8_t*)bytes.data(), { sizes[0], sizes[1] }, stride, format));
    }
    return uploadAnswer(
        self->rejectUpload("set_bytes_data: the sequence holds values that are not int, float or pixel tuples"));
}

void wrapByteImageProvider(py::module& m)
{
    // Release the Python upload callbacks while the interpreter still works.
    py::module_::import("atexit").attr("register")(py::cpp_function(&releasePyUploadCallbacks));

    py::enum_<UploadStatus>(m, "UploadStatus",
                            "What an upload achieved. FAILED: nothing new was accepted, old pixels stay. "
                            "ENQUEUED: accepted and ordered before later sampling, the copy may still run. "
                            "COMPLETE: the copy finished. NO_BACKEND: no GPU backend (no renderer), nothing was "
                            "uploaded, and this is not a failure.")
        .value("FAILED", UploadStatus::eFailed)
        .value("ENQUEUED", UploadStatus::eEnqueued)
        .value("COMPLETE", UploadStatus::eComplete)
        .value("NO_BACKEND", UploadStatus::eNoBackend);

    py::enum_<ByteImageUploadEvent::Kind>(m, "ByteImageUploadEventKind", "Kind of an upload event.")
        .value("FAILED", ByteImageUploadEvent::Kind::eFailed)
        .value("ENQUEUED", ByteImageUploadEvent::Kind::eEnqueued)
        .value("COMPLETED", ByteImageUploadEvent::Kind::eCompleted);

    py::class_<ByteImageUploadResult>(m, "ByteImageUploadResult", "What one upload of a ByteImageProvider did.")
        .def_readonly("status", &ByteImageUploadResult::status)
        .def_readonly("upload_id", &ByteImageUploadResult::uploadId)
        .def_readonly("requested_device_mask", &ByteImageUploadResult::requestedDeviceMask)
        .def_readonly("uploaded_device_mask", &ByteImageUploadResult::uploadedDeviceMask)
        .def_property_readonly("accepted", &ByteImageUploadResult::accepted)
        .def_property_readonly(
            "cause",
            [](const ByteImageUploadResult& r) -> py::object { return r.cause ? py::object(py::str(r.cause)) : py::none(); },
            "Why nothing new was accepted (FAILED or NO_BACKEND), or None.")
        .def("__bool__", &ByteImageUploadResult::accepted);

    py::class_<ByteImageProvider, ImageProvider, std::shared_ptr<ByteImageProvider>>(m, "ByteImageProvider", "doc")
        .def(py::init([]() {
            pybind11::gil_scoped_release gil;
            return ImageProvider::create<ByteImageProvider>();
        }), "doc")
        .def(py::init( [](const py::sequence& bytesSeq, const std::vector<uint32_t>& sizes, PixelFormatObject format, int stride, bool strict) {
            std::shared_ptr<ByteImageProvider> result;
            {
                pybind11::gil_scoped_release gil;
                result = ImageProvider::create<ByteImageProvider>();
            }
            if (result)
            {
                _setBytesData(result.get(), bytesSeq, sizes, format, stride, strict);
            }
            return result;
        }), py::arg("bytes"), py::arg("sizes"), py::arg("format") = pixelFormatToPython(PixelFormat::eUnknown), py::arg("stride") = -1,
        py::arg("strict") = false,
        "doc")
        .def(
            "set_data",
            [](ByteImageProvider* self, const std::vector<uint8_t>& bytes, const std::vector<uint32_t>& sizes, bool strict) {
                OMNIUI_LOG_WARN(
                    "ByteImageProvider.set_data is a deprecated function and will be removed in a future release.\n Please move to using ByteImageProvider.set_bytes_data instead.");
                // deprecated path still defaults to RGBA8_UNORM; gate the renderer call.
                if (!_validatePythonImageBuffer("ByteImageProvider.set_data",
                                                sizes, PixelFormat::eRGBA8_UNORM,
                                                bytes.size() * sizeof(uint8_t),
                                                /*stride=*/-1, strict))
                {
                    return uploadAnswer(self->rejectUpload("set_data: the sizes do not match the bytes"));
                }
                return uploadAnswer(self->uploadBytesData(bytes.data(), { sizes[0], sizes[1] }));
            },
            py::arg("bytes"), py::arg("sizes"), py::arg("strict") = false,
            "[DEPRECATED FUNCTION]" OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def(
            "set_data_array",
            [](ByteImageProvider* self, py::array_t<uint8_t>& bytes, const std::vector<uint32_t>& sizes, bool strict) {
                py::buffer_info bytes_buf = bytes.request();
                // numpy gives us the underlying byte count, so we can validate here.
                const size_t byteCount = (bytes_buf.size > 0 && bytes_buf.itemsize > 0)
                                             ? static_cast<size_t>(bytes_buf.size) *
                                                   static_cast<size_t>(bytes_buf.itemsize)
                                             : 0u;
                if (!_validatePythonImageBuffer("ByteImageProvider.set_data_array",
                                                sizes, PixelFormat::eRGBA8_UNORM, byteCount,
                                                /*stride=*/-1, strict))
                {
                    return uploadAnswer(self->rejectUpload("set_data_array: the sizes do not match the array"));
                }
                ByteImageUploadResult result;
                {
                    // The copy and the GPU upload run without the GIL, so Python
                    // threads (the renderer's) keep running; ``bytes`` stays
                    // referenced by the call's arguments. An upload event
                    // subscriber takes the GIL itself.
                    py::gil_scoped_release release;
                    result = self->uploadBytesData(static_cast<uint8_t *>(bytes_buf.ptr), { sizes[0], sizes[1] });
                }
                return uploadAnswer(result);
            },
            py::arg("bytes"), py::arg("sizes"), py::arg("strict") = false,
            "Sets an (H, W, 4) uint8 array as the image. Returns True, False or None, as set_bytes_data."
            OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY)
        .def("set_bytes_data", &_setBytesData,
             "Sets Python sequence as byte data. The image provider will recognize flattened color values, or sequence within sequence and convert it into an image. Returns True when the backend accepted the pixels, False when they were refused, and None when there is no GPU backend (no renderer; this is not a failure). False means the previous pixels stay, and last_upload_result.cause says why. True does not mean that the copy has finished: see completed_upload_id. Pass strict=True to raise ValueError on malformed input instead of logging an error and skipping the upload." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY,
             py::arg("bytes"), py::arg("sizes"), py::arg("format") = pixelFormatToPython(PixelFormat::eUnknown), py::arg("stride") = -1,
             py::arg("strict") = false)
        .def(
            "set_raw_bytes_data",
            [](ByteImageProvider* self, const void* rawBytes, const std::vector<uint32_t>& sizes, PixelFormatObject format,
               int stride, bool strict) {
                // raw pointer path has no python-side buffer size, so we only validate
                // structural inputs here; ByteImageProvider::uploadBytesData re-validates as the
                // defense-in-depth backstop.
                if (sizes.size() < 2 || sizes[0] == 0 || sizes[1] == 0 || rawBytes == nullptr)
                {
                    _rejectImageBuffer(strict,
                                       "ByteImageProvider.set_raw_bytes_data: rejected call "
                                       "(sizes.size=%zu, w=%u, h=%u, raw_bytes=%p). Skipping GPU upload.",
                                       sizes.size(),
                                       sizes.size() > 0 ? sizes[0] : 0u,
                                       sizes.size() > 1 ? sizes[1] : 0u,
                                       rawBytes);
                    return uploadAnswer(self->rejectUpload("set_raw_bytes_data: the sizes or the pointer are not valid"));
                }
                return uploadAnswer(self->uploadBytesData((const uint8_t*)rawBytes, { sizes[0], sizes[1] }, stride, pixelFormatFromPython(format)));
            },
            "Sets byte data that the image provider will turn raw pointer array into an image. Returns True, False or None, as set_bytes_data." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY, py::arg("raw_bytes"),
            py::arg("sizes"), py::arg("format") = pixelFormatToPython(PixelFormat::eRGBA8_UNORM), py::arg("stride") = -1,
            py::arg("strict") = false)
        .def(
            "set_bytes_data_from_gpu",
            [](ByteImageProvider* self, uint64_t gpuBytes, const std::vector<uint32_t>& sizes, PixelFormatObject format,
               int stride, bool strict) {
                // GPU-pointer path; like set_raw_bytes_data we cannot size-check from
                // python, but we can still reject zero-size / missing-pointer up front so a clearly
                // malformed call doesn't reach the renderer's memcpy.
                if (sizes.size() < 2 || sizes[0] == 0 || sizes[1] == 0 || gpuBytes == 0)
                {
                    _rejectImageBuffer(strict,
                                       "ByteImageProvider.set_bytes_data_from_gpu: rejected call "
                                       "(sizes.size=%zu, w=%u, h=%u, gpu_bytes=0x%llx). Skipping GPU upload.",
                                       sizes.size(),
                                       sizes.size() > 0 ? sizes[0] : 0u,
                                       sizes.size() > 1 ? sizes[1] : 0u,
                                       static_cast<unsigned long long>(gpuBytes));
                    return uploadAnswer(self->rejectUpload("set_bytes_data_from_gpu: the sizes or the pointer are not valid"));
                }
                return uploadAnswer(self->uploadBytesDataFromGPU((const uint8_t*)gpuBytes, { sizes[0], sizes[1] }, stride, pixelFormatFromPython(format)));
            },
            "Sets byte data from a copy of gpu memory at gpuBytes. Returns True, False or None, as set_bytes_data. The GPU memory must stay valid until the call returns, or, with publish_on_ui_thread, until the change has run." OVUI_IMAGE_PROVIDER_UI_THREAD_ONLY, py::arg("gpu_bytes"),
            py::arg("sizes"), py::arg("format") = pixelFormatToPython(PixelFormat::eRGBA8_UNORM), py::arg("stride") = -1,
            py::arg("strict") = false)
        .def_property_readonly("last_upload_result", &ByteImageProvider::getLastUploadResult,
                               "Result of the last upload call. Status is FAILED before the first call.")
        .def_property_readonly("upload_failure_count", &ByteImageProvider::getUploadFailureCount,
                               "How many upload calls of this provider were rejected. NO_BACKEND is not counted.")
        .def_property_readonly("completed_upload_id", &ByteImageProvider::getCompletedUploadId,
                               "The highest upload id whose copy finished, or 0.")
        .def("subscribe_upload_events", &subscribePyUploadEvents,
             "Calls callback(kind, upload_id, requested_device_mask, uploaded_device_mask) for each upload event. "
             "An exception raised by the callback is reported through sys.unraisablehook; the upload and the other "
             "callbacks are not affected. Callbacks are released at interpreter exit. "
             "Returns an id for unsubscribe_upload_events.",
             py::arg("callback"))
        .def("unsubscribe_upload_events", &ByteImageProvider::unsubscribeUploadEvents, py::arg("subscription_id"))
        .def_static("has_upload_backend", &ByteImageProvider::hasUploadBackend,
                    "True when a GPU backend is registered. False is a missing renderer, not a refused upload.")
        .def("inject_upload_failures", &ByteImageProvider::injectUploadFailures, py::arg("count"),
             "Test hook. The next count upload calls of this provider fail before they reach the backend. "
             "Other providers are not affected. Previous pixels stay. Pass 0 to stop. Returns how many were still "
             "waiting.")
        /**/;
}
