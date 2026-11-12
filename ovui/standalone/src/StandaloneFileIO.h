/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/platform/IUiFileIO.h>

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone IUiFileIO implementation using std::filesystem and stb_image.
/// Supports token resolution (e.g. "${fonts}" -> "resources/fonts/").
class StandaloneFileIO final : public IUiFileIO
{
public:
    StandaloneFileIO();
    ~StandaloneFileIO() override;

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

    // Shared signal of one background read, kept alive by the read thread so
    // the thread never touches this object after it delivers its callback.
    struct ReadSignal
    {
        std::mutex mutex;
        std::condition_variable registered_changed;
        std::condition_variable done_changed;
        // The read is recorded before its thread runs, so a callback that
        // destroys the file IO cannot do so before the record exists.
        bool registered = false;
        bool done = false;
    };

    struct BackgroundRead
    {
        std::thread thread;
        std::shared_ptr<ReadSignal> signal;
        std::string path;  // names the read in a shutdown-timeout report (rule 31.6)
    };

    // Reads started by readFileAsync. The destructor waits for each up to a
    // time limit, then abandons it (rules 13.3, 13.4).
    std::mutex m_readsMutex;
    std::vector<BackgroundRead> m_reads;
};

#ifdef OVUI_FILE_IO_TEST_SEAM
// Test seam (declared only for the file-IO test): arm a one-shot read failure
// so the next background read throws. Not present in the product library.
void failNextReadForTest();
#endif

} // namespace standalone
} // namespace ui
} // namespace omni
