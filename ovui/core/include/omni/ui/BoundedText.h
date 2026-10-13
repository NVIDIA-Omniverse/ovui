/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace omni::ui::boundedtext
{

constexpr uint32_t kTinyStringMaxSize = 16U;
constexpr uint32_t kLittleStringMaxSize = 32U;
constexpr uint32_t kSmallStringMaxSize = 64U;
constexpr uint32_t kMediumStringMaxSize = 128U;
constexpr uint32_t kRegularStringMaxSize = 256U;
constexpr uint32_t kBigStringMaxSize = 10248U;
constexpr uint32_t kLargeStringMaxSize = 2U * 1024U;
constexpr uint32_t kTextStringMaxSize = 8U * 1024U;

inline uint32_t getTextSize(const char* text, uint32_t maximum = kTextStringMaxSize) noexcept
{
    if (!text)
        return 0;
    uint32_t size = 0;
    while (size < maximum && text[size] != '\0')
        ++size;
    return size;
}

inline uint64_t hashText(const char* text, uint32_t size) noexcept
{
    uint64_t hash = 5381U;
    for (uint32_t index = 0; index < size; ++index)
        hash = ((hash << 5U) + hash) + static_cast<uint8_t>(text[index]);
    return hash;
}

class TextView final
{
public:
    static constexpr size_t npos = static_cast<size_t>(-1);

    TextView() noexcept = default;
    TextView(const char* text) noexcept : m_text(text ? text : ""), m_size(getTextSize(text))
    {
    }
    TextView(const char* text, size_t size) noexcept : m_text(text ? text : ""), m_size(text ? size : 0)
    {
    }

    const char* data() const noexcept
    {
        return m_text;
    }
    size_t size() const noexcept
    {
        return m_size;
    }
    bool empty() const noexcept
    {
        return m_size == 0;
    }
    char front() const noexcept
    {
        return m_text[0];
    }
    char back() const noexcept
    {
        return m_text[m_size - 1];
    }
    char operator[](size_t index) const noexcept
    {
        return m_text[index];
    }
    void removePrefix(size_t count) noexcept
    {
        const size_t removed = (std::min)(count, m_size);
        m_text += removed;
        m_size -= removed;
    }
    void removeSuffix(size_t count) noexcept
    {
        m_size -= (std::min)(count, m_size);
    }
    size_t find(char character, size_t start = 0) const noexcept
    {
        for (size_t index = start; index < m_size; ++index)
            if (m_text[index] == character)
                return index;
        return npos;
    }

    friend bool operator==(TextView lhs, TextView rhs) noexcept
    {
        return lhs.m_size == rhs.m_size && std::memcmp(lhs.m_text, rhs.m_text, lhs.m_size) == 0;
    }
    friend bool operator!=(TextView lhs, TextView rhs) noexcept
    {
        return !(lhs == rhs);
    }

private:
    const char* m_text{ "" };
    size_t m_size{};
};

template <uint32_t Capacity>
class StaticString final
{
public:
    StaticString() noexcept
    {
        clear();
    }

    explicit StaticString(const char* text) noexcept
    {
        clear();
        addText(text, getTextSize(text));
    }

    StaticString(const char* text, uint32_t size) noexcept
    {
        clear();
        addText(text, size);
    }

    const char* text() const noexcept
    {
        return m_buffer;
    }

    uint32_t size() const noexcept
    {
        return m_size;
    }

    constexpr uint32_t maxSize() const noexcept
    {
        return Capacity;
    }

    bool empty() const noexcept
    {
        return m_size == 0;
    }

    void clear() noexcept
    {
        m_size = 0;
        m_buffer[0] = '\0';
    }

    void addText(const char* text, uint32_t size) noexcept
    {
        if (!text || size == 0 || m_size + 1 >= Capacity)
            return;
        const uint32_t copySize = (std::min)(size, Capacity - m_size - 1);
        std::memcpy(m_buffer + m_size, text, copySize);
        m_size += copySize;
        m_buffer[m_size] = '\0';
    }

    template <uint32_t OtherCapacity>
    void addStaticString(const StaticString<OtherCapacity>& other) noexcept
    {
        addText(other.text(), other.size());
    }

    StaticString& operator+=(const char* text) noexcept
    {
        addText(text, getTextSize(text));
        return *this;
    }

    StaticString& operator+=(char value) noexcept
    {
        addText(&value, 1);
        return *this;
    }

    void popBack() noexcept
    {
        if (m_size == 0)
            return;
        m_buffer[--m_size] = '\0';
    }

    char back() const noexcept
    {
        return m_size ? m_buffer[m_size - 1] : '\0';
    }

    uint64_t hash() const noexcept
    {
        return hashText(m_buffer, m_size);
    }

    template <uint32_t OtherCapacity>
    bool operator==(const StaticString<OtherCapacity>& other) const noexcept
    {
        return m_size == other.size() && std::memcmp(m_buffer, other.text(), m_size) == 0;
    }

    template <uint32_t OtherCapacity>
    bool operator<(const StaticString<OtherCapacity>& other) const noexcept
    {
        const uint32_t commonSize = (std::min)(m_size, other.size());
        const int compare = std::memcmp(m_buffer, other.text(), commonSize);
        return compare < 0 || (compare == 0 && m_size < other.size());
    }

private:
    uint32_t m_size{};
    char m_buffer[Capacity]{};
};

using StaticString16 = StaticString<kTinyStringMaxSize>;
using StaticString32 = StaticString<kLittleStringMaxSize>;
using StaticString64 = StaticString<kSmallStringMaxSize>;
using StaticString128 = StaticString<kMediumStringMaxSize>;
using StaticString256 = StaticString<kRegularStringMaxSize>;
using StaticString1024 = StaticString<kBigStringMaxSize>;
using StaticString2048 = StaticString<kLargeStringMaxSize>;
using StaticString8096 = StaticString<kTextStringMaxSize>;

template <uint32_t Capacity>
struct StaticStringHash
{
    size_t operator()(const StaticString<Capacity>& value) const noexcept
    {
        return static_cast<size_t>(value.hash());
    }
};

/** Fixed-buffer stream **/
class TextStream final
{
public:
    TextStream(uint32_t bufferSizeInBytes, char* buffer) noexcept : m_sizeMax(bufferSizeInBytes), m_buffer(buffer)
    {
        clear();
        std::memset(m_convertBuffer, 0, sizeof(m_convertBuffer));
    }

    TextStream(const TextStream&) = delete;
    TextStream(TextStream&&) = delete;
    TextStream& operator=(const TextStream&) = delete;
    TextStream& operator=(TextStream&&) = delete;

    void clear() noexcept
    {
        m_size = 0;
        if (m_buffer && m_sizeMax)
            m_buffer[0] = '\0';
    }

    const char* text() const noexcept
    {
        return m_buffer ? m_buffer : "";
    }

    uint32_t size() const noexcept
    {
        return m_size;
    }

    void addText(const char* text, uint32_t size) noexcept
    {
        append(text, size);
    }

    TextStream& operator<<(const char* text) noexcept
    {
        append(text, getTextSize(text));
        return *this;
    }

    TextStream& operator<<(char value) noexcept
    {
        append(&value, 1);
        return *this;
    }

    TextStream& operator<<(int32_t value) noexcept
    {
        std::snprintf(m_convertBuffer, sizeof(m_convertBuffer), "%d", value);
        return *this << m_convertBuffer;
    }

    TextStream& operator<<(uint32_t value) noexcept
    {
        std::snprintf(m_convertBuffer, sizeof(m_convertBuffer), "%u", value);
        return *this << m_convertBuffer;
    }

    TextStream& operator<<(int64_t value) noexcept
    {
        std::snprintf(m_convertBuffer, sizeof(m_convertBuffer), "%lld", static_cast<long long>(value));
        return *this << m_convertBuffer;
    }

    TextStream& operator<<(uint64_t value) noexcept
    {
        std::snprintf(m_convertBuffer, sizeof(m_convertBuffer), "%llu", static_cast<unsigned long long>(value));
        return *this << m_convertBuffer;
    }

    TextStream& operator<<(float value) noexcept
    {
        return *this << static_cast<double>(value);
    }

    TextStream& operator<<(double value) noexcept
    {
        uint32_t precision = 1;
        if (value < 10.0 && value > -10.0)
        {
            precision = 2;
            if (value < 1.0 && value > -1.0)
            {
                precision = 3;
                if (value < 0.01 && value > -0.01)
                    precision = value == 0.0 ? 1 : 5;
            }
        }
        addFormatted(value, precision);
        return *this;
    }

    template <uint32_t Capacity>
    TextStream& operator<<(const StaticString<Capacity>& value) noexcept
    {
        append(value.text(), value.size());
        return *this;
    }

    void addFormatted(double value, uint32_t precision) noexcept
    {
        char format[8]{};
        std::snprintf(format, sizeof(format), "%%.%ulf", precision);
        std::snprintf(m_convertBuffer, sizeof(m_convertBuffer), format, value);
        *this << m_convertBuffer;
    }

private:
    void append(const char* text, uint32_t size) noexcept
    {
        if (!text || !m_buffer || m_sizeMax == 0 || size == 0)
            return;
        const uint32_t copySize = (std::min)(size, m_sizeMax - (std::min)(m_size + 1, m_sizeMax));
        if (copySize == 0)
            return;
        std::memcpy(m_buffer + m_size, text, copySize);
        m_size += copySize;
        m_buffer[m_size] = '\0';
    }

    static constexpr uint32_t kConvertBufferMaxSizeBytes = 512U;
    uint32_t m_size{};
    uint32_t m_sizeMax{};
    char* m_buffer{};
    char m_convertBuffer[kConvertBufferMaxSizeBytes]{};
};

} // namespace omni::ui::boundedtext
