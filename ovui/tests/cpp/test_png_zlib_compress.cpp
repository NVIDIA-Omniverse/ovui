/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * PNG export compresses with pngZlibCompress (standalone/src/PngZlibCompress.cpp)
 * instead of stb_image_write's built-in compressor. It must write the same
 * bytes, so exported PNG files stay byte-identical.
 *
 * This test compares both compressors byte for byte. The reference is stb's
 * compressor from the pinned stb in third_party, compiled here without the
 * STBIW_ZLIB_COMPRESS hook. The inputs reach the places where a compressor
 * goes wrong: tiny sizes and the last bytes of the buffer, the 258-byte match
 * limit, the 32K window, hash-chain trimming, lazy matching, the stored-block
 * fallback and the Adler-32 block size. No GPU, window or file is involved.
 *
 * It also checks that PNG export is faster: the stb_image_write that export
 * uses (compiled in PngZlibCompress.cpp) compresses a screenshot-like frame in
 * clearly less time than stb's own compressor.
 *
 * Speed must not be bought with memory. The last check counts the bytes each
 * compressor asks the allocator for, and the export one must never hold more
 * at once than stb does.
 */

// stb's compressor is renamed here, so that the export one can be called too.
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STB_IMAGE_WRITE_STATIC
#define stbi_zlib_compress stbZlibCompress
#include <stb_image_write.h>
#undef stbi_zlib_compress

#include "../../standalone/src/PngZlibCompress.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

using omni::ui::standalone::pngZlibCompress;

// The compressor that the export PNG writer calls.
extern "C" unsigned char* stbi_zlib_compress(unsigned char* data, int dataLen, int* outLen, int quality);

#if defined(OMNIUI_PNG_TEST_COUNT_ALLOCATIONS)

// Counts the heap bytes a compressor holds at once. malloc is wrapped at link
// time (see ovui/CMakeLists.txt) and new is replaced below, so a compressor is
// measured the same way whichever of the two it uses. Only the calls made
// while counting is on are counted, and only a compressor runs then.
#include <malloc.h>
#include <new>

extern "C" void* __real_malloc(size_t size);
extern "C" void* __real_calloc(size_t count, size_t size);
extern "C" void* __real_realloc(void* pointer, size_t size);
extern "C" void __real_free(void* pointer);

namespace
{
bool g_counting = false;
long long g_heldBytes = 0;
long long g_peakBytes = 0;

void countAllocated(void* pointer)
{
    if (!g_counting || !pointer)
        return;
    g_heldBytes += static_cast<long long>(malloc_usable_size(pointer));
    if (g_heldBytes > g_peakBytes)
        g_peakBytes = g_heldBytes;
}

void countFreed(void* pointer)
{
    if (!g_counting || !pointer)
        return;
    g_heldBytes -= static_cast<long long>(malloc_usable_size(pointer));
}
} // namespace

extern "C" void* __wrap_malloc(size_t size)
{
    void* pointer = __real_malloc(size);
    countAllocated(pointer);
    return pointer;
}

extern "C" void* __wrap_calloc(size_t count, size_t size)
{
    void* pointer = __real_calloc(count, size);
    countAllocated(pointer);
    return pointer;
}

extern "C" void* __wrap_realloc(void* pointer, size_t size)
{
    countFreed(pointer);
    void* grown = __real_realloc(pointer, size);
    if (!grown)
        countAllocated(pointer); // the old block is still held
    countAllocated(grown);
    return grown;
}

extern "C" void __wrap_free(void* pointer)
{
    countFreed(pointer);
    __real_free(pointer);
}

// The library allocates new with its own malloc, which --wrap does not reach,
// so new is replaced for the whole program here.
void* operator new(size_t size)
{
    void* pointer = __real_malloc(size ? size : 1);
    if (!pointer)
        throw std::bad_alloc();
    countAllocated(pointer);
    return pointer;
}

void* operator new[](size_t size)
{
    return operator new(size);
}

void operator delete(void* pointer) noexcept
{
    countFreed(pointer);
    __real_free(pointer);
}

void operator delete[](void* pointer) noexcept
{
    operator delete(pointer);
}

void operator delete(void* pointer, size_t) noexcept
{
    operator delete(pointer);
}

void operator delete[](void* pointer, size_t) noexcept
{
    operator delete(pointer);
}

#endif // OMNIUI_PNG_TEST_COUNT_ALLOCATIONS

namespace
{

using Bytes = std::vector<unsigned char>;

int g_totalChecks = 0;
int g_failedChecks = 0;

// Deterministic on every platform (std distributions are not).
struct Lcg
{
    uint32_t state;
    uint32_t next()
    {
        state = state * 1664525u + 1013904223u;
        return state >> 8;
    }
};

void compareCompressors(const std::string& name, const Bytes& data, int quality)
{
    ++g_totalChecks;
    unsigned char* input = const_cast<unsigned char*>(data.data());
    const int length = static_cast<int>(data.size());
    int expectedLength = 0;
    int actualLength = 0;
    unsigned char* expected = stbZlibCompress(input, length, &expectedLength, quality);
    unsigned char* actual = pngZlibCompress(input, length, &actualLength, quality);

    std::string failure;
    if (!expected || !actual)
        failure = "a compressor returned null";
    else if (expectedLength != actualLength)
        failure = "length " + std::to_string(actualLength) + ", stb " + std::to_string(expectedLength);
    else
    {
        for (int i = 0; i < expectedLength; ++i)
        {
            if (expected[i] != actual[i])
            {
                failure = "first different byte at " + std::to_string(i) + " of " + std::to_string(expectedLength);
                break;
            }
        }
    }
    std::free(expected);
    std::free(actual);

    if (!failure.empty())
    {
        ++g_failedChecks;
        std::cout << "[FAIL] " << name << " (" << length << " bytes, quality " << quality << "): " << failure
                  << std::endl;
    }
}

void compareAtQualities(const std::string& name, const Bytes& data)
{
    for (int quality : { 1, 5, 8, 12, 31 })
        compareCompressors(name, data, quality);
}

Bytes randomBytes(size_t length, uint32_t seed, uint32_t alphabet = 256)
{
    Lcg rng{ seed };
    Bytes data(length);
    for (auto& byte : data)
        byte = static_cast<unsigned char>(rng.next() % alphabet);
    return data;
}

// Every size up to 300 bytes, in several kinds of content: the main loop stops
// three bytes before the end, and the tail is written as literals.
void tinyAndOddSizes()
{
    for (size_t length = 0; length <= 300; ++length)
    {
        compareCompressors("zeros", Bytes(length, 0), 8);
        compareCompressors("random", randomBytes(length, 7 + static_cast<uint32_t>(length)), 8);
        compareCompressors("three symbols", randomBytes(length, 11 + static_cast<uint32_t>(length), 3), 8);
        Bytes text(length);
        for (size_t i = 0; i < length; ++i)
            text[i] = "abcabdabcabe"[i % 12];
        compareCompressors("short period", text, 8);
    }
}

// A match is at most 258 bytes and ends at the first difference or at the
// end of the input. Put the difference at every offset around those limits,
// with unaligned starts.
void matchLengthLimits()
{
    const Bytes block = randomBytes(300, 21);
    for (int differAt = 0; differAt <= 270; ++differAt)
    {
        for (int shift : { 0, 1, 3, 7 })
        {
            Bytes data(static_cast<size_t>(shift), 0x55);
            data.insert(data.end(), block.begin(), block.end());
            Bytes copy = block;
            if (differAt < static_cast<int>(copy.size()))
                copy[static_cast<size_t>(differAt)] ^= 0x80;
            data.insert(data.end(), copy.begin(), copy.end());
            compareCompressors("match differs at " + std::to_string(differAt), data, 8);
        }
    }
    // A repeat that runs into the end of the buffer at every length.
    for (int tail = 0; tail <= 266; ++tail)
    {
        Bytes data = block;
        data.insert(data.end(), block.begin(), block.begin() + tail);
        compareCompressors("repeat ends the buffer", data, 8);
    }
    // Long runs: whole and partial 258-byte matches.
    for (size_t length : { 258u, 259u, 260u, 261u, 516u, 517u, 774u, 4096u, 100000u })
    {
        compareCompressors("run of one byte", Bytes(length, 0xff), 8);
        Bytes pair(length);
        for (size_t i = 0; i < length; ++i)
            pair[i] = static_cast<unsigned char>(i & 1);
        compareCompressors("run of two bytes", pair, 8);
    }
}

// A match may reach back at most 32767 bytes, both for the current position
// and for the lazy check of the next one. Repeat a block at distances around
// that limit.
void windowLimits()
{
    const Bytes block = randomBytes(64, 31);
    for (int distance = 32760; distance <= 32772; ++distance)
    {
        const size_t first = 2000;
        const size_t second = first + static_cast<size_t>(distance);
        Bytes data = randomBytes(second + 200, 41 + static_cast<uint32_t>(distance), 251);
        std::memcpy(data.data() + first, block.data(), block.size());
        std::memcpy(data.data() + second, block.data(), block.size());
        compareCompressors("repeat at distance " + std::to_string(distance), data, 8);

        // The byte before the second copy starts a 3-byte match 1000 bytes
        // back, so the long match is only found by the lazy check.
        const size_t current = second - 1;
        data[current - 1000] = data[current];
        data[current - 999] = block[0];
        data[current - 998] = block[1];
        data[current - 997] = static_cast<unsigned char>(block[2] ^ 0x80);
        compareCompressors("lazy repeat at distance " + std::to_string(distance), data, 8);
    }
}

// Inputs where many positions share a hash: chains fill up and are trimmed,
// and the next byte often starts a longer match (lazy matching).
void hashChainsAndLazyMatches()
{
    for (uint32_t alphabet : { 2u, 3u, 4u, 16u })
        compareAtQualities("alphabet of " + std::to_string(alphabet), randomBytes(40000, 51 + alphabet, alphabet));

    // Many copies of a prefix with different endings: every new position
    // finds many candidates, and a longer match starts one byte later.
    Lcg rng{ 61 };
    Bytes data;
    while (data.size() < 60000)
    {
        static const char prefix[] = "abcdefgh";
        const size_t keep = 2 + rng.next() % 7;
        data.insert(data.end(), prefix, prefix + keep);
        data.push_back(static_cast<unsigned char>('0' + rng.next() % 10));
        if (rng.next() % 3 == 0)
            data.insert(data.end(), prefix + 1, prefix + 1 + keep);
    }
    compareAtQualities("prefixes with different endings", data);

    // Sparse edits in a repeated pattern.
    Bytes edited(70000);
    for (size_t i = 0; i < edited.size(); ++i)
        edited[i] = static_cast<unsigned char>(i % 97);
    for (size_t i = 0; i < edited.size(); i += 1 + rng.next() % 300)
        edited[i] = static_cast<unsigned char>(rng.next());
    compareAtQualities("repeated pattern with edits", edited);
}

// Data that does not compress is stored in blocks of at most 32767 bytes.
// The Adler-32 checksum is summed in blocks of 5552 bytes.
void storedBlocksAndChecksum()
{
    for (size_t length : { 5551u, 5552u, 5553u, 11104u, 32766u, 32767u, 32768u, 65533u, 65534u, 65535u, 98302u })
        compareCompressors("incompressible", randomBytes(length, 71 + static_cast<uint32_t>(length)), 8);
    for (size_t length : { 5552u, 11105u, 65535u })
        compareCompressors("all 0xff", Bytes(length, 0xff), 8);
}

// PNG filtered rows of an image like a UI screenshot: flat areas, gradients,
// thin lines and some noise, in both RGB and RGBA.
void screenshotLikeRows()
{
    for (int channels : { 3, 4 })
    {
        const int width = 333;
        const int height = 120;
        Lcg rng{ 81 + static_cast<uint32_t>(channels) };
        Bytes rows;
        for (int y = 0; y < height; ++y)
        {
            rows.push_back(static_cast<unsigned char>(y % 5)); // filter type byte
            for (int x = 0; x < width; ++x)
            {
                for (int c = 0; c < channels; ++c)
                {
                    unsigned char value = 0;
                    if (y % 40 < 20 && x > 50 && x < 280)
                        value = static_cast<unsigned char>(x * (c + 1));
                    else if (x % 37 == 0 || y % 23 == 0)
                        value = 0xe0;
                    if (rng.next() % 64 == 0)
                        value = static_cast<unsigned char>(rng.next());
                    rows.push_back(value);
                }
            }
        }
        compareAtQualities("screenshot-like rows, " + std::to_string(channels) + " channels", rows);
    }
}

// A frame like a UI screenshot: a window background, a gradient panel, borders
// and buttons.
Bytes screenshotFrame(int width, int height)
{
    Bytes frame(static_cast<size_t>(width) * height * 4);
    for (int y = 0; y < height; ++y)
    {
        for (int x = 0; x < width; ++x)
        {
            unsigned char value = 0x30; // window background
            if (x > 200 && y > 40 && y < 500)
                value = static_cast<unsigned char>(0x40 + y / 8); // gradient panel
            if (x % 240 == 0 || y % 120 == 0)
                value = 0x60; // borders
            if (y % 30 > 8 && y % 30 < 22 && x % 240 > 20 && x % 240 < 90)
                value = 0x80; // buttons
            unsigned char* pixel = &frame[(static_cast<size_t>(y) * width + x) * 4];
            pixel[0] = value;
            pixel[1] = value;
            pixel[2] = static_cast<unsigned char>(value + 8);
            pixel[3] = 0xff;
        }
    }
    return frame;
}

// stb measures match lengths one byte at a time. That loop took most of the
// PNG export time, and pngZlibCompress removes most of it. Compress a frame
// like a UI screenshot with the export compressor and with stb's, alternating,
// and compare the medians. Only the compressor is timed: the PNG row filter is
// the same in both and, in the unoptimized ASan build, takes much of the time.
bool exportIsFasterThanStb()
{
    Bytes frame = screenshotFrame(960, 540);

    std::vector<double> exportTimes;
    std::vector<double> stbTimes;
    for (int round = 0; round < 7; ++round)
    {
        int length = 0;
        const auto start = std::chrono::steady_clock::now();
        std::free(stbi_zlib_compress(frame.data(), static_cast<int>(frame.size()), &length, 8));
        const auto middle = std::chrono::steady_clock::now();
        std::free(stbZlibCompress(frame.data(), static_cast<int>(frame.size()), &length, 8));
        const auto end = std::chrono::steady_clock::now();
        exportTimes.push_back(std::chrono::duration<double, std::milli>(middle - start).count());
        stbTimes.push_back(std::chrono::duration<double, std::milli>(end - middle).count());
    }

    std::sort(exportTimes.begin(), exportTimes.end());
    std::sort(stbTimes.begin(), stbTimes.end());
    const double exportMs = exportTimes[exportTimes.size() / 2];
    const double stbMs = stbTimes[stbTimes.size() / 2];
    std::cout << "export compressor " << exportMs << " ms, stb " << stbMs << " ms, ratio " << exportMs / stbMs
              << std::endl;
    if (exportMs <= 0.75 * stbMs)
        return true;
    std::cout << "[FAIL] the export compressor takes more than 0.75 of stb's time" << std::endl;
    return false;
}

// A fast compressor must not be a hungry one. PNG export may not hold more
// heap at once than stb's compressor holds for the same input: that is what
// an export costs today, and it must not grow.
#if defined(OMNIUI_PNG_TEST_COUNT_ALLOCATIONS)

using Compressor = unsigned char* (*)(unsigned char*, int, int*, int);

long long peakBytes(Compressor compress, Bytes& data)
{
    int length = 0;
    g_heldBytes = 0;
    g_peakBytes = 0;
    g_counting = true;
    unsigned char* result = compress(data.data(), static_cast<int>(data.size()), &length, 8);
    g_counting = false;
    const long long peak = g_peakBytes;
    std::free(result);
    return peak;
}

bool memoryStaysWithinStb()
{
    Bytes flat(static_cast<size_t>(640) * 360 * 4, 0x30); // a window background
    std::vector<std::pair<std::string, Bytes>> inputs;
    inputs.emplace_back("eight bytes", Bytes{ 'a', 'b', 'c', 'a', 'b', 'c', 'a', 'b' });
    inputs.emplace_back("flat frame", flat);
    inputs.emplace_back("screenshot-like frame", screenshotFrame(640, 360));
    inputs.emplace_back("noise, which does not compress", randomBytes(300000, 5));

    bool withinStb = true;
    for (auto& input : inputs)
    {
        const long long stbPeak = peakBytes(stbZlibCompress, input.second);
        const long long exportPeak = peakBytes(stbi_zlib_compress, input.second);
        std::cout << input.first << ": export compressor holds " << exportPeak << " bytes at once, stb " << stbPeak
                  << std::endl;
        if (exportPeak > stbPeak)
        {
            std::cout << "[FAIL] the export compressor holds more than stb for " << input.first << std::endl;
            withinStb = false;
        }
    }
    return withinStb;
}

#else

bool memoryStaysWithinStb()
{
    std::cout << "memory is not counted here: the check needs the wrapped allocator of the Linux test build"
              << std::endl;
    return true;
}

#endif // OMNIUI_PNG_TEST_COUNT_ALLOCATIONS

} // namespace

int main()
{
    tinyAndOddSizes();
    matchLengthLimits();
    windowLimits();
    hashChainsAndLazyMatches();
    storedBlocksAndChecksum();
    screenshotLikeRows();
    const bool faster = exportIsFasterThanStb();
    const bool withinStbMemory = memoryStaysWithinStb();

    std::cout << (g_totalChecks - g_failedChecks) << "/" << g_totalChecks
              << " inputs compress to the same bytes as stb" << std::endl;
    return g_failedChecks == 0 && faster && withinStbMemory ? 0 : 1;
}
