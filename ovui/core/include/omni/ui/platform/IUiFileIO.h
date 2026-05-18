/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace omni {
namespace ui {

/// Decoded image data returned by decodeImage().
struct ImageData
{
    std::vector<uint8_t> pixels; ///< Raw pixel data (RGBA, 8 bits per channel).
    int width = 0;               ///< Image width in pixels.
    int height = 0;              ///< Image height in pixels.
    int channels = 0;            ///< Number of channels (e.g. 4 for RGBA).
};

/// Abstract file I/O interface for filesystem access, path token resolution,
/// and image decoding.
///
/// Each backend provides a concrete implementation (e.g. KitFileIOAdapter for
/// Kit, StandaloneFileIO for the standalone backend).
class IUiFileIO
{
public:
    virtual ~IUiFileIO() = default;

    /// Read an entire file into memory. Returns an empty vector on failure.
    virtual std::vector<uint8_t> readFile(const char* path) = 0;

    /// Check whether a file exists at the given path.
    virtual bool fileExists(const char* path) = 0;

    /// Return the last-modified time of a file as a Unix timestamp (seconds since epoch).
    /// Returns 0 if the file does not exist or the time cannot be determined.
    virtual uint64_t getModTime(const char* path) = 0;

    /// Resolve a tokenized path (e.g. "${fonts}/Roboto-Medium.ttf") into an
    /// absolute filesystem path. Returns the input unchanged if no tokens match.
    virtual std::string resolvePath(const char* tokenPath) = 0;

    /// Callback type for async file reads. Called on the main thread with the
    /// file contents (empty vector on failure).
    using ReadFileCallback = std::function<void(std::vector<uint8_t> data)>;

    /// Start an asynchronous file read. The callback will be delivered on the
    /// main thread (via the deferred queue) after the read completes.
    virtual void readFileAsync(const char* path, ReadFileCallback callback) = 0;

    /// Decode an in-memory image (PNG, JPEG, BMP, etc.) into raw pixel data.
    /// Returns a default-constructed ImageData on failure.
    virtual ImageData decodeImage(const uint8_t* data, size_t size) = 0;
};

} // namespace ui
} // namespace omni
