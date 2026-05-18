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

#include <omni/ui/platform/IUiFileIO.h>

#include <mutex>
#include <string>
#include <unordered_map>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone IUiFileIO implementation using std::filesystem and stb_image.
/// Supports token resolution (e.g. "${fonts}" -> "resources/fonts/").
class StandaloneFileIO final : public IUiFileIO
{
public:
    StandaloneFileIO();
    ~StandaloneFileIO() override = default;

    std::vector<uint8_t> readFile(const char* path) override;
    bool fileExists(const char* path) override;
    uint64_t getModTime(const char* path) override;
    std::string resolvePath(const char* tokenPath) override;
    void readFileAsync(const char* path, ReadFileCallback callback) override;
    ImageData decodeImage(const uint8_t* data, size_t size) override;

    /// Register a path token mapping (e.g. "${fonts}" -> "/path/to/fonts/").
    void registerToken(const std::string& token, const std::string& resolvedPath);

private:
    std::mutex m_mutex;
    std::unordered_map<std::string, std::string> m_tokens;
};

} // namespace standalone
} // namespace ui
} // namespace omni
