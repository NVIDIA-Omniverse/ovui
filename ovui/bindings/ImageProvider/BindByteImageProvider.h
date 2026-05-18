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

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/platform/Log.h>
#include <pybind11/numpy.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace py = pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

static void _setBytesData(ByteImageProvider* self,
                          const py::sequence& bytesSeq,
                          const std::vector<uint32_t>& sizes,
                          PixelFormat format,
                          int stride)
{
    const size_t bytesSeqSize = bytesSeq.size();
    if (bytesSeqSize == 0)
        return;

    const auto bytesSeqEntryAccessor = bytesSeq[0];
    if (py::isinstance<py::sequence>(bytesSeqEntryAccessor))
    {
        py::sequence bytesSeqEntry = bytesSeqEntryAccessor.cast<py::sequence>();
        const size_t bytesSeqEntrySize = bytesSeqEntry.size();
        if (bytesSeqEntrySize == 0)
        {
            OMNIUI_LOG_WARN("Invalid tuple fed into set_bytes_data!");
            return;
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
                for (auto it2 = pixelTuple.begin(); it2 != pixelTuple.end(); it2++)
                {
                    bytes[offset] = *it2;
                    ++offset;
                }
            }
            if (format == PixelFormat::eUnknown)
                format = PixelFormat::eRGBA8_UNORM;
            self->setBytesData(bytes.data(), { sizes[0], sizes[1] }, stride, format);
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
                for (auto it2 = pixelTuple.begin(); it2 != pixelTuple.end(); it2++)
                {
                    bytes[offset] = *it2;
                    ++offset;
                }
            }
            if (format == PixelFormat::eUnknown)
                format = PixelFormat::eRGBA32_FLOAT;
            self->setBytesData((const uint8_t*)bytes.data(), { sizes[0], sizes[1] }, stride, format);
        }
        else
        {
            OMNIUI_LOG_ERROR("Unsupported py::sequence[py::sequence] layout!");
        }
    }
    else if (py::isinstance<py::int_>(bytesSeqEntryAccessor))
    {
        // The sequence fed is an array of flattened integer channel values, e.g. [128, 128, 128, 128, 255, 255, 255,
        // 255, ...]
        std::vector<uint8_t> bytes = bytesSeq.cast<std::vector<uint8_t>>();
        if (format == PixelFormat::eUnknown)
            format = PixelFormat::eRGBA8_UNORM;
        self->setBytesData(bytes.data(), { sizes[0], sizes[1] }, stride, format);
    }
    else if (py::isinstance<py::float_>(bytesSeqEntryAccessor))
    {
        // The sequence fed is an array of flattened floating point channel values, e.g. [0.5, 0.5, 0.5,
        // 0.5, 1.0, 1.0, 1.0, 1.0, ...]
        std::vector<float> bytes = bytesSeq.cast<std::vector<float>>();
        if (format == PixelFormat::eUnknown)
            format = PixelFormat::eRGBA32_FLOAT;
        self->setBytesData((const uint8_t*)bytes.data(), { sizes[0], sizes[1] }, stride, format);
    }
    else
    {
        OMNIUI_LOG_ERROR("Unsupported py::sequence layout!");
    }
}

void wrapByteImageProvider(py::module& m)
{
    py::class_<ByteImageProvider, ImageProvider, std::shared_ptr<ByteImageProvider>>(m, "ByteImageProvider", "doc")
        .def(py::init([]() {
            pybind11::gil_scoped_release gil;
            return ImageProvider::create<ByteImageProvider>();
        }), "doc")
        .def(py::init( [](const py::sequence& bytesSeq, const std::vector<uint32_t>& sizes, PixelFormat format, int stride) {
            std::shared_ptr<ByteImageProvider> result;
            {
                pybind11::gil_scoped_release gil;
                result = ImageProvider::create<ByteImageProvider>();
            }
            if (result)
            {
                _setBytesData(result.get(), bytesSeq, sizes, format, stride);
            }
            return result;
        }), py::arg("bytes"), py::arg("sizes"), py::arg("format") = PixelFormat::eUnknown, py::arg("stride") = -1,
        "doc")
        .def(
            "set_data",
            [](ByteImageProvider* self, const std::vector<uint8_t>& bytes, const std::vector<uint32_t>& sizes) {
                OMNIUI_LOG_WARN(
                    "ByteImageProvider.set_data is a deprecated function and will be removed in a future release.\n Please move to using ByteImageProvider.set_bytes_data instead.");
                self->setBytesData(bytes.data(), { sizes[0], sizes[1] });
            },
            "[DEPRECATED FUNCTION]")
        .def(
            "set_data_array",
            [](ByteImageProvider* self, py::array_t<uint8_t>& bytes, const std::vector<uint32_t>& sizes) {
                py::buffer_info bytes_buf = bytes.request();
                self->setBytesData(static_cast<uint8_t *>(bytes_buf.ptr), { sizes[0], sizes[1] });
            })
        .def("set_bytes_data", &_setBytesData,
             "Sets Python sequence as byte data. The image provider will recognize flattened color values, or sequence within sequence and convert it into an image.",
             py::arg("bytes"), py::arg("sizes"), py::arg("format") = PixelFormat::eUnknown, py::arg("stride") = -1)
        .def(
            "set_raw_bytes_data",
            [](ByteImageProvider* self, const void* rawBytes, const std::vector<uint32_t>& sizes, PixelFormat format,
               int stride) {
                self->setBytesData((const uint8_t*)rawBytes, { sizes[0], sizes[1] }, stride, format);
            },
            "Sets byte data that the image provider will turn raw pointer array into an image.", py::arg("raw_bytes"),
            py::arg("sizes"), py::arg("format") = PixelFormat::eRGBA8_UNORM, py::arg("stride") = -1)
        .def(
            "set_bytes_data_from_gpu",
            [](ByteImageProvider* self, uint64_t gpuBytes, const std::vector<uint32_t>& sizes, PixelFormat format,
               int stride) {
                self->setBytesDataFromGPU((const uint8_t*)gpuBytes, { sizes[0], sizes[1] }, stride, format);
            },
            "Sets byte data from a copy of gpu memory at gpuBytes.", py::arg("gpu_bytes"),
            py::arg("sizes"), py::arg("format") = PixelFormat::eRGBA8_UNORM, py::arg("stride") = -1)

        /**/;
}
