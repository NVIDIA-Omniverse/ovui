/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Sharing contract of the standalone raster image loader.
 *
 * Several consumers can show the same image file at once: two preview windows
 * on one asset, a provider and a plain ui.Image on one path. The loader decodes
 * and uploads that file once and shares it. Two things must both hold:
 *
 *   - losing a consumer must not cost the next one a second decode and upload.
 *     Closing one preview says nothing about the file, so the entry stays
 *     shared and a later preview of the same path reuses it;
 *   - a consumer asking for its URL again is reloading a file that may have
 *     been replaced, so invalidateCacheEntry() must force the next load to read
 *     the file, while consumers still drawing the old entry keep their pixels
 *     until they release them.
 *
 * The loader source is compiled into this test, so no GPU, window or running
 * application is involved: a counting fake IByteImageGpu stands in for the
 * backend and the image is a small BMP written to a temporary file.
 */

#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO
#include <stb_image.h>

#include "../../standalone/src/StandaloneRasterImageLoader.h"

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <set>
#include <string>
#include <vector>

using namespace omni::ui;
using omni::ui::standalone::StandaloneRasterImageLoader;

namespace
{

// ---------------------------------------------------------------------------
// Reporting: collect every failure so one broken branch cannot hide another.
// ---------------------------------------------------------------------------

std::vector<std::string> g_caseFailures;
std::string g_caseName;
int g_failedCases = 0;
int g_totalCases = 0;

void check(bool condition, const std::string& what)
{
    if (!condition)
    {
        g_caseFailures.push_back(what);
    }
}

void beginCase(const char* name)
{
    g_caseName = name;
    g_caseFailures.clear();
    ++g_totalCases;
}

void endCase()
{
    if (g_caseFailures.empty())
    {
        std::cout << "PASS " << g_caseName << std::endl;
        return;
    }
    ++g_failedCases;
    std::cout << "FAIL " << g_caseName << std::endl;
    for (const std::string& failure : g_caseFailures)
    {
        std::cout << "       " << failure << std::endl;
    }
}

// ---------------------------------------------------------------------------
// Fake GPU backend: counts the work a duplicate decode would cost, and refuses
// to destroy a state twice so a use-after-free shows up as a failed case.
// ---------------------------------------------------------------------------

struct CountingGpu : IByteImageGpu
{
    int created = 0;
    int uploaded = 0;
    int destroyed = 0;
    std::set<void*> live;
    bool doubleDestroy = false;

    Handle createState() override
    {
        ++created;
        Handle state = new int(0);
        live.insert(state);
        return state;
    }

    void destroyState(Handle state) override
    {
        ++destroyed;
        if (live.erase(state) == 0)
        {
            doubleDestroy = true;
            return;
        }
        delete static_cast<int*>(state);
    }

    void releaseImage(Handle) override
    {
    }

    UpdateResult updateImage(Handle state, const uint8_t* const*, size_t*, size_t, UInt2,
                             PixelFormat, bool, uint32_t, uint32_t, uint32_t) override
    {
        ++uploaded;
        // A reference the loader can publish; never dereferenced by the test.
        return { state, nullptr };
    }
};

// ---------------------------------------------------------------------------
// A real file on disk, because the loader reads and decodes one.
// ---------------------------------------------------------------------------

void appendLe(std::vector<uint8_t>& out, uint32_t value, size_t bytes)
{
    for (size_t i = 0; i < bytes; ++i)
    {
        out.push_back(static_cast<uint8_t>((value >> (8 * i)) & 0xff));
    }
}

/// Write a 2x2 24-bit BMP. stb_image decodes it without any extra dependency.
void writeTestImage(const std::filesystem::path& path, uint8_t red)
{
    std::vector<uint8_t> pixels;
    for (int row = 0; row < 2; ++row)
    {
        for (int column = 0; column < 2; ++column)
        {
            pixels.push_back(0x20);               // blue
            pixels.push_back(0x40);               // green
            pixels.push_back(red);                // red
        }
        pixels.push_back(0); // row padding to a 4-byte boundary
        pixels.push_back(0);
    }

    std::vector<uint8_t> bytes{ 'B', 'M' };
    appendLe(bytes, static_cast<uint32_t>(54 + pixels.size()), 4); // file size
    appendLe(bytes, 0, 4); // reserved
    appendLe(bytes, 54, 4); // pixel data offset
    appendLe(bytes, 40, 4); // DIB header size
    appendLe(bytes, 2, 4); // width
    appendLe(bytes, 2, 4); // height
    appendLe(bytes, 1, 2); // planes
    appendLe(bytes, 24, 2); // bits per pixel
    appendLe(bytes, 0, 4); // no compression
    appendLe(bytes, static_cast<uint32_t>(pixels.size()), 4);
    appendLe(bytes, 2835, 4); // horizontal resolution
    appendLe(bytes, 2835, 4); // vertical resolution
    appendLe(bytes, 0, 4); // palette colours
    appendLe(bytes, 0, 4); // important colours
    bytes.insert(bytes.end(), pixels.begin(), pixels.end());

    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

/// Opaque per-consumer keys. The loader only compares them.
int g_consumerA = 0, g_consumerB = 0, g_consumerC = 0;
void* const kConsumerA = &g_consumerA;
void* const kConsumerB = &g_consumerB;
void* const kConsumerC = &g_consumerC;

/// What a RasterImageProvider does when it is destroyed: it gives its load and
/// its reference back, and says nothing about the file.
void releaseConsumer(StandaloneRasterImageLoader& loader, void* consumer, const std::string& url)
{
    loader.releaseLoad(consumer);
    loader.releaseGpuResource(url);
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

/// Two previews of one file, close one, open another: the surviving entry must
/// still be shared, so the new preview costs no second decode and upload.
void caseClosingOneConsumerKeepsTheSharedEntry(const std::string& url, CountingGpu& gpu)
{
    beginCase("closing_one_consumer_keeps_the_shared_entry");
    StandaloneRasterImageLoader loader;

    auto first = loader.beginLoad(kConsumerA, url);
    auto second = loader.beginLoad(kConsumerB, url);
    check(first.status == IRasterImageLoader::LoadResult::eCached, "the first consumer must load the file");
    check(second.status == IRasterImageLoader::LoadResult::eCached, "the second consumer must share the file");
    check(gpu.uploaded == 1, "two consumers of one unchanged file must share one upload");
    const int uploadsWhileShared = gpu.uploaded;

    releaseConsumer(loader, kConsumerB, url);
    check(gpu.destroyed == 0, "a consumer leaving must not destroy a texture another one draws");

    auto third = loader.beginLoad(kConsumerC, url);
    check(third.status == IRasterImageLoader::LoadResult::eCached, "the next consumer must load the file");
    check(gpu.uploaded == uploadsWhileShared,
          "a consumer closing must not make the next consumer of the same unchanged file decode a second copy");
    check(third.imGuiReference == first.imGuiReference,
          "the next consumer must be given the texture the surviving consumer is drawing");

    // No leak: the entry goes away with its last consumer.
    releaseConsumer(loader, kConsumerA, url);
    check(gpu.destroyed == 0, "the entry must survive while one consumer still holds it");
    releaseConsumer(loader, kConsumerC, url);
    check(gpu.destroyed == gpu.created, "the last consumer leaving must destroy every allocated texture");
    check(gpu.live.empty(), "no texture may be left allocated");
    check(!gpu.doubleDestroy, "no texture may be destroyed twice");
    endCase();
}

/// Reloading a replaced file still works, and does not disturb a consumer that
/// is drawing the old contents.
void caseInvalidateForcesAFreshDecode(const std::string& url, CountingGpu& gpu)
{
    beginCase("invalidate_forces_a_fresh_decode_and_spares_other_consumers");
    StandaloneRasterImageLoader loader;

    auto peer = loader.beginLoad(kConsumerA, url);
    check(gpu.uploaded == 1, "the first load uploads once");

    // The file was replaced on disk and a consumer asks for the URL again.
    loader.invalidateCacheEntry(url);
    auto reloaded = loader.beginLoad(kConsumerB, url);
    check(reloaded.status == IRasterImageLoader::LoadResult::eCached, "the reload must load the file");
    check(gpu.uploaded == 2, "an invalidated URL must be read from disk again");
    check(reloaded.imGuiReference != peer.imGuiReference, "the reload must publish its own texture");

    auto peerPoll = loader.poll(kConsumerA, ImageProviderTextureOptions{ 0 }, 3);
    check(peerPoll.status == IRasterImageLoader::LoadResult::eReady, "the other consumer must keep its image");
    check(peerPoll.imGuiReference == peer.imGuiReference,
          "a reload by one consumer must not change what another one draws");
    check(gpu.destroyed == 0, "a reload must not destroy a texture another consumer draws");

    releaseConsumer(loader, kConsumerA, url);
    check(gpu.destroyed == 1, "the superseded texture goes with its last consumer");
    releaseConsumer(loader, kConsumerB, url);
    check(gpu.destroyed == gpu.created && gpu.live.empty(), "every texture is released");
    check(!gpu.doubleDestroy, "no texture may be destroyed twice");
    endCase();
}

/// A file that cannot be read is never remembered, so a consumer that comes
/// back after the file appears picks it up.
void caseFailuresAreNotCached(const std::filesystem::path& dir, CountingGpu& gpu)
{
    beginCase("a_failed_load_is_not_remembered");
    const std::string url = (dir / "appears-later.bmp").string();
    std::filesystem::remove(url);
    StandaloneRasterImageLoader loader;

    auto missing = loader.beginLoad(kConsumerA, url);
    check(missing.status == IRasterImageLoader::LoadResult::eFailed, "a missing file must fail");
    check(gpu.uploaded == 0, "a missing file uploads nothing");

    writeTestImage(url, 0xf0);
    auto appeared = loader.beginLoad(kConsumerB, url);
    check(appeared.status == IRasterImageLoader::LoadResult::eCached,
          "a file that appears later must be picked up by the next load");
    check(gpu.uploaded == 1, "the file that appeared is decoded once");

    releaseConsumer(loader, kConsumerA, url);
    releaseConsumer(loader, kConsumerB, url);
    check(gpu.destroyed == gpu.created && gpu.live.empty(), "every texture is released");
    check(!gpu.doubleDestroy, "no texture may be destroyed twice");
    std::filesystem::remove(url);
    endCase();
}

} // namespace

int main()
{
    const std::filesystem::path dir =
        std::filesystem::temp_directory_path() / "ovui_standalone_raster_loader_test";
    std::filesystem::create_directories(dir);
    const std::filesystem::path image = dir / "asset.bmp";
    writeTestImage(image, 0xc0);
    const std::string url = image.string();

    auto fresh = []() {
        auto gpu = std::make_shared<CountingGpu>();
        PlatformRegistry::instance().setByteImageGpu(gpu);
        return gpu;
    };

    auto gpu = fresh();
    caseClosingOneConsumerKeepsTheSharedEntry(url, *gpu);
    gpu = fresh();
    caseInvalidateForcesAFreshDecode(url, *gpu);
    gpu = fresh();
    caseFailuresAreNotCached(dir, *gpu);

    PlatformRegistry::instance().setByteImageGpu(nullptr);
    std::filesystem::remove_all(dir);

    std::cout << "\n" << (g_totalCases - g_failedCases) << "/" << g_totalCases << " cases passed" << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
