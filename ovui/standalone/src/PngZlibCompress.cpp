/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// The compressor follows stbi_zlib_compress from stb_image_write.h
// (nothings/stb, public domain / MIT): the same hash, hash chains, lazy
// matching, fixed Huffman codes and stored-block fallback. Any change here
// must keep its output byte for byte.
//
// It also keeps stb's memory shape, so an export never holds more bytes than
// stb does: a hash chain is allocated when its hash is first seen and grows
// only as far as it fills, the compressed bytes grow by doubling, and the
// caller is handed those same bytes instead of a second copy.

#include "PngZlibCompress.h"

#include <climits>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#if defined(_MSC_VER)
#include <intrin.h>
#endif

namespace omni {
namespace ui {
namespace standalone {

namespace {

constexpr int kHashSize = 16384;
constexpr int kMaxMatch = 258;
constexpr int kWindow = 32768;

int firstDifferentByte(uint64_t diff)
{
#if defined(_MSC_VER)
    unsigned long bit = 0;
    _BitScanForward64(&bit, diff);
    return static_cast<int>(bit >> 3);
#elif defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    return __builtin_clzll(diff) >> 3;
#else
    return __builtin_ctzll(diff) >> 3;
#endif
}

// Same result as stbiw__zlib_countm: the number of equal leading bytes, at
// most min(limit, 258).
int matchLength(const unsigned char* a, const unsigned char* b, int limit)
{
    const int n = limit < kMaxMatch ? limit : kMaxMatch;
    int i = 0;
    for (; i + 8 <= n; i += 8)
    {
        uint64_t x;
        uint64_t y;
        std::memcpy(&x, a + i, 8);
        std::memcpy(&y, b + i, 8);
        if (const uint64_t diff = x ^ y)
            return i + firstDifferentByte(diff);
    }
    while (i < n && a[i] == b[i])
        ++i;
    return i;
}

uint32_t zhash(const unsigned char* data)
{
    uint32_t hash = data[0] + (data[1] << 8) + (data[2] << 16);
    hash ^= hash << 3;
    hash += hash >> 5;
    hash ^= hash << 4;
    hash += hash >> 17;
    hash ^= hash << 25;
    hash += hash >> 6;
    return hash;
}

int bitReverse(int code, int codeBits)
{
    int result = 0;
    while (codeBits--)
    {
        result = (result << 1) | (code & 1);
        code >>= 1;
    }
    return result;
}

// The compressed bytes. They grow in the same steps as stb's stretchy buffer,
// and the caller is handed this same storage trimmed to its size, so the
// bytes are never held twice.
class ByteBuffer
{
public:
    ByteBuffer() = default;
    ByteBuffer(const ByteBuffer&) = delete;
    ByteBuffer& operator=(const ByteBuffer&) = delete;

    ~ByteBuffer()
    {
        std::free(m_data);
    }

    bool failed() const
    {
        return m_failed;
    }

    int size() const
    {
        return m_size;
    }

    void push(unsigned char value)
    {
        if (m_size == m_capacity && !grow(1))
            return;
        m_data[m_size++] = value;
    }

    void append(const unsigned char* bytes, int count)
    {
        if (m_capacity - m_size < count && !grow(count))
            return;
        std::memcpy(m_data + m_size, bytes, static_cast<size_t>(count));
        m_size += count;
    }

    void truncate(int size)
    {
        m_size = size;
    }

    // Gives the bytes to the caller, trimmed to their exact size. The caller
    // frees them, as stb_image_write does.
    unsigned char* release()
    {
        if (m_failed)
            return nullptr;
        unsigned char* bytes = m_data;
        if (m_size > 0 && m_size < m_capacity)
        {
            if (auto* trimmed = static_cast<unsigned char*>(std::realloc(bytes, static_cast<size_t>(m_size))))
                bytes = trimmed;
        }
        m_data = nullptr;
        m_size = 0;
        m_capacity = 0;
        return bytes;
    }

private:
    bool grow(int extra)
    {
        if (m_failed)
            return false;
        const long long needed = static_cast<long long>(m_size) + extra;
        if (needed > INT_MAX)
        {
            m_failed = true;
            return false;
        }
        long long capacity = m_capacity;
        do
        {
            capacity = capacity ? 2 * capacity + extra : extra + 1; // stb's steps
        } while (capacity < needed);
        if (capacity > INT_MAX)
            capacity = INT_MAX;
        auto* grown = static_cast<unsigned char*>(std::realloc(m_data, static_cast<size_t>(capacity)));
        if (!grown)
        {
            m_failed = true;
            return false;
        }
        m_data = grown;
        m_capacity = static_cast<int>(capacity);
        return true;
    }

    unsigned char* m_data = nullptr;
    int m_size = 0;
    int m_capacity = 0;
    bool m_failed = false;
};

// One chain per hash value: the positions whose next three bytes hash the
// same, oldest first. A chain is allocated when its hash is first seen and
// holds at most 2 * quality positions, as in stb. stb keeps pointers; a
// position is half their size. The first two ints of a chain are its length
// and its capacity.
class HashChains
{
public:
    explicit HashChains(int maxLength) : m_maxLength(maxLength)
    {
        m_table = static_cast<int**>(std::calloc(kHashSize, sizeof(int*)));
    }

    HashChains(const HashChains&) = delete;
    HashChains& operator=(const HashChains&) = delete;

    ~HashChains()
    {
        clear();
    }

    bool valid() const
    {
        return m_table != nullptr;
    }

    // The chains are not needed once the matches are found. stb frees them at
    // the same place, before the output grows any further.
    void clear()
    {
        if (!m_table)
            return;
        for (int h = 0; h < kHashSize; ++h)
            std::free(m_table[h]);
        std::free(m_table);
        m_table = nullptr;
    }

    int length(int h) const
    {
        return m_table[h] ? m_table[h][0] : 0;
    }

    // Oldest first. Only the first length(h) entries are positions.
    const int* positions(int h) const
    {
        return m_table[h] ? m_table[h] + kChainHeader : nullptr;
    }

    bool add(int h, int position)
    {
        int* chain = m_table[h];
        int length = chain ? chain[0] : 0;
        const int capacity = chain ? chain[1] : 0;
        if (length == m_maxLength)
        {
            // The chain is full: drop the older half, as stb does.
            const int keep = m_maxLength / 2;
            std::memmove(chain + kChainHeader, chain + kChainHeader + (m_maxLength - keep), sizeof(int) * keep);
            length = keep;
        }
        else if (length == capacity)
        {
            int grown = capacity ? capacity * 2 : 2;
            if (grown > m_maxLength)
                grown = m_maxLength;
            auto* resized = static_cast<int*>(std::realloc(chain, sizeof(int) * (kChainHeader + grown)));
            if (!resized)
                return false;
            chain = resized;
            chain[1] = grown;
            m_table[h] = chain;
        }
        chain[0] = length + 1;
        chain[kChainHeader + length] = position;
        return true;
    }

private:
    static constexpr int kChainHeader = 2; // length, capacity

    int** m_table = nullptr;
    int m_maxLength = 0;
};

class BitWriter
{
public:
    explicit BitWriter(ByteBuffer& out) : m_out(out)
    {
    }

    void add(unsigned int code, int codeBits)
    {
        m_bits |= code << m_count;
        m_count += codeBits;
        while (m_count >= 8)
        {
            m_out.push(static_cast<unsigned char>(m_bits));
            m_bits >>= 8;
            m_count -= 8;
        }
    }

    // Fixed Huffman code of a literal/length symbol.
    void symbol(int n)
    {
        if (n <= 143)
            huffman(0x30 + n, 8);
        else if (n <= 255)
            huffman(0x190 + n - 144, 9);
        else if (n <= 279)
            huffman(n - 256, 7);
        else
            huffman(0xc0 + n - 280, 8);
    }

    void padToByte()
    {
        while (m_count)
            add(0, 1);
    }

private:
    void huffman(int code, int codeBits)
    {
        add(bitReverse(code, codeBits), codeBits);
    }

    ByteBuffer& m_out;
    unsigned int m_bits = 0;
    int m_count = 0;
};

} // namespace

unsigned char* pngZlibCompress(unsigned char* data, int dataLen, int* outLen, int quality)
{
    static const unsigned short lengthc[] = { 3,  4,  5,  6,  7,  8,  9,  10, 11,  13,  15,  17,  19,  23,  27,
                                              31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258, 259 };
    static const unsigned char lengtheb[] = { 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                                              2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0 };
    static const unsigned short distc[] = { 1,    2,    3,    4,    5,    7,     9,     13,    17,    25,   33,
                                            49,   65,   97,   129,  193,  257,   385,   513,   769,   1025, 1537,
                                            2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577, 32768 };
    static const unsigned char disteb[] = { 0, 0, 0, 0, 1, 1, 2, 2,  3,  3,  4,  4,  5,  5,  6,
                                            6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13 };
    if (quality < 5)
        quality = 5;

    // Each hash chain keeps at most 2 * quality positions, oldest first. When
    // a chain is full, the older half is dropped before the next position is
    // added, as in stb.
    HashChains chains(2 * quality);
    if (!chains.valid())
        return nullptr;

    ByteBuffer out;
    out.push(0x78); // DEFLATE 32K window
    out.push(0x5e); // FLEVEL = 1
    BitWriter bits(out);
    bits.add(1, 1); // BFINAL = 1
    bits.add(1, 2); // BTYPE = 1 -- fixed Huffman

    int i = 0;
    while (i < dataLen - 3)
    {
        int h = static_cast<int>(zhash(data + i) & (kHashSize - 1));
        int best = 3;
        int bestPos = -1;
        int n = chains.length(h);
        const int* chain = chains.positions(h);
        for (int j = 0; j < n; ++j)
        {
            if (chain[j] > i - kWindow)
            {
                const int d = matchLength(data + chain[j], data + i, dataLen - i);
                if (d >= best)
                {
                    best = d;
                    bestPos = chain[j];
                }
            }
        }
        if (!chains.add(h, i))
            return nullptr;

        if (bestPos >= 0)
        {
            // Lazy matching: emit a literal if the next byte starts a longer match.
            h = static_cast<int>(zhash(data + i + 1) & (kHashSize - 1));
            n = chains.length(h);
            chain = chains.positions(h);
            for (int j = 0; j < n; ++j)
            {
                if (chain[j] > i - (kWindow - 1))
                {
                    const int e = matchLength(data + chain[j], data + i + 1, dataLen - i - 1);
                    if (e > best)
                    {
                        bestPos = -1;
                        break;
                    }
                }
            }
        }

        if (bestPos >= 0)
        {
            const int d = i - bestPos; // distance back
            int j = 0;
            for (j = 0; best > lengthc[j + 1] - 1; ++j)
                ;
            bits.symbol(j + 257);
            if (lengtheb[j])
                bits.add(best - lengthc[j], lengtheb[j]);
            for (j = 0; d > distc[j + 1] - 1; ++j)
                ;
            bits.add(bitReverse(j, 5), 5);
            if (disteb[j])
                bits.add(d - distc[j], disteb[j]);
            i += best;
        }
        else
        {
            bits.symbol(data[i]);
            ++i;
        }
    }
    for (; i < dataLen; ++i)
        bits.symbol(data[i]);
    bits.symbol(256); // end of block
    bits.padToByte();
    chains.clear();

    // Store the data uncompressed if compression made it larger.
    if (out.size() > dataLen + 2 + ((dataLen + 32766) / 32767) * 5)
    {
        out.truncate(2);
        for (int j = 0; j < dataLen;)
        {
            int blockLen = dataLen - j;
            if (blockLen > 32767)
                blockLen = 32767;
            out.push(dataLen - j == blockLen); // BFINAL = ?, BTYPE = 0 -- stored
            out.push(static_cast<unsigned char>(blockLen));
            out.push(static_cast<unsigned char>(blockLen >> 8));
            out.push(static_cast<unsigned char>(~blockLen));
            out.push(static_cast<unsigned char>(~blockLen >> 8));
            out.append(data + j, blockLen);
            j += blockLen;
        }
    }

    // Adler-32 of the input.
    unsigned int s1 = 1;
    unsigned int s2 = 0;
    int blockLen = dataLen % 5552;
    for (int j = 0; j < dataLen;)
    {
        for (int k = 0; k < blockLen; ++k)
        {
            s1 += data[j + k];
            s2 += s1;
        }
        s1 %= 65521;
        s2 %= 65521;
        j += blockLen;
        blockLen = 5552;
    }
    out.push(static_cast<unsigned char>(s2 >> 8));
    out.push(static_cast<unsigned char>(s2));
    out.push(static_cast<unsigned char>(s1 >> 8));
    out.push(static_cast<unsigned char>(s1));

    // Out of memory anywhere above: report the failure as stb's compressor
    // does, with no result.
    const int length = out.size();
    unsigned char* result = out.release();
    if (!result)
        return nullptr;
    *outLen = length;
    return result;
}

} // namespace standalone
} // namespace ui
} // namespace omni

// The stb_image_write that PNG, JPG and BMP export use, with pngZlibCompress
// as its PNG compressor. It is compiled here, not in StandaloneInit.cpp, so
// that the native test can reach it without the rest of the backend.
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBIW_ZLIB_COMPRESS omni::ui::standalone::pngZlibCompress
#include <stb_image_write.h>
