/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Reads SVG text into a svg::Document: a small XML reader, a CSS reader for
// the style attribute and <style> sheets, and the SVG rules for shapes,
// styles, gradients, <use> and clip paths. See StandaloneSvgDocument.h.

#include "StandaloneSvgDocument.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstring>
#include <forward_list>
#include <optional>
#include <set>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

namespace omni {
namespace ui {
namespace standalone {
namespace svg {

namespace {

constexpr double kPi = 3.14159265358979323846;
/// Deepest element nesting that is read. Deeper files are refused.
constexpr size_t kMaxXmlDepth = 256;
/// Deepest nesting of the drawing: groups, <svg> and <use> references
/// together. Deeper parts are not drawn and are reported.
constexpr int kMaxDrawingDepth = 256;
/// Longest chain of gradient templates (href) that is followed.
constexpr int kMaxReferenceDepth = 32;

// Work limits (see StandaloneSvgDocument.h). Each is checked before the work
// that it limits is done.
/// Bytes of text that entity references add to the file, in total.
constexpr size_t kMaxEntityText = 1024 * 1024;
/// XML elements of a file.
constexpr size_t kMaxXmlElements = 1000000;
/// XML attributes of a file.
constexpr size_t kMaxXmlAttributes = 4 * kMaxXmlElements;
/// Groups and shapes of the drawing (also clip shapes), after <use>
/// references are followed.
constexpr size_t kMaxNodes = 100000;
/// Points of all shapes and clip shapes, after <use> references are followed.
constexpr size_t kMaxPathPoints = 4000000;
/// Selector and declaration pairs of all <style> rules.
constexpr size_t kMaxCssPairs = 100000;
/// Selector tests and declarations applied while the style of each element
/// is computed.
constexpr size_t kMaxCssSteps = 10000000;
/// Stops of one gradient.
constexpr size_t kMaxGradientStops = 4096;
/// The memory of a thread's last XML file is kept for the next file while it
/// holds at most this many elements (about 100 bytes each).
constexpr size_t kKeepXmlElements = 1024;
/// Attribute names of one element that are compared one by one to find a
/// name given twice. An element with more uses a set of its names.
constexpr size_t kListedAttributes = 64;

constexpr std::string_view kSvgNamespace = "http://www.w3.org/2000/svg";
constexpr std::string_view kXlinkNamespace = "http://www.w3.org/1999/xlink";

bool isSpace(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f';
}

// ASCII character classes. The <cctype> functions depend on the locale.
bool isDigit(char c)
{
    return c >= '0' && c <= '9';
}

bool isLetter(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

char toLowerAscii(char c)
{
    return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

char toUpperAscii(char c)
{
    return (c >= 'a' && c <= 'z') ? static_cast<char>(c - 'a' + 'A') : c;
}

std::string_view trim(std::string_view s)
{
    while (!s.empty() && isSpace(s.front()))
        s.remove_prefix(1);
    while (!s.empty() && isSpace(s.back()))
        s.remove_suffix(1);
    return s;
}

std::string toLower(std::string_view s)
{
    std::string out(s);
    for (char& c : out)
        c = toLowerAscii(c);
    return out;
}

bool startsWith(std::string_view s, std::string_view prefix)
{
    return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

/// A file that needs more than a work limit. parseSvgDocument() returns its
/// text as the error.
class LimitError : public std::runtime_error
{
public:
    explicit LimitError(const std::string& what) : std::runtime_error("the SVG is too complex to draw: " + what) {}
};

bool equalsIgnoreCase(std::string_view a, std::string_view b)
{
    if (a.size() != b.size())
        return false;
    for (size_t i = 0; i < a.size(); ++i)
    {
        if (toLowerAscii(a[i]) != toLowerAscii(b[i]))
            return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Numbers and lists
// ---------------------------------------------------------------------------

#if defined(_MSC_VER)
#    define OVUI_SVG_NOINLINE __declspec(noinline)
#else
#    define OVUI_SVG_NOINLINE __attribute__((noinline))
#endif

/// True when the number text [first, last), which std::from_chars found
/// out of range, is too small rather than too large: the power of ten of
/// its first digit that is not 0, plus its exponent, is below 0.
/// Out of line: it runs only for a number out of the double range, and the
/// usual numbers are read faster without it in NumberReader::number().
OVUI_SVG_NOINLINE bool isUnderflow(const char* first, const char* last)
{
    const char* p = first;
    if (p < last && (*p == '+' || *p == '-'))
        ++p;
    long long magnitude = 0; // the power of ten of the first nonzero digit, without the exponent
    bool found = false;
    long long integerDigits = 0;
    for (; p < last && isDigit(*p); ++p)
    {
        if (found || *p != '0')
        {
            found = true;
            ++integerDigits;
        }
    }
    if (found)
        magnitude = integerDigits - 1;
    if (p < last && *p == '.')
    {
        ++p;
        long long position = -1;
        for (; p < last && isDigit(*p); ++p, --position)
        {
            if (!found && *p != '0')
            {
                found = true;
                magnitude = position;
            }
        }
    }
    long long exponent = 0;
    if (p < last && (*p == 'e' || *p == 'E'))
    {
        ++p;
        const bool negativeExponent = p < last && *p == '-';
        if (p < last && (*p == '+' || *p == '-'))
            ++p;
        for (; p < last && isDigit(*p); ++p)
            exponent = std::min<long long>(exponent * 10 + (*p - '0'), 1000000000LL);
        if (negativeExponent)
            exponent = -exponent;
    }
    return found && magnitude + exponent < 0;
}


/// Reads text as a sequence of numbers in the SVG number grammar:
/// [+-] (digits [. digits] | . digits) [(e|E) [+-] digits]. Numbers may be
/// separated by white space and at most one comma, or by nothing when the
/// grammar allows it ("1.5.5" is 1.5 and .5, "1-2" is 1 and -2).
class NumberReader
{
public:
    explicit NumberReader(std::string_view text) : m_p(text.data()), m_end(text.data() + text.size()) {}

    bool atEnd()
    {
        skipSpace();
        return m_p >= m_end;
    }

    void skipSpace()
    {
        while (m_p < m_end && isSpace(*m_p))
            ++m_p;
    }

    void skipSeparator()
    {
        skipSpace();
        if (m_p < m_end && *m_p == ',')
        {
            ++m_p;
            skipSpace();
        }
    }

    char peek()
    {
        skipSpace();
        return m_p < m_end ? *m_p : '\0';
    }

    void advance() { ++m_p; }

    bool number(double& out)
    {
        skipSpace();
        const char* start = m_p;
        const char* p = m_p;
        bool negative = false;
        if (p < m_end && (*p == '+' || *p == '-'))
            negative = *p++ == '-';
        // The digits are read into an integer on the way; up to 15 digits it
        // is exact.
        uint64_t mantissa = 0;
        int digits = 0;
        int fraction = 0;
        while (p < m_end && isDigit(*p))
        {
            mantissa = mantissa * 10 + static_cast<uint64_t>(*p++ - '0');
            ++digits;
        }
        if (p < m_end && *p == '.')
        {
            ++p;
            while (p < m_end && isDigit(*p))
            {
                mantissa = mantissa * 10 + static_cast<uint64_t>(*p++ - '0');
                ++digits;
                ++fraction;
            }
        }
        if (digits == 0)
            return false;
        bool exponent = false;
        if (p < m_end && (*p == 'e' || *p == 'E'))
        {
            const char* q = p + 1;
            if (q < m_end && (*q == '+' || *q == '-'))
                ++q;
            const char* exponentDigits = q;
            while (q < m_end && isDigit(*q))
                ++q;
            if (q > exponentDigits)
            {
                p = q;
                exponent = true;
            }
        }
        if (!exponent && digits <= 15)
        {
            // The usual short number: one division of an exact integer by an
            // exact power of ten gives the correctly rounded value, the same
            // as std::from_chars.
            static const double kPow10[] = { 1e0, 1e1, 1e2,  1e3,  1e4,  1e5,  1e6,  1e7,
                                             1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15 };
            const double v = static_cast<double>(mantissa) / kPow10[fraction];
            m_p = p;
            out = negative ? -v : v;
            return true;
        }
        // std::from_chars does not take a leading '+'. It does not depend on
        // the locale, unlike strtod.
        double value = 0.0;
        const char* first = (*start == '+') ? start + 1 : start;
        auto result = std::from_chars(first, p, value);
        if (result.ec == std::errc::result_out_of_range && result.ptr == p)
        {
            // Too small or too large for a double. A number too small is 0, as
            // in browsers; a number too large is an error of the file.
            if (!isUnderflow(first, p))
                return false;
            value = negative ? -0.0 : 0.0;
        }
        else if (result.ec != std::errc() || result.ptr != p)
        {
            return false;
        }
        if (!std::isfinite(value))
            return false;
        m_p = p;
        out = value;
        return true;
    }

    /// An arc flag: one '0' or '1', which may be followed directly by the next number.
    bool flag(bool& out)
    {
        skipSpace();
        if (m_p < m_end && (*m_p == '0' || *m_p == '1'))
        {
            out = *m_p == '1';
            ++m_p;
            return true;
        }
        return false;
    }

    /// The text from the current position to the end, without leading space.
    std::string_view rest()
    {
        skipSpace();
        return std::string_view(m_p, static_cast<size_t>(m_end - m_p));
    }

private:
    const char* m_p;
    const char* m_end;
};

std::vector<double> parseNumberList(std::string_view text, bool* ok = nullptr)
{
    std::vector<double> values;
    NumberReader reader(text);
    bool good = true;
    while (!reader.atEnd())
    {
        double v = 0.0;
        if (!reader.number(v))
        {
            good = false;
            break;
        }
        values.push_back(v);
        reader.skipSeparator();
    }
    if (ok)
        *ok = good;
    return values;
}

// ---------------------------------------------------------------------------
// Lengths
// ---------------------------------------------------------------------------

/// Which size a percentage refers to.
enum class Axis
{
    eX,
    eY,
    eOther
};

struct Length
{
    double value = 0.0;
    bool percent = false;
};

/// Parses "12", "12px", "1.5em", "50%" and the other absolute units.
bool parseLength(std::string_view text, Length& out)
{
    text = trim(text);
    NumberReader reader(text);
    double value = 0.0;
    if (!reader.number(value))
        return false;
    const std::string_view unit = trim(reader.rest());
    auto is = [&](std::string_view name) { return equalsIgnoreCase(unit, name); };
    double scale = 1.0;
    bool percent = false;
    if (unit.empty() || is("px"))
        scale = 1.0;
    else if (unit == "%")
        percent = true;
    else if (is("pt"))
        scale = 96.0 / 72.0;
    else if (is("pc"))
        scale = 16.0;
    else if (is("in"))
        scale = 96.0;
    else if (is("cm"))
        scale = 96.0 / 2.54;
    else if (is("mm"))
        scale = 96.0 / 25.4;
    else if (is("q"))
        scale = 96.0 / 101.6;
    else if (is("em") || is("rem"))
        scale = 16.0; // the default font size; ovui does not draw SVG text
    else if (is("ex"))
        scale = 8.0;
    else
        return false;
    out.value = percent ? value : value * scale;
    out.percent = percent;
    return true;
}

struct Viewport
{
    double width = 0.0;
    double height = 0.0;

    double resolve(const Length& length, Axis axis) const
    {
        if (!length.percent)
            return length.value;
        double reference = 0.0;
        switch (axis)
        {
        case Axis::eX:
            reference = width;
            break;
        case Axis::eY:
            reference = height;
            break;
        case Axis::eOther:
            reference = std::sqrt((width * width + height * height) / 2.0);
            break;
        }
        return length.value / 100.0 * reference;
    }
};

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------

struct NamedColor
{
    const char* name;
    uint32_t rgb;
};

// The CSS color keywords.
const NamedColor kNamedColors[] = {
    { "aliceblue", 0xf0f8ff },
    { "antiquewhite", 0xfaebd7 },
    { "aqua", 0x00ffff },
    { "aquamarine", 0x7fffd4 },
    { "azure", 0xf0ffff },
    { "beige", 0xf5f5dc },
    { "bisque", 0xffe4c4 },
    { "black", 0x000000 },
    { "blanchedalmond", 0xffebcd },
    { "blue", 0x0000ff },
    { "blueviolet", 0x8a2be2 },
    { "brown", 0xa52a2a },
    { "burlywood", 0xdeb887 },
    { "cadetblue", 0x5f9ea0 },
    { "chartreuse", 0x7fff00 },
    { "chocolate", 0xd2691e },
    { "coral", 0xff7f50 },
    { "cornflowerblue", 0x6495ed },
    { "cornsilk", 0xfff8dc },
    { "crimson", 0xdc143c },
    { "cyan", 0x00ffff },
    { "darkblue", 0x00008b },
    { "darkcyan", 0x008b8b },
    { "darkgoldenrod", 0xb8860b },
    { "darkgray", 0xa9a9a9 },
    { "darkgreen", 0x006400 },
    { "darkgrey", 0xa9a9a9 },
    { "darkkhaki", 0xbdb76b },
    { "darkmagenta", 0x8b008b },
    { "darkolivegreen", 0x556b2f },
    { "darkorange", 0xff8c00 },
    { "darkorchid", 0x9932cc },
    { "darkred", 0x8b0000 },
    { "darksalmon", 0xe9967a },
    { "darkseagreen", 0x8fbc8f },
    { "darkslateblue", 0x483d8b },
    { "darkslategray", 0x2f4f4f },
    { "darkslategrey", 0x2f4f4f },
    { "darkturquoise", 0x00ced1 },
    { "darkviolet", 0x9400d3 },
    { "deeppink", 0xff1493 },
    { "deepskyblue", 0x00bfff },
    { "dimgray", 0x696969 },
    { "dimgrey", 0x696969 },
    { "dodgerblue", 0x1e90ff },
    { "firebrick", 0xb22222 },
    { "floralwhite", 0xfffaf0 },
    { "forestgreen", 0x228b22 },
    { "fuchsia", 0xff00ff },
    { "gainsboro", 0xdcdcdc },
    { "ghostwhite", 0xf8f8ff },
    { "gold", 0xffd700 },
    { "goldenrod", 0xdaa520 },
    { "gray", 0x808080 },
    { "green", 0x008000 },
    { "greenyellow", 0xadff2f },
    { "grey", 0x808080 },
    { "honeydew", 0xf0fff0 },
    { "hotpink", 0xff69b4 },
    { "indianred", 0xcd5c5c },
    { "indigo", 0x4b0082 },
    { "ivory", 0xfffff0 },
    { "khaki", 0xf0e68c },
    { "lavender", 0xe6e6fa },
    { "lavenderblush", 0xfff0f5 },
    { "lawngreen", 0x7cfc00 },
    { "lemonchiffon", 0xfffacd },
    { "lightblue", 0xadd8e6 },
    { "lightcoral", 0xf08080 },
    { "lightcyan", 0xe0ffff },
    { "lightgoldenrodyellow", 0xfafad2 },
    { "lightgray", 0xd3d3d3 },
    { "lightgreen", 0x90ee90 },
    { "lightgrey", 0xd3d3d3 },
    { "lightpink", 0xffb6c1 },
    { "lightsalmon", 0xffa07a },
    { "lightseagreen", 0x20b2aa },
    { "lightskyblue", 0x87cefa },
    { "lightslategray", 0x778899 },
    { "lightslategrey", 0x778899 },
    { "lightsteelblue", 0xb0c4de },
    { "lightyellow", 0xffffe0 },
    { "lime", 0x00ff00 },
    { "limegreen", 0x32cd32 },
    { "linen", 0xfaf0e6 },
    { "magenta", 0xff00ff },
    { "maroon", 0x800000 },
    { "mediumaquamarine", 0x66cdaa },
    { "mediumblue", 0x0000cd },
    { "mediumorchid", 0xba55d3 },
    { "mediumpurple", 0x9370db },
    { "mediumseagreen", 0x3cb371 },
    { "mediumslateblue", 0x7b68ee },
    { "mediumspringgreen", 0x00fa9a },
    { "mediumturquoise", 0x48d1cc },
    { "mediumvioletred", 0xc71585 },
    { "midnightblue", 0x191970 },
    { "mintcream", 0xf5fffa },
    { "mistyrose", 0xffe4e1 },
    { "moccasin", 0xffe4b5 },
    { "navajowhite", 0xffdead },
    { "navy", 0x000080 },
    { "oldlace", 0xfdf5e6 },
    { "olive", 0x808000 },
    { "olivedrab", 0x6b8e23 },
    { "orange", 0xffa500 },
    { "orangered", 0xff4500 },
    { "orchid", 0xda70d6 },
    { "palegoldenrod", 0xeee8aa },
    { "palegreen", 0x98fb98 },
    { "paleturquoise", 0xafeeee },
    { "palevioletred", 0xdb7093 },
    { "papayawhip", 0xffefd5 },
    { "peachpuff", 0xffdab9 },
    { "peru", 0xcd853f },
    { "pink", 0xffc0cb },
    { "plum", 0xdda0dd },
    { "powderblue", 0xb0e0e6 },
    { "purple", 0x800080 },
    { "rebeccapurple", 0x663399 },
    { "red", 0xff0000 },
    { "rosybrown", 0xbc8f8f },
    { "royalblue", 0x4169e1 },
    { "saddlebrown", 0x8b4513 },
    { "salmon", 0xfa8072 },
    { "sandybrown", 0xf4a460 },
    { "seagreen", 0x2e8b57 },
    { "seashell", 0xfff5ee },
    { "sienna", 0xa0522d },
    { "silver", 0xc0c0c0 },
    { "skyblue", 0x87ceeb },
    { "slateblue", 0x6a5acd },
    { "slategray", 0x708090 },
    { "slategrey", 0x708090 },
    { "snow", 0xfffafa },
    { "springgreen", 0x00ff7f },
    { "steelblue", 0x4682b4 },
    { "tan", 0xd2b48c },
    { "teal", 0x008080 },
    { "thistle", 0xd8bfd8 },
    { "tomato", 0xff6347 },
    { "turquoise", 0x40e0d0 },
    { "violet", 0xee82ee },
    { "wheat", 0xf5deb3 },
    { "white", 0xffffff },
    { "whitesmoke", 0xf5f5f5 },
    { "yellow", 0xffff00 },
    { "yellowgreen", 0x9acd32 },
};

Color colorFromRgb(uint32_t rgb, float alpha = 1.0f)
{
    Color c;
    c.r = static_cast<float>((rgb >> 16) & 0xff) / 255.0f;
    c.g = static_cast<float>((rgb >> 8) & 0xff) / 255.0f;
    c.b = static_cast<float>(rgb & 0xff) / 255.0f;
    c.a = alpha;
    return c;
}

float clamp01(double v)
{
    return static_cast<float>(std::min(1.0, std::max(0.0, v)));
}

int hexDigit(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

/// Reads the arguments of rgb(), rgba(), hsl() and hsla(): numbers or
/// percentages, separated by commas or by spaces with an optional "/" before
/// the alpha value. `percentScale` is what 100% means for each of the first
/// three arguments.
bool parseColorArguments(std::string_view args, double values[4], bool percents[4], int& count, bool hueFirst)
{
    count = 0;
    size_t i = 0;
    while (i < args.size())
    {
        while (i < args.size() && (isSpace(args[i]) || args[i] == ',' || args[i] == '/'))
            ++i;
        if (i >= args.size())
            break;
        if (count == 4)
            return false;
        NumberReader reader(args.substr(i));
        double v = 0.0;
        if (!reader.number(v))
            return false;
        std::string_view rest = reader.rest();
        size_t used = args.size() - i - rest.size();
        bool percent = false;
        if (!rest.empty() && rest.front() == '%')
        {
            percent = true;
            ++used;
        }
        else if (hueFirst && count == 0 && startsWith(rest, "deg"))
        {
            used += 3;
        }
        values[count] = v;
        percents[count] = percent;
        ++count;
        i += used;
    }
    return count == 3 || count == 4;
}

bool parseColor(std::string_view text, Color& out)
{
    text = trim(text);
    if (text.empty())
        return false;
    if (text.front() == '#')
    {
        std::string_view hex = text.substr(1);
        int digits[8] = {};
        if (hex.size() != 3 && hex.size() != 4 && hex.size() != 6 && hex.size() != 8)
            return false;
        for (size_t i = 0; i < hex.size(); ++i)
        {
            digits[i] = hexDigit(hex[i]);
            if (digits[i] < 0)
                return false;
        }
        int r, g, b, a = 255;
        if (hex.size() <= 4)
        {
            r = digits[0] * 17;
            g = digits[1] * 17;
            b = digits[2] * 17;
            if (hex.size() == 4)
                a = digits[3] * 17;
        }
        else
        {
            r = digits[0] * 16 + digits[1];
            g = digits[2] * 16 + digits[3];
            b = digits[4] * 16 + digits[5];
            if (hex.size() == 8)
                a = digits[6] * 16 + digits[7];
        }
        out = colorFromRgb(static_cast<uint32_t>((r << 16) | (g << 8) | b), static_cast<float>(a) / 255.0f);
        return true;
    }

    const size_t open = text.find('(');
    if (open != std::string_view::npos)
    {
        if (text.back() != ')')
            return false;
        const std::string name = toLower(trim(text.substr(0, open)));
        const std::string_view args = text.substr(open + 1, text.size() - open - 2);
        double v[4] = { 0, 0, 0, 1 };
        bool percent[4] = { false, false, false, false };
        int count = 0;
        if (name == "rgb" || name == "rgba")
        {
            if (!parseColorArguments(args, v, percent, count, false))
                return false;
            double rgb[3];
            for (int i = 0; i < 3; ++i)
                rgb[i] = percent[i] ? v[i] / 100.0 : v[i] / 255.0;
            double alpha = count == 4 ? (percent[3] ? v[3] / 100.0 : v[3]) : 1.0;
            // A channel is rounded to 8 bits, like a browser stores it.
            out.r = static_cast<float>(std::round(clamp01(rgb[0]) * 255.0) / 255.0);
            out.g = static_cast<float>(std::round(clamp01(rgb[1]) * 255.0) / 255.0);
            out.b = static_cast<float>(std::round(clamp01(rgb[2]) * 255.0) / 255.0);
            out.a = clamp01(alpha);
            return true;
        }
        if (name == "hsl" || name == "hsla")
        {
            if (!parseColorArguments(args, v, percent, count, true))
                return false;
            double h = std::fmod(v[0], 360.0);
            if (h < 0)
                h += 360.0;
            const double s = clamp01(v[1] / 100.0);
            const double l = clamp01(v[2] / 100.0);
            const double alpha = count == 4 ? (percent[3] ? v[3] / 100.0 : v[3]) : 1.0;
            const double chroma = (1.0 - std::fabs(2.0 * l - 1.0)) * s;
            const double hp = h / 60.0;
            const double x = chroma * (1.0 - std::fabs(std::fmod(hp, 2.0) - 1.0));
            double r = 0, g = 0, b = 0;
            if (hp < 1)
                r = chroma, g = x;
            else if (hp < 2)
                r = x, g = chroma;
            else if (hp < 3)
                g = chroma, b = x;
            else if (hp < 4)
                g = x, b = chroma;
            else if (hp < 5)
                r = x, b = chroma;
            else
                r = chroma, b = x;
            const double m = l - chroma / 2.0;
            out.r = static_cast<float>(std::round(clamp01(r + m) * 255.0) / 255.0);
            out.g = static_cast<float>(std::round(clamp01(g + m) * 255.0) / 255.0);
            out.b = static_cast<float>(std::round(clamp01(b + m) * 255.0) / 255.0);
            out.a = clamp01(alpha);
            return true;
        }
        return false;
    }

    if (equalsIgnoreCase(text, "transparent"))
    {
        out = Color{ 0.0f, 0.0f, 0.0f, 0.0f };
        return true;
    }
    for (const NamedColor& named : kNamedColors)
    {
        if (equalsIgnoreCase(text, named.name))
        {
            out = colorFromRgb(named.rgb);
            return true;
        }
    }
    return false;
}

// ---------------------------------------------------------------------------
// Transforms
// ---------------------------------------------------------------------------

/// Parses a transform list. Returns false for a malformed list; SVG then
/// uses no transform at all.
bool parseTransformList(std::string_view text, Transform& out)
{
    Transform result;
    size_t i = 0;
    while (true)
    {
        while (i < text.size() && (isSpace(text[i]) || text[i] == ','))
            ++i;
        if (i >= text.size())
            break;
        size_t nameStart = i;
        while (i < text.size() && isLetter(text[i]))
            ++i;
        const std::string_view name = text.substr(nameStart, i - nameStart);
        while (i < text.size() && isSpace(text[i]))
            ++i;
        if (i >= text.size() || text[i] != '(')
            return false;
        const size_t close = text.find(')', i);
        if (close == std::string_view::npos)
            return false;
        bool ok = true;
        const std::vector<double> v = parseNumberList(text.substr(i + 1, close - i - 1), &ok);
        if (!ok)
            return false;
        i = close + 1;

        Transform t;
        if (name == "matrix" && v.size() == 6)
        {
            t.a = v[0];
            t.b = v[1];
            t.c = v[2];
            t.d = v[3];
            t.e = v[4];
            t.f = v[5];
        }
        else if (name == "translate" && (v.size() == 1 || v.size() == 2))
            t = Transform::translate(v[0], v.size() == 2 ? v[1] : 0.0);
        else if (name == "scale" && (v.size() == 1 || v.size() == 2))
            t = Transform::scale(v[0], v.size() == 2 ? v[1] : v[0]);
        else if (name == "rotate" && v.size() == 1)
            t = Transform::rotate(v[0]);
        else if (name == "rotate" && v.size() == 3)
            t = Transform::translate(v[1], v[2]) * Transform::rotate(v[0]) * Transform::translate(-v[1], -v[2]);
        else if (name == "skewX" && v.size() == 1)
            t = Transform::skewX(v[0]);
        else if (name == "skewY" && v.size() == 1)
            t = Transform::skewY(v[0]);
        else
            return false;
        result = result * t;
    }
    out = result;
    return true;
}

// ---------------------------------------------------------------------------
// Path data
// ---------------------------------------------------------------------------

/// Parses SVG path data. On an error the path keeps what was read before it,
/// as the SVG rules ask.
/// Reads path data into `path`. Returns false when the data has an error: the
/// path then holds the commands before the error, as SVG says.
bool parsePathData(std::string_view text, Path& path)
{
    NumberReader r(text);
    char command = '\0';
    Point start;
    Point current;
    Point lastCubicControl;
    Point lastQuadControl;
    char previous = '\0';
    while (!r.atEnd())
    {
        const char c = r.peek();
        if (isLetter(c))
        {
            command = c;
            r.advance();
        }
        else if (command == '\0')
        {
            return false; // data must start with a command
        }
        else if (command == 'Z' || command == 'z')
        {
            return false; // numbers after Z are an error
        }
        const bool relative = command >= 'a' && command <= 'z';
        const double ox = relative ? current.x : 0.0;
        const double oy = relative ? current.y : 0.0;
        switch (toUpperAscii(command))
        {
        case 'M':
        {
            double x, y;
            if (!r.number(x) || (r.skipSeparator(), !r.number(y)))
                return false;
            current = { ox + x, oy + y };
            start = current;
            path.moveTo(current);
            // Further pairs are line commands.
            command = relative ? 'l' : 'L';
            break;
        }
        case 'L':
        {
            double x, y;
            if (!r.number(x) || (r.skipSeparator(), !r.number(y)))
                return false;
            current = { ox + x, oy + y };
            path.lineTo(current);
            break;
        }
        case 'H':
        {
            double x;
            if (!r.number(x))
                return false;
            current.x = ox + x;
            path.lineTo(current);
            break;
        }
        case 'V':
        {
            double y;
            if (!r.number(y))
                return false;
            current.y = oy + y;
            path.lineTo(current);
            break;
        }
        case 'C':
        {
            double v[6];
            for (int i = 0; i < 6; ++i)
            {
                if (i)
                    r.skipSeparator();
                if (!r.number(v[i]))
                    return false;
            }
            const Point c1{ ox + v[0], oy + v[1] };
            const Point c2{ ox + v[2], oy + v[3] };
            current = { ox + v[4], oy + v[5] };
            path.cubicTo(c1, c2, current);
            lastCubicControl = c2;
            break;
        }
        case 'S':
        {
            double v[4];
            for (int i = 0; i < 4; ++i)
            {
                if (i)
                    r.skipSeparator();
                if (!r.number(v[i]))
                    return false;
            }
            const char p = toUpperAscii(previous);
            const Point c1 = (p == 'C' || p == 'S') ?
                                 Point{ 2.0 * current.x - lastCubicControl.x, 2.0 * current.y - lastCubicControl.y } :
                                 current;
            const Point c2{ ox + v[0], oy + v[1] };
            current = { ox + v[2], oy + v[3] };
            path.cubicTo(c1, c2, current);
            lastCubicControl = c2;
            break;
        }
        case 'Q':
        {
            double v[4];
            for (int i = 0; i < 4; ++i)
            {
                if (i)
                    r.skipSeparator();
                if (!r.number(v[i]))
                    return false;
            }
            const Point q{ ox + v[0], oy + v[1] };
            current = { ox + v[2], oy + v[3] };
            path.quadTo(q, current);
            lastQuadControl = q;
            break;
        }
        case 'T':
        {
            double v[2];
            if (!r.number(v[0]) || (r.skipSeparator(), !r.number(v[1])))
                return false;
            const char p = toUpperAscii(previous);
            const Point q = (p == 'Q' || p == 'T') ?
                                Point{ 2.0 * current.x - lastQuadControl.x, 2.0 * current.y - lastQuadControl.y } :
                                current;
            current = { ox + v[0], oy + v[1] };
            path.quadTo(q, current);
            lastQuadControl = q;
            break;
        }
        case 'A':
        {
            double rx, ry, rotation, x, y;
            bool largeArc, sweep;
            if (!r.number(rx) || (r.skipSeparator(), !r.number(ry)) || (r.skipSeparator(), !r.number(rotation)) ||
                (r.skipSeparator(), !r.flag(largeArc)) || (r.skipSeparator(), !r.flag(sweep)) ||
                (r.skipSeparator(), !r.number(x)) || (r.skipSeparator(), !r.number(y)))
                return false;
            const Point to{ ox + x, oy + y };
            path.arcTo(rx, ry, rotation, largeArc, sweep, to);
            current = to;
            break;
        }
        case 'Z':
            path.close();
            current = start;
            break;
        default:
            return false; // an unknown command ends the data
        }
        previous = command;
        if (command == 'M' || command == 'm')
            previous = 'L';
        r.skipSeparator();
    }
    return true;
}

/// Adds `count` pieces of 45 degrees of the ellipse (cx, cy, rx, ry) as cubic
/// curves, from octant `first` on (octant 0 starts on the +x axis and turns
/// toward +y). The current point must be the start of the first piece.
void addEllipseOctants(Path& path, double cx, double cy, double rx, double ry, int first, int count)
{
    constexpr double r = 0.70710678118654752440;
    static const double kCos[9] = { 1.0, r, 0.0, -r, -1.0, -r, 0.0, r, 1.0 };
    static const double kSin[9] = { 0.0, r, 1.0, r, 0.0, -r, -1.0, -r, 0.0 };
    // The handle length of a cubic that follows 45 degrees of a unit circle.
    const double k = 4.0 / 3.0 * std::tan(kPi / 16.0);
    for (int i = first; i < first + count; ++i)
    {
        const int a = i % 8;
        const int b = a + 1;
        path.cubicTo({ cx + rx * (kCos[a] - k * kSin[a]), cy + ry * (kSin[a] + k * kCos[a]) },
                     { cx + rx * (kCos[b] + k * kSin[b]), cy + ry * (kSin[b] - k * kCos[b]) },
                     { cx + rx * kCos[b], cy + ry * kSin[b] });
    }
}

// ---------------------------------------------------------------------------
// XML
// ---------------------------------------------------------------------------

/// The SVG elements that the reader knows.
enum class Tag : uint8_t
{
    eOther,
    eA,
    eCircle,
    eClipPath,
    eDefs,
    eDesc,
    eEllipse,
    eFilter,
    eForeignObject,
    eG,
    eImage,
    eLine,
    eLinearGradient,
    eMarker,
    eMask,
    eMetadata,
    ePath,
    ePattern,
    ePolygon,
    ePolyline,
    eRadialGradient,
    eRect,
    eStop,
    eStyle,
    eSvg,
    eSwitch,
    eSymbol,
    eText,
    eTitle,
    eUse,
};

Tag tagOf(std::string_view name)
{
    // By length first, so that only a few names are compared.
    switch (name.size())
    {
    case 1:
        return name == "g" ? Tag::eG : name == "a" ? Tag::eA : Tag::eOther;
    case 3:
        return name == "svg" ? Tag::eSvg : name == "use" ? Tag::eUse : Tag::eOther;
    case 4:
        return name == "path" ? Tag::ePath :
               name == "rect" ? Tag::eRect :
               name == "line" ? Tag::eLine :
               name == "defs" ? Tag::eDefs :
               name == "stop" ? Tag::eStop :
               name == "desc" ? Tag::eDesc :
               name == "mask" ? Tag::eMask :
               name == "text" ? Tag::eText :
                                Tag::eOther;
    case 5:
        return name == "style" ? Tag::eStyle :
               name == "title" ? Tag::eTitle :
               name == "image" ? Tag::eImage :
                                 Tag::eOther;
    case 6:
        return name == "circle" ? Tag::eCircle :
               name == "symbol" ? Tag::eSymbol :
               name == "switch" ? Tag::eSwitch :
               name == "filter" ? Tag::eFilter :
               name == "marker" ? Tag::eMarker :
                                  Tag::eOther;
    case 7:
        return name == "ellipse" ? Tag::eEllipse :
               name == "polygon" ? Tag::ePolygon :
               name == "pattern" ? Tag::ePattern :
                                   Tag::eOther;
    case 8:
        return name == "polyline" ? Tag::ePolyline :
               name == "clipPath" ? Tag::eClipPath :
               name == "metadata" ? Tag::eMetadata :
                                    Tag::eOther;
    case 13:
        return name == "foreignObject" ? Tag::eForeignObject : Tag::eOther;
    case 14:
        return name == "linearGradient" ? Tag::eLinearGradient :
               name == "radialGradient" ? Tag::eRadialGradient :
                                          Tag::eOther;
    default:
        return Tag::eOther;
    }
}

struct XmlAttribute
{
    std::string_view name;
    std::string_view value; ///< points into the file text, or into decoded text kept by the document
};

struct XmlElement
{
    std::string_view name; ///< local name of an SVG element; empty for an element of another namespace
    Tag tag = Tag::eOther;
    const XmlAttribute* attributes = nullptr;
    size_t attributeCount = 0;
    std::string text; ///< character data, kept for <style> only
    XmlElement* parent = nullptr;
    XmlElement* firstChild = nullptr;
    XmlElement* lastChild = nullptr;
    XmlElement* nextSibling = nullptr;
    size_t childCount = 0;

    const std::string_view* attribute(std::string_view key) const
    {
        for (size_t i = 0; i < attributeCount; ++i)
        {
            if (attributes[i].name == key)
                return &attributes[i].value;
        }
        return nullptr;
    }

    /// The child elements, in document order.
    struct Children
    {
        const XmlElement* first;
        struct Iterator
        {
            const XmlElement* e;
            const XmlElement& operator*() const { return *e; }
            Iterator& operator++()
            {
                e = e->nextSibling;
                return *this;
            }
            bool operator!=(const Iterator& o) const { return e != o.e; }
        };
        Iterator begin() const { return { first }; }
        Iterator end() const { return { nullptr }; }
    };
    Children children() const { return { firstChild }; }
};

/// An element that the reader has opened and not yet closed.
struct XmlOpenElement
{
    XmlElement* element;
    std::string_view rawName;
    size_t namespaceCount; ///< namespace declarations that it made
};

/// The elements of a file. Names and values point into the file text, which
/// must outlive the document. The reader reserves `elements` and `attributes`
/// for the most that the text can hold, so that they never move.
struct XmlDocument
{
    std::vector<XmlElement> elements;
    std::vector<XmlAttribute> attributes;
    std::forward_list<std::string> decoded; ///< attribute values that had references
    XmlElement* root = nullptr;

    // The reader's stacks: the open elements and their namespace
    // declarations (prefix, name; the last one wins).
    std::vector<XmlOpenElement> open;
    std::vector<std::pair<std::string_view, std::string_view>> namespaces;

    /// Empties the document. The vectors keep their memory for the next file.
    void clear()
    {
        elements.clear();
        attributes.clear();
        decoded.clear();
        root = nullptr;
        open.clear();
        namespaces.clear();
    }

    /// True when the memory of the last file is too much to keep.
    bool large() const
    {
        return elements.capacity() > kKeepXmlElements || attributes.capacity() > 4 * kKeepXmlElements ||
               namespaces.capacity() > kKeepXmlElements;
    }
};

class XmlReader
{
public:
    explicit XmlReader(const std::string& text) : m_text(text) {}

    /// Reads the text into `doc`. Every '<' of the text must start markup or
    /// be inside a comment, CDATA section, processing instruction or
    /// <!DOCTYPE>; XML does not allow it in an attribute value. That is
    /// checked by counting, so that values are not scanned for it: when the
    /// counts differ, the text is read again with each value checked, which
    /// gives the place of the '<'.
    bool read(XmlDocument& doc, std::string& error)
    {
        if (!read(doc, error, false))
            return false;
        if (m_lessThanSeen == m_lessThanInText)
            return true;
        doc.clear();
        m_entities.clear();
        m_entityText = 0;
        if (!read(doc, error, true))
            return false;
        return fail(error, 0, "a '<' that does not start markup"); // not expected: the second read finds it
    }

private:
    bool read(XmlDocument& doc, std::string& error, bool checkValues)
    {
        size_t i = 0;
        if (startsWith(m_text, "\xEF\xBB\xBF"))
            i = 3;
        std::vector<XmlOpenElement>& open = doc.open;
        std::vector<std::pair<std::string_view, std::string_view>>& namespaces = doc.namespaces;
        std::string scratch;
        const std::string_view text(m_text);
        // Each element starts with '<' and each attribute has a '=', so these
        // are the most there can be: the vectors never move, and pointers to
        // their items stay valid.
        size_t lessThan = 0, equals = 0;
        countMarks(text, lessThan, equals);
        doc.elements.reserve(std::min(lessThan, kMaxXmlElements));
        doc.attributes.reserve(std::min(equals, kMaxXmlAttributes));
        bool doctypeRead = false;
        m_lessThanInText = lessThan;
        // Each '<' that starts markup, and those inside text that markup skips
        // (a comment, CDATA, ...).
        size_t lessThanSeen = 0;
        auto countSkipped = [&](size_t from, size_t to) {
            lessThanSeen += static_cast<size_t>(std::count(text.begin() + static_cast<std::ptrdiff_t>(from),
                                                           text.begin() + static_cast<std::ptrdiff_t>(to), '<'));
        };
        while (i < text.size())
        {
            if (text[i] != '<')
            {
                const size_t next = std::min(text.find('<', i), text.size());
                const std::string_view chunk = text.substr(i, next - i);
                if (open.empty())
                {
                    if (!trim(chunk).empty())
                        return fail(error, i, "text outside the root element");
                }
                else
                {
                    // Decode to check the references; keep the text of <style> only.
                    std::string& out = open.back().element->tag == Tag::eStyle ? open.back().element->text : scratch;
                    if (&out == &scratch)
                        scratch.clear();
                    if (!decode(chunk, out, i, error))
                        return false;
                }
                i = next;
                continue;
            }
            const std::string_view rest = text.substr(i);
            const char second = i + 1 < text.size() ? text[i + 1] : '\0';
            ++lessThanSeen;
            if (second == '?')
            {
                const size_t end = text.find("?>", i + 2);
                if (end == std::string_view::npos)
                    return fail(error, i, "an unclosed processing instruction");
                countSkipped(i + 2, end);
                i = end + 2;
            }
            else if (second == '!' && startsWith(rest, "<!--"))
            {
                const size_t end = text.find("-->", i + 4);
                if (end == std::string_view::npos)
                    return fail(error, i, "an unclosed comment");
                // XML does not allow "--" inside a comment, also not as the
                // start of a "--->" end.
                const size_t dashes = text.find("--", i + 4);
                if (dashes < end)
                    return fail(error, dashes, "'--' inside a comment");
                countSkipped(i + 4, end);
                i = end + 3;
            }
            else if (second == '!' && startsWith(rest, "<![CDATA["))
            {
                const size_t end = text.find("]]>", i + 9);
                if (end == std::string_view::npos)
                    return fail(error, i, "an unclosed CDATA section");
                if (open.empty())
                    return fail(error, i, "CDATA outside the root element");
                if (open.back().element->tag == Tag::eStyle)
                    open.back().element->text.append(text.substr(i + 9, end - (i + 9)));
                countSkipped(i + 9, end);
                i = end + 3;
            }
            else if (second == '!')
            {
                // The only other "<!" of XML is one <!DOCTYPE ...> before the
                // root element.
                size_t p = i + 2;
                const std::string_view keyword = readName(p);
                if (keyword != "DOCTYPE" || p >= text.size() || !isSpace(text[p]))
                    return fail(error, i, "an unknown markup declaration <!" + std::string(keyword) + ">");
                if (doctypeRead || doc.root)
                    return fail(error, i, "a <!DOCTYPE> that is not the only one before the root element");
                doctypeRead = true;
                const size_t start = i;
                if (!readDoctype(i, error))
                    return false;
                countSkipped(start + 1, i);
            }
            else if (second == '/')
            {
                size_t p = i + 2;
                const std::string_view name = readName(p);
                skipSpace(p);
                if (name.empty() || p >= text.size() || text[p] != '>')
                    return fail(error, i, "a malformed end tag");
                if (open.empty() || open.back().rawName != name)
                    return fail(error, i, "the end tag </" + std::string(name) + "> does not match the open element");
                namespaces.resize(namespaces.size() - open.back().namespaceCount);
                open.pop_back();
                i = p + 1;
            }
            else
            {
                size_t p = i + 1;
                const std::string_view rawName = readName(p);
                if (rawName.empty())
                    return fail(error, i, "a malformed start tag");
                const size_t firstAttribute = doc.attributes.size();
                std::optional<std::unordered_set<std::string_view>> names; // made past kListedAttributes
                size_t namespaceCount = 0;
                bool selfClosing = false;
                while (true)
                {
                    const size_t before = p;
                    skipSpace(p);
                    if (p >= text.size())
                        return fail(error, i, "an unclosed start tag <" + std::string(rawName) + ">");
                    if (text[p] == '>')
                    {
                        ++p;
                        break;
                    }
                    if (text[p] == '/' && p + 1 < text.size() && text[p + 1] == '>')
                    {
                        selfClosing = true;
                        p += 2;
                        break;
                    }
                    if (p == before)
                        return fail(error, p, "attributes must be separated by white space");
                    const std::string_view attributeName = readName(p);
                    if (attributeName.empty())
                        return fail(error, p, "a malformed attribute in <" + std::string(rawName) + ">");
                    skipSpace(p);
                    if (p >= text.size() || text[p] != '=')
                        return fail(error, p, "the attribute " + std::string(attributeName) + " has no value");
                    ++p;
                    skipSpace(p);
                    if (p >= text.size() || (text[p] != '"' && text[p] != '\''))
                        return fail(error, p, "the value of " + std::string(attributeName) + " is not quoted");
                    const char quote = text[p];
                    const size_t valueEnd = text.find(quote, p + 1);
                    if (valueEnd == std::string_view::npos)
                        return fail(error, p, "the value of " + std::string(attributeName) + " is not closed");
                    std::string_view value = text.substr(p + 1, valueEnd - p - 1);
                    if (checkValues)
                    {
                        // XML does not allow a raw '<' in a value.
                        const size_t lessThanInValue = value.find('<');
                        if (lessThanInValue != std::string_view::npos)
                            return fail(error, p + 1 + lessThanInValue,
                                        "a '<' in the value of " + std::string(attributeName) + " (write &lt;)");
                    }
                    if (value.find('&') != std::string_view::npos)
                    {
                        doc.decoded.emplace_front();
                        if (!decode(value, doc.decoded.front(), p + 1, error))
                            return false;
                        value = doc.decoded.front();
                    }
                    // The name is compared with each earlier name of the element
                    // while there are few; past that, a set of the names is
                    // used, so that the time does not grow with the square of
                    // the number of attributes.
                    const size_t earlier = doc.attributes.size() - firstAttribute;
                    if (earlier == kListedAttributes)
                    {
                        names.emplace();
                        for (size_t a = firstAttribute; a < doc.attributes.size(); ++a)
                            names->insert(doc.attributes[a].name);
                    }
                    bool given = false;
                    if (earlier < kListedAttributes)
                    {
                        for (size_t a = firstAttribute; a < doc.attributes.size(); ++a)
                            given = given || doc.attributes[a].name == attributeName;
                    }
                    else
                        given = !names->insert(attributeName).second;
                    if (given)
                        return fail(error, p, "the attribute " + std::string(attributeName) + " is given twice");
                    if (doc.attributes.size() >= kMaxXmlAttributes)
                        return tooComplex(error, p, "it has more than " + std::to_string(kMaxXmlAttributes) +
                                                        " XML attributes");
                    if (doc.attributes.size() == doc.attributes.capacity())
                        return fail(error, p, "too many attributes"); // cannot happen: see the reserve above
                    doc.attributes.push_back({ attributeName, value });
                    if (attributeName == "xmlns")
                    {
                        namespaces.emplace_back(std::string_view(), value);
                        ++namespaceCount;
                    }
                    else if (startsWith(attributeName, "xmlns:"))
                    {
                        namespaces.emplace_back(attributeName.substr(6), value);
                        ++namespaceCount;
                    }
                    p = valueEnd + 1;
                }

                // Names with a prefix: the namespace decides. xlink:href is kept
                // under that name; other prefixed attributes are not used.
                size_t kept = firstAttribute;
                for (size_t a = firstAttribute; a < doc.attributes.size(); ++a)
                {
                    XmlAttribute attribute = doc.attributes[a];
                    const size_t colon = attribute.name.find(':');
                    if (colon != std::string_view::npos)
                    {
                        if (namespaceOf(namespaces, attribute.name.substr(0, colon)) != kXlinkNamespace ||
                            attribute.name.substr(colon + 1) != "href")
                            continue;
                        attribute.name = "xlink:href";
                    }
                    doc.attributes[kept++] = attribute;
                }
                doc.attributes.resize(kept);

                if (doc.elements.size() >= kMaxXmlElements)
                    return tooComplex(error, i, "it has more than " + std::to_string(kMaxXmlElements) +
                                                    " XML elements");
                if (doc.elements.size() == doc.elements.capacity())
                    return fail(error, i, "too many elements"); // cannot happen: see the reserve above
                doc.elements.emplace_back();
                XmlElement* element = &doc.elements.back();
                element->attributes = doc.attributes.data() + firstAttribute;
                element->attributeCount = kept - firstAttribute;
                const size_t colon = rawName.find(':');
                const std::string_view prefix = colon == std::string_view::npos ? std::string_view() : rawName.substr(0, colon);
                const std::string_view local = colon == std::string_view::npos ? rawName : rawName.substr(colon + 1);
                if (namespaceOf(namespaces, prefix) == kSvgNamespace)
                    element->name = local;
                element->tag = tagOf(element->name);

                if (open.empty())
                {
                    if (doc.root)
                        return fail(error, i, "a second root element <" + std::string(rawName) + ">");
                    doc.root = element;
                }
                else
                {
                    XmlElement* parent = open.back().element;
                    element->parent = parent;
                    if (parent->lastChild)
                        parent->lastChild->nextSibling = element;
                    else
                        parent->firstChild = element;
                    parent->lastChild = element;
                    ++parent->childCount;
                }
                if (selfClosing)
                {
                    namespaces.resize(namespaces.size() - namespaceCount);
                }
                else
                {
                    if (open.size() >= kMaxXmlDepth)
                        return fail(error, i, "the elements are nested too deeply");
                    open.push_back({ element, rawName, namespaceCount });
                }
                i = p;
            }
        }
        if (!open.empty())
            return fail(error, text.size(), "the element <" + std::string(open.back().rawName) + "> is not closed");
        if (!doc.root)
            return fail(error, text.size(), "there is no root element");
        m_lessThanSeen = lessThanSeen;
        return true;
    }

private:
    /// The number of '<' and of '=' in the text. Blocks of 64 bytes are
    /// counted in bytes, which compilers turn into vector instructions.
    static void countMarks(std::string_view text, size_t& lessThan, size_t& equals)
    {
        const unsigned char* p = reinterpret_cast<const unsigned char*>(text.data());
        const size_t size = text.size();
        size_t i = 0;
        for (; i + 64 <= size; i += 64)
        {
            unsigned char a = 0, b = 0;
            for (size_t j = 0; j < 64; ++j)
            {
                a = static_cast<unsigned char>(a + (p[i + j] == '<'));
                b = static_cast<unsigned char>(b + (p[i + j] == '='));
            }
            lessThan += a;
            equals += b;
        }
        for (; i < size; ++i)
        {
            lessThan += p[i] == '<';
            equals += p[i] == '=';
        }
    }

    /// The namespace of a prefix; "" for a prefix that is not declared. With
    /// no declaration, the default namespace is the SVG namespace.
    static std::string_view namespaceOf(const std::vector<std::pair<std::string_view, std::string_view>>& namespaces,
                                        std::string_view prefix)
    {
        for (size_t i = namespaces.size(); i-- > 0;)
        {
            if (namespaces[i].first == prefix)
                return namespaces[i].second;
        }
        return prefix.empty() ? std::string_view(kSvgNamespace) : std::string_view();
    }

    /// "line L, column C" of a byte position of the text (both from 1; the
    /// column counts bytes).
    std::string location(size_t position) const
    {
        position = std::min(position, m_text.size());
        const auto end = m_text.begin() + static_cast<std::ptrdiff_t>(position);
        const size_t line = 1 + static_cast<size_t>(std::count(m_text.begin(), end, '\n'));
        const size_t lineStart = position == 0 ? std::string::npos : m_text.rfind('\n', position - 1);
        const size_t column = lineStart == std::string::npos ? position + 1 : position - lineStart;
        return "line " + std::to_string(line) + ", column " + std::to_string(column);
    }

    bool fail(std::string& error, size_t position, const std::string& what)
    {
        error = "the file is not a valid SVG (XML error on " + location(position) + ": " + what + ")";
        return false;
    }

    bool tooComplex(std::string& error, size_t position, const std::string& what)
    {
        error = LimitError(what + " (" + location(position) + ")").what();
        return false;
    }

    void skipSpace(size_t& p) const
    {
        while (p < m_text.size() && isSpace(m_text[p]))
            ++p;
    }

    std::string_view readName(size_t& p) const
    {
        // 1: may start a name; 2: may be inside a name only.
        static const std::array<uint8_t, 256> kNameChar = [] {
            std::array<uint8_t, 256> table{};
            for (int c = 0; c < 256; ++c)
            {
                if (isLetter(static_cast<char>(c)) || c == '_' || c == ':' || c >= 0x80)
                    table[static_cast<size_t>(c)] = 1;
                else if (isDigit(static_cast<char>(c)) || c == '-' || c == '.')
                    table[static_cast<size_t>(c)] = 2;
            }
            return table;
        }();
        const size_t start = p;
        const size_t size = m_text.size();
        if (p < size && kNameChar[static_cast<unsigned char>(m_text[p])] == 1)
        {
            ++p;
            while (p < size && kNameChar[static_cast<unsigned char>(m_text[p])] != 0)
                ++p;
        }
        return std::string_view(m_text).substr(start, p - start);
    }

    /// Skips <!DOCTYPE ...>, with an internal subset in [...], and keeps the
    /// text of each <!ENTITY name "value"> declaration in it.
    bool readDoctype(size_t& i, std::string& error)
    {
        size_t p = i + 2;
        int brackets = 0;
        while (p < m_text.size())
        {
            const char c = m_text[p];
            if (c == '"' || c == '\'')
            {
                const size_t end = m_text.find(c, p + 1);
                if (end == std::string::npos)
                    break;
                p = end + 1;
                continue;
            }
            if (c == '[')
                ++brackets;
            else if (c == ']')
                --brackets;
            else if (c == '>' && brackets <= 0)
            {
                i = p + 1;
                return true;
            }
            else if (brackets > 0 && m_text.compare(p, 8, "<!ENTITY") == 0)
            {
                size_t q = p + 8;
                skipSpace(q);
                const std::string name(readName(q));
                skipSpace(q);
                if (!name.empty() && q < m_text.size() && (m_text[q] == '"' || m_text[q] == '\''))
                {
                    const size_t end = m_text.find(m_text[q], q + 1);
                    if (end != std::string::npos)
                        m_entities[name] = m_text.substr(q + 1, end - q - 1);
                }
            }
            else if (brackets > 0 && m_text.compare(p, 4, "<!--") == 0)
            {
                const size_t end = m_text.find("-->", p + 4);
                if (end == std::string::npos)
                    break;
                p = end + 3;
                continue;
            }
            ++p;
        }
        return fail(error, i, "an unclosed <!DOCTYPE>");
    }

    static void appendUtf8(std::string& out, uint32_t cp)
    {
        if (cp < 0x80)
            out += static_cast<char>(cp);
        else if (cp < 0x800)
        {
            out += static_cast<char>(0xC0 | (cp >> 6));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
        else if (cp < 0x10000)
        {
            out += static_cast<char>(0xE0 | (cp >> 12));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
        else
        {
            out += static_cast<char>(0xF0 | (cp >> 18));
            out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
    }

    /// Replaces the character and entity references in `in`.
    bool decode(std::string_view in, std::string& out, size_t position, std::string& error)
    {
        if (in.find('&') == std::string_view::npos)
        {
            out.append(in);
            return true;
        }
        out.reserve(out.size() + in.size());
        for (size_t i = 0; i < in.size(); ++i)
        {
            if (in[i] != '&')
            {
                out += in[i];
                continue;
            }
            const size_t semicolon = in.find(';', i);
            if (semicolon == std::string_view::npos)
                return fail(error, position + i, "an '&' that does not start a reference");
            const std::string_view ref = in.substr(i + 1, semicolon - i - 1);
            if (!ref.empty() && ref[0] == '#')
            {
                uint32_t cp = 0;
                const bool hex = ref.size() > 1 && (ref[1] == 'x' || ref[1] == 'X');
                const std::string_view digits = ref.substr(hex ? 2 : 1);
                auto result = std::from_chars(digits.data(), digits.data() + digits.size(), cp, hex ? 16 : 10);
                if (digits.empty() || result.ec != std::errc() || result.ptr != digits.data() + digits.size() ||
                    cp == 0 || cp > 0x10FFFF)
                    return fail(error, position + i, "a bad character reference");
                appendUtf8(out, cp);
            }
            else if (ref == "lt")
                out += '<';
            else if (ref == "gt")
                out += '>';
            else if (ref == "amp")
                out += '&';
            else if (ref == "quot")
                out += '"';
            else if (ref == "apos")
                out += '\'';
            else
            {
                auto entity = m_entities.find(std::string(ref));
                if (entity == m_entities.end())
                    return fail(error, position + i, "the entity &" + std::string(ref) + "; is not declared");
                // Counted before the text is copied: a short file must not
                // expand to gigabytes.
                if (entity->second.size() > kMaxEntityText - m_entityText)
                    return tooComplex(error, position + i,
                                      "its entity references add more than " + std::to_string(kMaxEntityText) +
                                          " bytes of text");
                m_entityText += entity->second.size();
                out += entity->second;
            }
            i = semicolon;
        }
        return true;
    }

    const std::string& m_text;
    std::unordered_map<std::string, std::string> m_entities;
    size_t m_entityText = 0; ///< bytes that entity references added so far
    size_t m_lessThanInText = 0; ///< every '<' of the text
    size_t m_lessThanSeen = 0; ///< each '<' that starts markup or is inside skipped markup
};

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

/// The style properties that the reader knows.
enum class Prop : uint8_t
{
    eUnknown,
    eClipPath,
    eClipRule,
    eColor,
    eDisplay,
    eFill,
    eFillOpacity,
    eFillRule,
    eFilter,
    eMarker,
    eMarkerEnd,
    eMarkerMid,
    eMarkerStart,
    eMask,
    eOpacity,
    eStopColor,
    eStopOpacity,
    eStroke,
    eStrokeDasharray,
    eStrokeDashoffset,
    eStrokeLinecap,
    eStrokeLinejoin,
    eStrokeMiterlimit,
    eStrokeOpacity,
    eStrokeWidth,
    eVisibility,
};

Prop propOf(std::string_view name)
{
    // By length first, so that only a few names are compared.
    switch (name.size())
    {
    case 4:
        return name == "fill" ? Prop::eFill : name == "mask" ? Prop::eMask : Prop::eUnknown;
    case 5:
        return name == "color" ? Prop::eColor : Prop::eUnknown;
    case 6:
        return name == "stroke" ? Prop::eStroke :
               name == "filter" ? Prop::eFilter :
               name == "marker" ? Prop::eMarker :
                                  Prop::eUnknown;
    case 7:
        return name == "opacity" ? Prop::eOpacity : name == "display" ? Prop::eDisplay : Prop::eUnknown;
    case 9:
        return name == "fill-rule" ? Prop::eFillRule :
               name == "clip-path" ? Prop::eClipPath :
               name == "clip-rule" ? Prop::eClipRule :
                                     Prop::eUnknown;
    case 10:
        return name == "stop-color" ? Prop::eStopColor :
               name == "visibility" ? Prop::eVisibility :
               name == "marker-end" ? Prop::eMarkerEnd :
               name == "marker-mid" ? Prop::eMarkerMid :
                                      Prop::eUnknown;
    case 12:
        return name == "stroke-width" ? Prop::eStrokeWidth :
               name == "fill-opacity" ? Prop::eFillOpacity :
               name == "stop-opacity" ? Prop::eStopOpacity :
               name == "marker-start" ? Prop::eMarkerStart :
                                        Prop::eUnknown;
    case 14:
        return name == "stroke-linecap" ? Prop::eStrokeLinecap :
               name == "stroke-opacity" ? Prop::eStrokeOpacity :
                                          Prop::eUnknown;
    case 15:
        return name == "stroke-linejoin" ? Prop::eStrokeLinejoin : Prop::eUnknown;
    case 16:
        return name == "stroke-dasharray" ? Prop::eStrokeDasharray : Prop::eUnknown;
    case 17:
        return name == "stroke-dashoffset" ? Prop::eStrokeDashoffset :
               name == "stroke-miterlimit" ? Prop::eStrokeMiterlimit :
                                             Prop::eUnknown;
    default:
        return Prop::eUnknown;
    }
}

struct Declaration
{
    Prop property = Prop::eUnknown;
    std::string value;
    bool important = false;
};

std::vector<Declaration> parseDeclarations(std::string_view text)
{
    std::vector<Declaration> out;
    size_t i = 0;
    while (i < text.size())
    {
        // Find the end of this declaration: a ';' outside parentheses and quotes.
        size_t end = i;
        int depth = 0;
        char quote = '\0';
        for (; end < text.size(); ++end)
        {
            const char c = text[end];
            if (quote)
            {
                if (c == quote)
                    quote = '\0';
            }
            else if (c == '"' || c == '\'')
                quote = c;
            else if (c == '(')
                ++depth;
            else if (c == ')')
                --depth;
            else if (c == ';' && depth <= 0)
                break;
        }
        const std::string_view item = text.substr(i, end - i);
        i = end + 1;
        const size_t colon = item.find(':');
        if (colon == std::string_view::npos)
            continue;
        Declaration d;
        d.property = propOf(toLower(trim(item.substr(0, colon))));
        std::string_view value = trim(item.substr(colon + 1));
        const size_t bang = value.rfind('!');
        if (bang != std::string_view::npos && equalsIgnoreCase(trim(value.substr(bang + 1)), "important"))
        {
            d.important = true;
            value = trim(value.substr(0, bang));
        }
        d.value = std::string(value);
        if (d.property != Prop::eUnknown)
            out.push_back(std::move(d));
    }
    return out;
}

struct SimpleSelector
{
    std::string type; ///< empty or "*": any element
    std::string id;
    std::vector<std::string> classes;
    char combinator = ' '; ///< how this part relates to the part on its left: ' ' or '>'
};

struct CssRule
{
    std::vector<SimpleSelector> parts; ///< left to right
    int specificity = 0;
    size_t order = 0;
    /// Shared by the selectors of one rule ("a, b { ... }").
    std::shared_ptr<const std::vector<Declaration>> declarations;
};

bool parseSelector(std::string_view text, CssRule& rule)
{
    text = trim(text);
    if (text.empty())
        return false;
    size_t i = 0;
    char combinator = ' ';
    int ids = 0, classes = 0, types = 0;
    while (i < text.size())
    {
        while (i < text.size() && isSpace(text[i]))
            ++i;
        if (i < text.size() && text[i] == '>')
        {
            combinator = '>';
            ++i;
            continue;
        }
        if (i >= text.size())
            break;
        SimpleSelector part;
        part.combinator = combinator;
        combinator = ' ';
        bool any = false;
        auto readIdent = [&](size_t& p) {
            const size_t s = p;
            while (p < text.size() && (isLetter(text[p]) || isDigit(text[p]) || text[p] == '-' || text[p] == '_' ||
                                       static_cast<unsigned char>(text[p]) >= 0x80))
                ++p;
            return std::string(text.substr(s, p - s));
        };
        if (text[i] == '*')
        {
            part.type = "*";
            ++i;
            any = true;
        }
        else if (isLetter(text[i]))
        {
            part.type = readIdent(i);
            ++types;
            any = true;
        }
        while (i < text.size() && (text[i] == '.' || text[i] == '#'))
        {
            const char kind = text[i++];
            const std::string name = readIdent(i);
            if (name.empty())
                return false;
            if (kind == '.')
            {
                part.classes.push_back(name);
                ++classes;
            }
            else
            {
                part.id = name;
                ++ids;
            }
            any = true;
        }
        if (!any)
            return false;
        if (i < text.size() && !isSpace(text[i]) && text[i] != '>')
            return false; // attribute selectors, pseudo-classes, '+' and '~' are not read
        rule.parts.push_back(std::move(part));
    }
    if (rule.parts.empty())
        return false;
    rule.specificity = ids * 10000 + classes * 100 + types;
    return true;
}

std::string stripCssComments(std::string_view text)
{
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); ++i)
    {
        if (text[i] == '/' && i + 1 < text.size() && text[i + 1] == '*')
        {
            const size_t end = text.find("*/", i + 2);
            if (end == std::string_view::npos)
                break;
            i = end + 1;
            continue;
        }
        out += text[i];
    }
    return out;
}

/// Reads a <style> sheet into `rules`. `pairs` counts the selector and
/// declaration pairs of all sheets (a selector with no declaration counts 1);
/// past kMaxCssPairs the file is refused before more rules are made.
void parseStyleSheet(std::string_view source,
                     std::vector<CssRule>& rules,
                     std::vector<std::string>& unsupported,
                     size_t& pairs)
{
    const std::string text = stripCssComments(source);
    size_t i = 0;
    while (i < text.size())
    {
        while (i < text.size() && (isSpace(text[i]) || text[i] == '}' || text[i] == ';'))
            ++i;
        if (i >= text.size())
            break;
        if (text[i] == '@')
        {
            // At-rules (@media, @font-face, @import, ...) are skipped with their block.
            const size_t semicolon = text.find(';', i);
            const size_t brace = text.find('{', i);
            if (brace == std::string::npos || (semicolon != std::string::npos && semicolon < brace))
            {
                i = semicolon == std::string::npos ? text.size() : semicolon + 1;
                continue;
            }
            int depth = 0;
            size_t p = brace;
            for (; p < text.size(); ++p)
            {
                if (text[p] == '{')
                    ++depth;
                else if (text[p] == '}' && --depth == 0)
                    break;
            }
            i = p + 1;
            continue;
        }
        const size_t brace = text.find('{', i);
        if (brace == std::string::npos)
            break;
        const size_t close = text.find('}', brace);
        const std::string_view selectors = std::string_view(text).substr(i, brace - i);
        const std::string_view body =
            std::string_view(text).substr(brace + 1, (close == std::string::npos ? text.size() : close) - brace - 1);
        const auto declarations = std::make_shared<const std::vector<Declaration>>(parseDeclarations(body));
        size_t s = 0;
        while (s <= selectors.size())
        {
            size_t comma = selectors.find(',', s);
            if (comma == std::string_view::npos)
                comma = selectors.size();
            CssRule rule;
            const std::string_view one = trim(selectors.substr(s, comma - s));
            if (parseSelector(one, rule))
            {
                pairs += std::max<size_t>(1, declarations->size());
                if (pairs > kMaxCssPairs)
                    throw LimitError("its <style> rules have more than " + std::to_string(kMaxCssPairs) +
                                     " selector and declaration pairs");
                rule.order = rules.size();
                rule.declarations = declarations;
                rules.push_back(std::move(rule));
            }
            else if (!one.empty())
            {
                unsupported.push_back("CSS selector '" + std::string(one) + "'");
            }
            s = comma + 1;
        }
        i = close == std::string::npos ? text.size() : close + 1;
    }
}

bool hasClass(const XmlElement& element, const std::string& name)
{
    const std::string_view* list = element.attribute("class");
    if (!list)
        return false;
    std::string_view rest(*list);
    while (!rest.empty())
    {
        while (!rest.empty() && isSpace(rest.front()))
            rest.remove_prefix(1);
        size_t end = 0;
        while (end < rest.size() && !isSpace(rest[end]))
            ++end;
        if (end > 0 && rest.substr(0, end) == name)
            return true;
        rest.remove_prefix(end);
    }
    return false;
}

bool matchesSimple(const SimpleSelector& part, const XmlElement& element)
{
    if (!part.type.empty() && part.type != "*" && part.type != element.name)
        return false;
    if (!part.id.empty())
    {
        const std::string_view* id = element.attribute("id");
        if (!id || *id != part.id)
            return false;
    }
    for (const std::string& name : part.classes)
    {
        if (!hasClass(element, name))
            return false;
    }
    return true;
}

/// Counts the work of the style computation of a file and refuses the file
/// past kMaxCssSteps.
struct CssSteps
{
    size_t count = 0;

    void add(size_t n)
    {
        count += n;
        if (count > kMaxCssSteps)
            throw LimitError("its styles need more than " + std::to_string(kMaxCssSteps) +
                             " selector tests and declarations");
    }
};

/// Matches the parts [first, last] of a rule, which are joined by '>', to a
/// chain of parents that ends at `bottom`. Returns the element of parts[first],
/// or nullptr.
const XmlElement* matchChain(const CssRule& rule, size_t first, size_t last, const XmlElement* bottom, CssSteps& steps)
{
    const XmlElement* e = bottom;
    for (size_t k = last + 1; k-- > first;)
    {
        if (!e)
            return nullptr;
        steps.add(1);
        if (!matchesSimple(rule.parts[k], *e))
            return nullptr;
        if (k > first)
            e = e->parent;
    }
    return e;
}

/// True when the rule matches the element. The parts are matched from the
/// right in chains of parts joined by '>'. The last chain must end at the
/// element; each chain on its left is matched at the nearest ancestor where
/// it matches. That nearest match is enough: it leaves the most ancestors for
/// the chains on its left. So each ancestor is tried at most once for each
/// chain, and the work grows with the depth, not with the ways the parts can
/// be placed.
bool matches(const CssRule& rule, const XmlElement& element, CssSteps& steps)
{
    size_t last = rule.parts.size() - 1;
    auto chainStart = [&](size_t end) {
        size_t start = end;
        while (start > 0 && rule.parts[start].combinator == '>')
            --start;
        return start;
    };
    size_t first = chainStart(last);
    const XmlElement* top = matchChain(rule, first, last, &element, steps);
    while (top && first > 0)
    {
        last = first - 1;
        first = chainStart(last);
        const XmlElement* found = nullptr;
        for (const XmlElement* bottom = top->parent; bottom && !found; bottom = bottom->parent)
            found = matchChain(rule, first, last, bottom, steps);
        top = found;
    }
    return top != nullptr;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

struct PaintValue
{
    enum class Kind
    {
        eNone,
        eColor,
        eCurrentColor,
        eUrl
    };
    Kind kind = Kind::eNone;
    Color color;
    std::string url; ///< the id, for eUrl
    Kind fallbackKind = Kind::eNone; ///< for eUrl: eNone, eColor or eCurrentColor
    Color fallbackColor;
};

bool parsePaint(std::string_view text, PaintValue& out)
{
    text = trim(text);
    if (text == "none")
    {
        out = PaintValue{};
        return true;
    }
    if (equalsIgnoreCase(text, "currentColor"))
    {
        out = PaintValue{};
        out.kind = PaintValue::Kind::eCurrentColor;
        return true;
    }
    if (startsWith(text, "url("))
    {
        const size_t close = text.find(')');
        if (close == std::string_view::npos)
            return false;
        std::string_view ref = trim(text.substr(4, close - 4));
        if (!ref.empty() && (ref.front() == '"' || ref.front() == '\'') && ref.size() >= 2)
            ref = ref.substr(1, ref.size() - 2);
        PaintValue value;
        value.kind = PaintValue::Kind::eUrl;
        value.url = std::string(ref.size() > 0 && ref.front() == '#' ? ref.substr(1) : ref);
        const std::string_view fallback = trim(text.substr(close + 1));
        if (fallback == "none" || fallback.empty())
            value.fallbackKind = PaintValue::Kind::eNone;
        else if (equalsIgnoreCase(fallback, "currentColor"))
            value.fallbackKind = PaintValue::Kind::eCurrentColor;
        else if (parseColor(fallback, value.fallbackColor))
            value.fallbackKind = PaintValue::Kind::eColor;
        else
            return false;
        out = value;
        return true;
    }
    Color c;
    if (!parseColor(text, c))
        return false;
    out = PaintValue{};
    out.kind = PaintValue::Kind::eColor;
    out.color = c;
    return true;
}

/// The computed style of one element. The first block is inherited by the
/// children; the second block is not.
struct Style
{
    PaintValue fill;
    PaintValue stroke;
    float fillOpacity = 1.0f;
    float strokeOpacity = 1.0f;
    FillRule fillRule = FillRule::eNonZero;
    FillRule clipRule = FillRule::eNonZero;
    Length strokeWidth{ 1.0, false };
    LineCap lineCap = LineCap::eButt;
    LineJoin lineJoin = LineJoin::eMiter;
    double miterLimit = 4.0;
    std::vector<Length> dashArray;
    Length dashOffset;
    Color color{ 0.0f, 0.0f, 0.0f, 1.0f };
    bool visible = true;
    bool markers = false;

    float opacity = 1.0f;
    bool display = true;
    std::string clipPath; ///< the id of url(#id)
    Color stopColor{ 0.0f, 0.0f, 0.0f, 1.0f };
    bool stopColorIsCurrent = false;
    float stopOpacity = 1.0f;
    bool mask = false;
    bool filter = false;

    Style()
    {
        fill.kind = PaintValue::Kind::eColor; // black
    }

    /// The style a child starts from: the inherited properties of this one.
    Style inherited() const
    {
        Style s;
        s.fill = fill;
        s.stroke = stroke;
        s.fillOpacity = fillOpacity;
        s.strokeOpacity = strokeOpacity;
        s.fillRule = fillRule;
        s.clipRule = clipRule;
        s.strokeWidth = strokeWidth;
        s.lineCap = lineCap;
        s.lineJoin = lineJoin;
        s.miterLimit = miterLimit;
        s.dashArray = dashArray;
        s.dashOffset = dashOffset;
        s.color = color;
        s.visible = visible;
        s.markers = markers;
        return s;
    }
};

bool parseOpacity(std::string_view text, float& out)
{
    text = trim(text);
    NumberReader reader(text);
    double v = 0.0;
    if (!reader.number(v))
        return false;
    const std::string_view rest = reader.rest();
    if (rest == "%")
        v /= 100.0;
    else if (!rest.empty())
        return false;
    out = clamp01(v);
    return true;
}

std::string parseUrlId(std::string_view text)
{
    text = trim(text);
    if (!startsWith(text, "url("))
        return {};
    const size_t close = text.find(')');
    if (close == std::string_view::npos)
        return {};
    std::string_view ref = trim(text.substr(4, close - 4));
    if (ref.size() >= 2 && (ref.front() == '"' || ref.front() == '\''))
        ref = ref.substr(1, ref.size() - 2);
    if (!ref.empty() && ref.front() == '#')
        ref.remove_prefix(1);
    return std::string(ref);
}

/// Applies one property to `style`. `parent` gives the value of "inherit".
/// An unknown property or a value that does not parse changes nothing.
void applyProperty(Style& style, const Style& parent, Prop prop, std::string_view value)
{
    value = trim(value);
    const bool inherit = value == "inherit";
    if (prop == Prop::eFill)
    {
        if (inherit)
            style.fill = parent.fill;
        else
            parsePaint(value, style.fill);
    }
    else if (prop == Prop::eStroke)
    {
        if (inherit)
            style.stroke = parent.stroke;
        else
            parsePaint(value, style.stroke);
    }
    else if (prop == Prop::eFillOpacity)
    {
        if (inherit)
            style.fillOpacity = parent.fillOpacity;
        else
            parseOpacity(value, style.fillOpacity);
    }
    else if (prop == Prop::eStrokeOpacity)
    {
        if (inherit)
            style.strokeOpacity = parent.strokeOpacity;
        else
            parseOpacity(value, style.strokeOpacity);
    }
    else if (prop == Prop::eOpacity)
    {
        if (inherit)
            style.opacity = parent.opacity;
        else
            parseOpacity(value, style.opacity);
    }
    else if (prop == Prop::eFillRule || prop == Prop::eClipRule)
    {
        FillRule& rule = prop == Prop::eFillRule ? style.fillRule : style.clipRule;
        if (inherit)
            rule = prop == Prop::eFillRule ? parent.fillRule : parent.clipRule;
        else if (value == "nonzero")
            rule = FillRule::eNonZero;
        else if (value == "evenodd")
            rule = FillRule::eEvenOdd;
    }
    else if (prop == Prop::eStrokeWidth)
    {
        Length l;
        if (inherit)
            style.strokeWidth = parent.strokeWidth;
        else if (parseLength(value, l) && l.value >= 0.0)
            style.strokeWidth = l;
    }
    else if (prop == Prop::eStrokeLinecap)
    {
        if (inherit)
            style.lineCap = parent.lineCap;
        else if (value == "butt")
            style.lineCap = LineCap::eButt;
        else if (value == "round")
            style.lineCap = LineCap::eRound;
        else if (value == "square")
            style.lineCap = LineCap::eSquare;
    }
    else if (prop == Prop::eStrokeLinejoin)
    {
        if (inherit)
            style.lineJoin = parent.lineJoin;
        else if (value == "miter" || value == "miter-clip" || value == "arcs")
            style.lineJoin = LineJoin::eMiter;
        else if (value == "round")
            style.lineJoin = LineJoin::eRound;
        else if (value == "bevel")
            style.lineJoin = LineJoin::eBevel;
    }
    else if (prop == Prop::eStrokeMiterlimit)
    {
        double v = 0.0;
        NumberReader reader(value);
        if (inherit)
            style.miterLimit = parent.miterLimit;
        else if (reader.number(v) && reader.atEnd() && v >= 1.0)
            style.miterLimit = v;
    }
    else if (prop == Prop::eStrokeDasharray)
    {
        if (inherit)
        {
            style.dashArray = parent.dashArray;
            return;
        }
        if (value == "none")
        {
            style.dashArray.clear();
            return;
        }
        std::vector<Length> dashes;
        size_t i = 0;
        while (i < value.size())
        {
            while (i < value.size() && (isSpace(value[i]) || value[i] == ','))
                ++i;
            size_t end = i;
            while (end < value.size() && !isSpace(value[end]) && value[end] != ',')
                ++end;
            if (end == i)
                break;
            Length l;
            if (!parseLength(value.substr(i, end - i), l) || l.value < 0.0)
                return; // a bad list is ignored
            dashes.push_back(l);
            i = end;
        }
        style.dashArray = std::move(dashes);
    }
    else if (prop == Prop::eStrokeDashoffset)
    {
        Length l;
        if (inherit)
            style.dashOffset = parent.dashOffset;
        else if (parseLength(value, l))
            style.dashOffset = l;
    }
    else if (prop == Prop::eColor)
    {
        Color c;
        if (inherit || equalsIgnoreCase(value, "currentColor"))
            style.color = parent.color;
        else if (parseColor(value, c))
            style.color = c;
    }
    else if (prop == Prop::eDisplay)
    {
        style.display = inherit ? parent.display : value != "none";
    }
    else if (prop == Prop::eVisibility)
    {
        if (inherit)
            style.visible = parent.visible;
        else if (value == "visible")
            style.visible = true;
        else if (value == "hidden" || value == "collapse")
            style.visible = false;
    }
    else if (prop == Prop::eStopColor)
    {
        Color c;
        if (inherit)
        {
            style.stopColor = parent.stopColor;
            style.stopColorIsCurrent = parent.stopColorIsCurrent;
        }
        else if (equalsIgnoreCase(value, "currentColor"))
            style.stopColorIsCurrent = true;
        else if (parseColor(value, c))
        {
            style.stopColor = c;
            style.stopColorIsCurrent = false;
        }
    }
    else if (prop == Prop::eStopOpacity)
    {
        if (inherit)
            style.stopOpacity = parent.stopOpacity;
        else
            parseOpacity(value, style.stopOpacity);
    }
    else if (prop == Prop::eClipPath)
    {
        style.clipPath = inherit ? parent.clipPath : parseUrlId(value);
    }
    else if (prop == Prop::eMask)
    {
        style.mask = inherit ? parent.mask : (value != "none" && !value.empty());
    }
    else if (prop == Prop::eFilter)
    {
        style.filter = inherit ? parent.filter : (value != "none" && !value.empty());
    }
    else if (prop == Prop::eMarkerStart || prop == Prop::eMarkerMid || prop == Prop::eMarkerEnd || prop == Prop::eMarker)
    {
        style.markers = inherit ? parent.markers : (value != "none" && !value.empty());
    }
}

/// The property of a presentation attribute; eUnknown for other attributes.
/// The shorthand "marker" is a CSS property only.
Prop presentationAttribute(std::string_view name)
{
    const Prop prop = propOf(name);
    return prop == Prop::eMarker ? Prop::eUnknown : prop;
}

// ---------------------------------------------------------------------------
// The SVG reader
// ---------------------------------------------------------------------------

struct PreserveAspectRatio
{
    bool none = false;
    int alignX = 1; // 0 min, 1 mid, 2 max
    int alignY = 1;
    bool slice = false;
};

PreserveAspectRatio parsePreserveAspectRatio(const std::string_view* text)
{
    PreserveAspectRatio par;
    if (!text)
        return par;
    std::string_view rest = trim(*text);
    if (startsWith(rest, "defer"))
        rest = trim(rest.substr(5));
    const size_t space = rest.find_first_of(" \t\r\n");
    const std::string_view align = rest.substr(0, space);
    const std::string_view meetOrSlice = space == std::string_view::npos ? std::string_view() : trim(rest.substr(space));
    if (align == "none")
    {
        par.none = true;
        return par;
    }
    if (align.size() == 8 && align[0] == 'x' && align[4] == 'Y')
    {
        auto axis = [](std::string_view v) { return v == "Min" ? 0 : v == "Max" ? 2 : 1; };
        par.alignX = axis(align.substr(1, 3));
        par.alignY = axis(align.substr(5, 3));
    }
    par.slice = meetOrSlice == "slice";
    return par;
}

/// Maps the viewBox (vx, vy, vw, vh) into a viewport of width x height.
Transform viewBoxTransform(double vx, double vy, double vw, double vh, double width, double height,
                           const PreserveAspectRatio& par)
{
    const double sx = width / vw;
    const double sy = height / vh;
    if (par.none)
        return Transform::scale(sx, sy) * Transform::translate(-vx, -vy);
    const double s = par.slice ? std::max(sx, sy) : std::min(sx, sy);
    double tx = -vx * s;
    double ty = -vy * s;
    tx += (width - vw * s) * 0.5 * par.alignX;
    ty += (height - vh * s) * 0.5 * par.alignY;
    return Transform::translate(tx, ty) * Transform::scale(s, s);
}

bool parseViewBox(const std::string_view* text, double v[4])
{
    if (!text)
        return false;
    NumberReader reader(*text);
    for (int i = 0; i < 4; ++i)
    {
        if (!reader.number(v[i]))
            return false;
        reader.skipSeparator();
    }
    return reader.atEnd() && v[2] > 0.0 && v[3] > 0.0;
}

class SvgReader
{
public:
    SvgReader(const XmlElement& root, Document& doc) : m_root(root), m_doc(doc)
    {
        index(root);
    }

    bool read(std::string& error)
    {
        if (m_root.tag != Tag::eSvg)
        {
            error = "the file is not an SVG (its root element is not <svg>)";
            return false;
        }
        double viewBox[4];
        const bool hasViewBox = parseViewBox(m_root.attribute("viewBox"), viewBox);
        Length width, height;
        const bool hasWidth = readLength(m_root, "width", width) && !width.percent;
        const bool hasHeight = readLength(m_root, "height", height) && !height.percent;
        double w = hasWidth ? width.value : 0.0;
        double h = hasHeight ? height.value : 0.0;
        if (hasViewBox)
        {
            if (!hasWidth && !hasHeight)
            {
                w = viewBox[2];
                h = viewBox[3];
            }
            else if (!hasWidth)
                w = h * viewBox[2] / viewBox[3];
            else if (!hasHeight)
                h = w * viewBox[3] / viewBox[2];
        }
        if (!(w > 0.0) || !(h > 0.0) || !std::isfinite(w) || !std::isfinite(h))
        {
            error = "the SVG has no size (no width, height or viewBox)";
            return false;
        }
        m_doc.width = w;
        m_doc.height = h;

        // <style> sheets of the whole file, in document order.
        collectStyleSheets(m_root);

        Viewport viewport{ w, h };
        Transform rootTransform;
        if (hasViewBox)
        {
            rootTransform = viewBoxTransform(viewBox[0], viewBox[1], viewBox[2], viewBox[3], w, h,
                                             parsePreserveAspectRatio(m_root.attribute("preserveAspectRatio")));
            viewport = Viewport{ viewBox[2], viewBox[3] };
        }
        const Style rootStyle = computeStyle(m_root, Style());
        m_doc.root.isGroup = true;
        m_doc.root.transform = rootTransform;
        m_doc.root.opacity = rootStyle.display ? rootStyle.opacity : 0.0f;
        countNode(0);
        if (rootStyle.display)
        {
            // The same parts are reported for the root as for its children.
            skipUnsupportedEffects(m_root, rootStyle);
            applyClip(m_doc.root, rootStyle, viewport);
            readChildren(m_root, rootStyle, viewport, m_doc.root.children, 0);
        }
        return true;
    }

private:
    void index(const XmlElement& element)
    {
        if (const std::string_view* id = element.attribute("id"))
            m_ids.emplace(*id, &element);
        for (const XmlElement& child : element.children())
            index(child);
    }

    void skip(const std::string& what)
    {
        if (m_skipped.insert(what).second)
            m_doc.skipped.push_back(what);
    }

    void changed(const std::string& what)
    {
        if (std::find(m_doc.changed.begin(), m_doc.changed.end(), what) == m_doc.changed.end())
            m_doc.changed.push_back(what);
    }

    /// Reports the parts of an element's style and attributes that are not
    /// drawn: masks, filters, and a transform on an <svg> element.
    void skipUnsupportedEffects(const XmlElement& element, const Style& style)
    {
        if (style.mask || style.filter || element.tag == Tag::eSvg)
            reportUnsupportedEffects(element, style);
    }

    OVUI_SVG_NOINLINE void reportUnsupportedEffects(const XmlElement& element, const Style& style)
    {
        if (style.mask)
            skip("mask");
        if (style.filter)
            skip("filter");
        if (element.tag == Tag::eSvg && element.attribute("transform"))
            skip("transform on <svg>");
    }

    /// Counts one more group or shape of the drawing with `points` path
    /// points, before it is made, and refuses the file past the limits.
    void countNode(size_t points)
    {
        if (++m_nodes > kMaxNodes || points > kMaxPathPoints - m_points)
            refuseNode();
        m_points += points;
    }

    [[noreturn]] OVUI_SVG_NOINLINE void refuseNode() const
    {
        if (m_nodes > kMaxNodes)
            throw LimitError("it has more than " + std::to_string(kMaxNodes) +
                             " groups and shapes when its <use> references are followed");
        throw LimitError("it has more than " + std::to_string(kMaxPathPoints) +
                         " path points when its <use> references are followed");
    }

    void collectStyleSheets(const XmlElement& element)
    {
        if (element.tag == Tag::eStyle)
        {
            const std::string_view* type = element.attribute("type");
            if (!type || trim(*type).empty() || trim(*type) == "text/css")
            {
                std::vector<std::string> unsupported;
                parseStyleSheet(element.text, m_rules, unsupported, m_cssPairs);
                for (const std::string& what : unsupported)
                    skip(what);
            }
        }
        for (const XmlElement& child : element.children())
            collectStyleSheets(child);
    }

    static bool readLength(const XmlElement& element, const char* name, Length& out)
    {
        const std::string_view* text = element.attribute(name);
        return text && parseLength(*text, out);
    }

    static double lengthAttribute(const XmlElement& element, const char* name, const Viewport& viewport, Axis axis,
                                  double fallback)
    {
        Length l;
        if (!readLength(element, name, l))
            return fallback;
        return viewport.resolve(l, axis);
    }

    Style computeStyle(const XmlElement& element, const Style& parent) const
    {
        Style style = parent.inherited();
        for (size_t i = 0; i < element.attributeCount; ++i)
        {
            const XmlAttribute& attribute = element.attributes[i];
            const Prop prop = presentationAttribute(attribute.name);
            if (prop != Prop::eUnknown)
                applyProperty(style, parent, prop, attribute.value);
        }
        const std::string_view* inlineStyle = element.attribute("style");
        if (m_rules.empty() && !inlineStyle)
            return style;
        // Declarations of the sheets and the style attribute, in cascade order.
        struct Ranked
        {
            int level;
            int specificity;
            size_t order;
            const Declaration* declaration;
        };
        std::vector<Ranked> ranked;
        size_t sequence = 0;
        for (const CssRule& rule : m_rules)
        {
            if (!matches(rule, element, m_cssSteps))
                continue;
            m_cssSteps.add(rule.declarations->size());
            for (const Declaration& d : *rule.declarations)
                ranked.push_back({ d.important ? 3 : 1, rule.specificity, sequence++, &d });
        }
        std::vector<Declaration> inlineDeclarations;
        if (inlineStyle)
        {
            // The parse, the sort and the apply of the style attribute all grow
            // with its length, which is charged before the work is done. A
            // <use> that repeats an element with a big style attribute is bound
            // by this, as a <style> sheet is by its rules.
            m_cssSteps.add(inlineStyle->size());
            inlineDeclarations = parseDeclarations(*inlineStyle);
        }
        for (const Declaration& d : inlineDeclarations)
            ranked.push_back({ d.important ? 4 : 2, 0, sequence++, &d });
        std::stable_sort(ranked.begin(), ranked.end(), [](const Ranked& a, const Ranked& b) {
            if (a.level != b.level)
                return a.level < b.level;
            if (a.specificity != b.specificity)
                return a.specificity < b.specificity;
            return a.order < b.order;
        });
        for (const Ranked& r : ranked)
            applyProperty(style, parent, r.declaration->property, r.declaration->value);
        return style;
    }

    /// The style of an element where it is in the file: computed from the root
    /// through each of its ancestors. The stops of a gradient and the shapes of
    /// a clip path inherit from their own ancestors (the gradient or clip path,
    /// its <defs>, the root), not from the element that uses them.
    const Style& documentStyle(const XmlElement& element)
    {
        // Kept for each element: many shapes can use one clip path. The map
        // is made when a file first needs it.
        if (!m_documentStyles)
            m_documentStyles = std::make_unique<std::unordered_map<const XmlElement*, Style>>();
        auto cached = m_documentStyles->find(&element);
        if (cached != m_documentStyles->end())
            return cached->second;
        std::vector<const XmlElement*> path;
        for (const XmlElement* e = &element; e; e = e->parent)
            path.push_back(e);
        Style style;
        for (auto it = path.rbegin(); it != path.rend(); ++it)
            style = computeStyle(**it, style);
        return m_documentStyles->emplace(&element, std::move(style)).first->second;
    }

    static Transform elementTransform(const XmlElement& element)
    {
        Transform t;
        if (const std::string_view* text = element.attribute("transform"))
            parseTransformList(*text, t);
        return t;
    }

    const XmlElement* lookup(std::string_view id) const
    {
        auto it = m_ids.find(id);
        return it == m_ids.end() ? nullptr : it->second;
    }

    static const std::string_view* href(const XmlElement& element)
    {
        if (const std::string_view* h = element.attribute("href"))
            return h;
        return element.attribute("xlink:href");
    }

    const XmlElement* hrefTarget(const XmlElement& element)
    {
        const std::string_view* h = href(element);
        if (!h)
            return nullptr;
        const std::string_view ref = trim(*h);
        if (ref.empty() || ref.front() != '#')
        {
            if (!ref.empty())
                skip("a reference to another file");
            return nullptr;
        }
        return lookup(std::string(ref.substr(1)));
    }

    void readChildren(const XmlElement& element, const Style& style, const Viewport& viewport, std::vector<Node>& out,
                      int depth)
    {
        if (element.tag == Tag::eSwitch)
        {
            // A <switch> draws its first child that can be drawn.
            for (const XmlElement& child : element.children())
            {
                const size_t before = out.size();
                readElement(child, style, viewport, out, depth);
                if (out.size() > before)
                    break;
            }
            return;
        }
        out.reserve(out.size() + element.childCount);
        for (const XmlElement& child : element.children())
            readElement(child, style, viewport, out, depth);
    }

    /// Reads one element into `out`. `depth` is the number of groups, <svg>
    /// and <use> elements around it in the drawing.
    void readElement(const XmlElement& element, const Style& parentStyle, const Viewport& viewport,
                     std::vector<Node>& out, int depth)
    {
        const std::string_view name = element.name;
        const Tag tag = element.tag;
        if (tag == Tag::eOther || tag == Tag::eDefs || tag == Tag::eSymbol || tag == Tag::eClipPath ||
            tag == Tag::eLinearGradient || tag == Tag::eRadialGradient || tag == Tag::eStyle || tag == Tag::eTitle ||
            tag == Tag::eDesc || tag == Tag::eMetadata || tag == Tag::eMask || tag == Tag::ePattern ||
            tag == Tag::eMarker || tag == Tag::eFilter || tag == Tag::eStop)
            return;
        if (tag == Tag::eText || tag == Tag::eImage || tag == Tag::eForeignObject)
        {
            skip("<" + std::string(name) + ">");
            return;
        }
        if (depth >= kMaxDrawingDepth)
        {
            skip("parts nested deeper than " + std::to_string(kMaxDrawingDepth) +
                 " levels of groups, <svg> and <use> references (the depth limit)");
            return;
        }
        const Style style = computeStyle(element, parentStyle);
        if (!style.display)
            return;
        skipUnsupportedEffects(element, style);

        if (tag == Tag::eG || tag == Tag::eA || tag == Tag::eSwitch)
        {
            countNode(0);
            Node group;
            group.isGroup = true;
            group.transform = elementTransform(element);
            group.opacity = style.opacity;
            readChildren(element, style, viewport, group.children, depth + 1);
            if (group.children.empty())
                return;
            applyClip(group, style, viewport);
            out.push_back(std::move(group));
            return;
        }
        if (tag == Tag::eSvg)
        {
            readNestedViewport(lengthAttribute(element, "x", viewport, Axis::eX, 0.0),
                               lengthAttribute(element, "y", viewport, Axis::eY, 0.0),
                               lengthAttribute(element, "width", viewport, Axis::eX, viewport.width),
                               lengthAttribute(element, "height", viewport, Axis::eY, viewport.height), element, style,
                               viewport, out, depth, Transform());
            return;
        }
        if (tag == Tag::eUse)
        {
            readUse(element, style, viewport, out, depth);
            return;
        }

        Path path;
        if (!readShape(element, viewport, path))
            return;
        countNode(path.points.size());
        ++m_doc.shapeCount;
        if (path.empty() || !style.visible)
            return;
        if (style.markers)
            skip("markers");

        Node shape;
        shape.path = std::move(path);
        shape.fill = resolvePaint(style.fill, style, viewport);
        shape.fillOpacity = style.fillOpacity;
        shape.fillRule = style.fillRule;
        shape.stroke.paint = resolvePaint(style.stroke, style, viewport);
        shape.stroke.opacity = style.strokeOpacity;
        shape.stroke.width = viewport.resolve(style.strokeWidth, Axis::eOther);
        shape.stroke.cap = style.lineCap;
        shape.stroke.join = style.lineJoin;
        shape.stroke.miterLimit = style.miterLimit;
        double dashTotal = 0.0;
        for (const Length& l : style.dashArray)
        {
            shape.stroke.dashes.push_back(viewport.resolve(l, Axis::eOther));
            dashTotal += shape.stroke.dashes.back();
        }
        if (!(dashTotal > 0.0))
            shape.stroke.dashes.clear();
        else if (shape.stroke.dashes.size() % 2 == 1)
            shape.stroke.dashes.insert(shape.stroke.dashes.end(), shape.stroke.dashes.begin(), shape.stroke.dashes.end());
        shape.stroke.dashOffset = viewport.resolve(style.dashOffset, Axis::eOther);
        if (!(shape.stroke.width > 0.0))
            shape.stroke.paint = Paint{};

        const Transform transform = elementTransform(element);
        const bool hasFill = shape.fill.kind != Paint::Kind::eNone;
        const bool hasStroke = shape.stroke.paint.kind != Paint::Kind::eNone;
        if (!hasFill && !hasStroke)
            return;
        const bool clipped = !style.clipPath.empty();
        if (style.opacity < 1.0f && !(hasFill && hasStroke))
        {
            // One paint only: the opacity is the same as a lower paint opacity.
            shape.fillOpacity *= style.opacity;
            shape.stroke.opacity *= style.opacity;
        }
        else if (style.opacity < 1.0f || clipped)
        {
            countNode(0);
            Node group;
            group.isGroup = true;
            group.transform = transform;
            group.opacity = style.opacity;
            applyClip(group, style, viewport, &shape.path);
            group.children.push_back(std::move(shape));
            out.push_back(std::move(group));
            return;
        }
        if (clipped)
        {
            Node group;
            group.isGroup = true;
            group.transform = transform;
            applyClip(group, style, viewport, &shape.path);
            group.children.push_back(std::move(shape));
            out.push_back(std::move(group));
            return;
        }
        shape.transform = transform;
        out.push_back(std::move(shape));
    }

    /// <svg> inside the file, or a <symbol> or <svg> that a <use> draws.
    void readNestedViewport(double x, double y, double w, double h, const XmlElement& contentElement,
                            const Style& style, const Viewport& viewport, std::vector<Node>& out, int depth,
                            const Transform& outer)
    {
        if (!(w > 0.0) || !(h > 0.0))
            return;
        countNode(0);
        countNode(5); // the clip group and its rectangle
        Node group;
        group.isGroup = true;
        group.opacity = style.opacity;
        double viewBox[4];
        Viewport inner{ w, h };
        Transform t = outer * Transform::translate(x, y);
        if (parseViewBox(contentElement.attribute("viewBox"), viewBox))
        {
            t = t * viewBoxTransform(viewBox[0], viewBox[1], viewBox[2], viewBox[3], w, h,
                                     parsePreserveAspectRatio(contentElement.attribute("preserveAspectRatio")));
            inner = Viewport{ viewBox[2], viewBox[3] };
        }
        group.transform = t;
        readChildren(contentElement, style, inner, group.children, depth + 1);
        if (group.children.empty())
            return;
        // A nested viewport clips its content to its own rectangle.
        Node clipGroup;
        clipGroup.isGroup = true;
        ClipShape box;
        box.path.moveTo({ x, y });
        box.path.lineTo({ x + w, y });
        box.path.lineTo({ x + w, y + h });
        box.path.lineTo({ x, y + h });
        box.path.close();
        box.transform = outer;
        clipGroup.clip.push_back(std::move(box));
        applyClip(group, style, viewport);
        clipGroup.children.push_back(std::move(group));
        out.push_back(std::move(clipGroup));
    }

    void readUse(const XmlElement& element, const Style& style, const Viewport& viewport, std::vector<Node>& out,
                 int depth)
    {
        const XmlElement* target = hrefTarget(element);
        if (!target)
            return;
        if (std::find(m_useStack.begin(), m_useStack.end(), target) != m_useStack.end())
        {
            skip("a <use> that refers to itself");
            return;
        }
        for (const XmlElement* a = element.parent; a; a = a->parent)
        {
            if (a == target)
            {
                skip("a <use> that refers to itself");
                return;
            }
        }
        m_useStack.push_back(target);
        const double x = lengthAttribute(element, "x", viewport, Axis::eX, 0.0);
        const double y = lengthAttribute(element, "y", viewport, Axis::eY, 0.0);
        countNode(0);
        Node group;
        group.isGroup = true;
        group.transform = elementTransform(element) * Transform::translate(x, y);
        group.opacity = style.opacity;
        if (target->tag == Tag::eSymbol || target->tag == Tag::eSvg)
        {
            // The width and height of the <use> override those of the symbol.
            const bool useHasSize = element.attribute("width") || element.attribute("height");
            const XmlElement& sizeSource = useHasSize ? element : *target;
            const Style targetStyle = computeStyle(*target, style);
            if (targetStyle.display)
            {
                skipUnsupportedEffects(*target, targetStyle);
                const double w = lengthAttribute(sizeSource, "width", viewport, Axis::eX, viewport.width);
                const double h = lengthAttribute(sizeSource, "height", viewport, Axis::eY, viewport.height);
                readNestedViewport(0.0, 0.0, w, h, *target, targetStyle, viewport, group.children, depth + 1, Transform());
            }
        }
        else
        {
            readElement(*target, style, viewport, group.children, depth + 1);
        }
        m_useStack.pop_back();
        if (group.children.empty())
            return;
        applyClip(group, style, viewport);
        out.push_back(std::move(group));
    }

    bool readShape(const XmlElement& element, const Viewport& viewport, Path& path)
    {
        const Tag tag = element.tag;
        if (tag == Tag::ePath)
        {
            if (const std::string_view* d = element.attribute("d"))
            {
                path.verbs.reserve(d->size() / 4 + 2);
                path.points.reserve(d->size() / 3 + 2);
                if (!parsePathData(*d, path))
                    changed("a <path> whose data has an error is drawn up to the error");
            }
            return true;
        }
        if (tag == Tag::eRect)
        {
            const double x = lengthAttribute(element, "x", viewport, Axis::eX, 0.0);
            const double y = lengthAttribute(element, "y", viewport, Axis::eY, 0.0);
            const double w = lengthAttribute(element, "width", viewport, Axis::eX, 0.0);
            const double h = lengthAttribute(element, "height", viewport, Axis::eY, 0.0);
            if (!(w > 0.0) || !(h > 0.0))
                return true;
            path.verbs.reserve(14);
            path.points.reserve(30);
            Length l;
            const bool hasRx = readLength(element, "rx", l) && l.value >= 0.0;
            double rx = hasRx ? viewport.resolve(l, Axis::eX) : 0.0;
            const bool hasRy = readLength(element, "ry", l) && l.value >= 0.0;
            double ry = hasRy ? viewport.resolve(l, Axis::eY) : 0.0;
            if (hasRx && !hasRy)
                ry = rx;
            else if (hasRy && !hasRx)
                rx = ry;
            rx = std::min(rx, w / 2.0);
            ry = std::min(ry, h / 2.0);
            if (rx > 0.0 && ry > 0.0)
            {
                path.moveTo({ x + rx, y });
                path.lineTo({ x + w - rx, y });
                addEllipseOctants(path, x + w - rx, y + ry, rx, ry, 6, 2);
                path.lineTo({ x + w, y + h - ry });
                addEllipseOctants(path, x + w - rx, y + h - ry, rx, ry, 0, 2);
                path.lineTo({ x + rx, y + h });
                addEllipseOctants(path, x + rx, y + h - ry, rx, ry, 2, 2);
                path.lineTo({ x, y + ry });
                addEllipseOctants(path, x + rx, y + ry, rx, ry, 4, 2);
            }
            else
            {
                path.moveTo({ x, y });
                path.lineTo({ x + w, y });
                path.lineTo({ x + w, y + h });
                path.lineTo({ x, y + h });
            }
            path.close();
            return true;
        }
        if (tag == Tag::eCircle || tag == Tag::eEllipse)
        {
            const double cx = lengthAttribute(element, "cx", viewport, Axis::eX, 0.0);
            const double cy = lengthAttribute(element, "cy", viewport, Axis::eY, 0.0);
            double rx, ry;
            if (tag == Tag::eCircle)
            {
                rx = ry = lengthAttribute(element, "r", viewport, Axis::eOther, 0.0);
            }
            else
            {
                Length l;
                const bool hasRx = readLength(element, "rx", l);
                rx = hasRx ? viewport.resolve(l, Axis::eX) : 0.0;
                const bool hasRy = readLength(element, "ry", l);
                ry = hasRy ? viewport.resolve(l, Axis::eY) : 0.0;
                if (hasRx && !hasRy)
                    ry = rx;
                else if (hasRy && !hasRx)
                    rx = ry;
            }
            if (!(rx > 0.0) || !(ry > 0.0))
                return true;
            path.verbs.reserve(10);
            path.points.reserve(25);
            path.moveTo({ cx + rx, cy });
            addEllipseOctants(path, cx, cy, rx, ry, 0, 8);
            path.close();
            return true;
        }
        if (tag == Tag::eLine)
        {
            const double x1 = lengthAttribute(element, "x1", viewport, Axis::eX, 0.0);
            const double y1 = lengthAttribute(element, "y1", viewport, Axis::eY, 0.0);
            const double x2 = lengthAttribute(element, "x2", viewport, Axis::eX, 0.0);
            const double y2 = lengthAttribute(element, "y2", viewport, Axis::eY, 0.0);
            path.moveTo({ x1, y1 });
            path.lineTo({ x2, y2 });
            return true;
        }
        if (tag == Tag::ePolyline || tag == Tag::ePolygon)
        {
            const std::string_view* points = element.attribute("points");
            if (!points)
                return true;
            const std::vector<double> v = parseNumberList(*points);
            for (size_t i = 0; i + 1 < v.size(); i += 2)
            {
                if (i == 0)
                    path.moveTo({ v[0], v[1] });
                else
                    path.lineTo({ v[i], v[i + 1] });
            }
            if (tag == Tag::ePolygon && !path.empty())
                path.close();
            return true;
        }
        return false;
    }

    Paint resolvePaint(const PaintValue& value, const Style& style, const Viewport& viewport)
    {
        Paint paint;
        auto solid = [&](PaintValue::Kind kind, const Color& color) {
            Paint p;
            if (kind == PaintValue::Kind::eColor)
            {
                p.kind = Paint::Kind::eColor;
                p.color = color;
            }
            else if (kind == PaintValue::Kind::eCurrentColor)
            {
                p.kind = Paint::Kind::eColor;
                p.color = style.color;
            }
            return p;
        };
        switch (value.kind)
        {
        case PaintValue::Kind::eNone:
            return paint;
        case PaintValue::Kind::eColor:
        case PaintValue::Kind::eCurrentColor:
            return solid(value.kind, value.color);
        case PaintValue::Kind::eUrl:
            break;
        }
        const XmlElement* target = lookup(value.url);
        if (target && (target->tag == Tag::eLinearGradient || target->tag == Tag::eRadialGradient))
        {
            auto gradient = readGradient(*target, viewport);
            if (gradient->stops.empty())
                return paint; // no stops: nothing is painted
            if (gradient->stops.size() == 1)
            {
                paint.kind = Paint::Kind::eColor;
                paint.color = gradient->stops[0].color;
                return paint;
            }
            paint.kind = Paint::Kind::eGradient;
            paint.gradient = std::move(gradient);
            return paint;
        }
        if (target && target->tag == Tag::ePattern)
            skip("<pattern> paint");
        return solid(value.fallbackKind, value.fallbackColor);
    }

    std::shared_ptr<Gradient> readGradient(const XmlElement& element, const Viewport& viewport)
    {
        auto it = m_gradients.find(&element);
        if (it != m_gradients.end())
            return it->second;

        // The chain of xlink:href templates, starting with this element.
        std::vector<const XmlElement*> chain{ &element };
        while (chain.size() < static_cast<size_t>(kMaxReferenceDepth))
        {
            const XmlElement* next = hrefTarget(*chain.back());
            if (!next || (next->tag != Tag::eLinearGradient && next->tag != Tag::eRadialGradient) ||
                std::find(chain.begin(), chain.end(), next) != chain.end())
                break;
            chain.push_back(next);
        }
        auto attribute = [&](const char* name) -> const std::string_view* {
            for (const XmlElement* e : chain)
            {
                if (const std::string_view* v = e->attribute(name))
                    return v;
            }
            return nullptr;
        };

        auto gradient = std::make_shared<Gradient>();
        gradient->radial = element.tag == Tag::eRadialGradient;
        const std::string_view* units = attribute("gradientUnits");
        gradient->userSpaceUnits = units && trim(*units) == "userSpaceOnUse";
        if (const std::string_view* spread = attribute("spreadMethod"))
        {
            if (trim(*spread) == "reflect")
                gradient->spread = Gradient::Spread::eReflect;
            else if (trim(*spread) == "repeat")
                gradient->spread = Gradient::Spread::eRepeat;
        }
        if (const std::string_view* t = attribute("gradientTransform"))
            parseTransformList(*t, gradient->transform);

        // In bounding-box units, 50% and 0.5 are the same.
        auto coordinate = [&](const char* name, Axis axis, double fallback) {
            const std::string_view* text = attribute(name);
            Length l;
            if (!text || !parseLength(*text, l))
                return fallback;
            if (!gradient->userSpaceUnits)
                return l.percent ? l.value / 100.0 : l.value;
            return viewport.resolve(l, axis);
        };
        const bool user = gradient->userSpaceUnits;
        if (gradient->radial)
        {
            gradient->cx = coordinate("cx", Axis::eX, user ? viewport.width * 0.5 : 0.5);
            gradient->cy = coordinate("cy", Axis::eY, user ? viewport.height * 0.5 : 0.5);
            gradient->r = coordinate("r", Axis::eOther, user ? viewport.resolve({ 50.0, true }, Axis::eOther) : 0.5);
            gradient->fx = coordinate("fx", Axis::eX, gradient->cx);
            gradient->fy = coordinate("fy", Axis::eY, gradient->cy);
            gradient->fr = coordinate("fr", Axis::eOther, 0.0);
        }
        else
        {
            gradient->x1 = coordinate("x1", Axis::eX, 0.0);
            gradient->y1 = coordinate("y1", Axis::eY, 0.0);
            gradient->x2 = coordinate("x2", Axis::eX, user ? viewport.width : 1.0);
            gradient->y2 = coordinate("y2", Axis::eY, 0.0);
        }

        // The stops of the first element in the chain that has any. They
        // inherit (currentColor, inherit) from that element and its ancestors.
        for (const XmlElement* e : chain)
        {
            size_t stops = 0;
            for (const XmlElement& child : e->children())
                stops += child.tag == Tag::eStop;
            if (stops > kMaxGradientStops)
                throw LimitError("a gradient has more than " + std::to_string(kMaxGradientStops) + " stops");
            if (stops == 0)
                continue;
            gradient->stops.reserve(stops);
            float last = 0.0f;
            const Style& gradientStyle = documentStyle(*e);
            for (const XmlElement& child : e->children())
            {
                if (child.tag != Tag::eStop)
                    continue;
                const Style stopStyle = computeStyle(child, gradientStyle);
                GradientStop stop;
                float offset = 0.0f;
                if (const std::string_view* text = child.attribute("offset"))
                    parseOpacity(*text, offset); // a number or a percentage, clamped to 0..1
                stop.offset = std::max(offset, last);
                last = stop.offset;
                stop.color = stopStyle.stopColorIsCurrent ? stopStyle.color : stopStyle.stopColor;
                stop.color.a *= stopStyle.stopOpacity;
                gradient->stops.push_back(stop);
            }
            if (!gradient->stops.empty())
                break;
        }
        m_gradients.emplace(&element, gradient);
        return gradient;
    }

    /// Adds the clip path of `style` to `node`. `bboxPath` gives the bounding
    /// box for clipPathUnits="objectBoundingBox"; for a group it is the union
    /// of the children.
    void applyClip(Node& node, const Style& style, const Viewport& viewport, const Path* bboxPath = nullptr)
    {
        if (style.clipPath.empty())
            return;
        const XmlElement* clip = lookup(style.clipPath);
        if (!clip || clip->tag != Tag::eClipPath)
            return; // a missing clip path draws the element without a clip, like a browser
        const Style& clipStyle = documentStyle(*clip);
        if (!clipStyle.clipPath.empty())
            skip("a clip-path on a <clipPath>");
        Transform units;
        const std::string_view* unitsText = clip->attribute("clipPathUnits");
        if (unitsText && trim(*unitsText) == "objectBoundingBox")
        {
            Rect box;
            if (bboxPath)
                box = bboxPath->bounds();
            else
                box = childrenBounds(node.children);
            if (box.empty())
            {
                node.clipToNothing = true;
                return;
            }
            units = Transform::translate(box.x0, box.y0) * Transform::scale(box.x1 - box.x0, box.y1 - box.y0);
        }
        const Transform clipTransform = elementTransform(*clip) * units;
        for (const XmlElement& child : clip->children())
        {
            const XmlElement* shapeElement = &child;
            Transform useTransform;
            // A <use> is styled first; the shape that it refers to inherits
            // from it (for example its clip-rule), as everywhere else.
            Style childStyle = computeStyle(child, clipStyle);
            if (shapeElement->tag == Tag::eUse)
            {
                const XmlElement* target = hrefTarget(*shapeElement);
                if (!target || !childStyle.display)
                    continue;
                useTransform = elementTransform(*shapeElement) *
                               Transform::translate(lengthAttribute(*shapeElement, "x", viewport, Axis::eX, 0.0),
                                                    lengthAttribute(*shapeElement, "y", viewport, Axis::eY, 0.0));
                shapeElement = target;
                childStyle = computeStyle(*target, childStyle);
            }
            if (!childStyle.display || !childStyle.visible)
                continue;
            ClipShape shape;
            if (!readShape(*shapeElement, viewport, shape.path))
            {
                if (shapeElement->tag == Tag::eText)
                    skip("<text>");
                continue;
            }
            if (shape.path.empty())
                continue;
            countNode(shape.path.points.size());
            shape.transform = clipTransform * useTransform * elementTransform(*shapeElement);
            shape.rule = childStyle.clipRule;
            node.clip.push_back(std::move(shape));
        }
        if (node.clip.empty())
            node.clipToNothing = true;
    }

    static Rect childrenBounds(const std::vector<Node>& children)
    {
        Rect total;
        bool any = false;
        for (const Node& child : children)
        {
            Rect box = child.isGroup ? childrenBounds(child.children) : child.path.bounds();
            if (box.empty() && !(box.x1 >= box.x0 && box.y1 >= box.y0 && (box.x1 > box.x0 || box.y1 > box.y0)))
                continue;
            const Point corners[4] = { child.transform.apply({ box.x0, box.y0 }),
                                       child.transform.apply({ box.x1, box.y0 }),
                                       child.transform.apply({ box.x1, box.y1 }),
                                       child.transform.apply({ box.x0, box.y1 }) };
            for (const Point& p : corners)
            {
                if (!any)
                {
                    total = Rect{ p.x, p.y, p.x, p.y };
                    any = true;
                }
                total.x0 = std::min(total.x0, p.x);
                total.y0 = std::min(total.y0, p.y);
                total.x1 = std::max(total.x1, p.x);
                total.y1 = std::max(total.y1, p.y);
            }
        }
        return total;
    }

    const XmlElement& m_root;
    Document& m_doc;
    std::unordered_map<std::string_view, const XmlElement*> m_ids;
    std::vector<CssRule> m_rules;
    size_t m_cssPairs = 0;
    mutable CssSteps m_cssSteps; ///< counted by computeStyle(), which does not change the document
    std::set<std::string> m_skipped;
    std::vector<const XmlElement*> m_useStack;
    std::unordered_map<const XmlElement*, std::shared_ptr<Gradient>> m_gradients;
    std::unique_ptr<std::unordered_map<const XmlElement*, Style>> m_documentStyles;
    size_t m_nodes = 0; ///< groups and shapes made, with clip shapes
    size_t m_points = 0; ///< path points of the shapes and clip shapes made
};

} // anonymous namespace

// ---------------------------------------------------------------------------
// Transform and Path
// ---------------------------------------------------------------------------

Transform Transform::translate(double x, double y)
{
    Transform t;
    t.e = x;
    t.f = y;
    return t;
}

Transform Transform::scale(double x, double y)
{
    Transform t;
    t.a = x;
    t.d = y;
    return t;
}

Transform Transform::rotate(double degrees)
{
    const double r = degrees * kPi / 180.0;
    Transform t;
    t.a = std::cos(r);
    t.b = std::sin(r);
    t.c = -t.b;
    t.d = t.a;
    return t;
}

Transform Transform::skewX(double degrees)
{
    Transform t;
    t.c = std::tan(degrees * kPi / 180.0);
    return t;
}

Transform Transform::skewY(double degrees)
{
    Transform t;
    t.b = std::tan(degrees * kPi / 180.0);
    return t;
}

Transform Transform::operator*(const Transform& o) const
{
    Transform r;
    r.a = a * o.a + c * o.b;
    r.b = b * o.a + d * o.b;
    r.c = a * o.c + c * o.d;
    r.d = b * o.c + d * o.d;
    r.e = a * o.e + c * o.f + e;
    r.f = b * o.e + d * o.f + f;
    return r;
}

bool Transform::invert(Transform& out) const
{
    const double det = a * d - b * c;
    if (!std::isfinite(det) || std::fabs(det) < 1e-300)
        return false;
    const double inv = 1.0 / det;
    out.a = d * inv;
    out.b = -b * inv;
    out.c = -c * inv;
    out.d = a * inv;
    out.e = -(out.a * e + out.c * f);
    out.f = -(out.b * e + out.d * f);
    return true;
}

double Transform::maxScale() const
{
    // The largest singular value of [a c; b d].
    const double sum = a * a + b * b + c * c + d * d;
    const double det = a * d - b * c;
    const double root = std::sqrt(std::max(0.0, sum * sum / 4.0 - det * det));
    return std::sqrt(std::max(0.0, sum / 2.0 + root));
}

void Path::moveTo(Point p)
{
    verbs.push_back(Verb::eMove);
    points.push_back(p);
}

void Path::lineTo(Point p)
{
    if (verbs.empty())
    {
        moveTo(p);
        return;
    }
    verbs.push_back(Verb::eLine);
    points.push_back(p);
}

void Path::cubicTo(Point c1, Point c2, Point p)
{
    if (verbs.empty())
        moveTo(c1);
    verbs.push_back(Verb::eCubic);
    points.push_back(c1);
    points.push_back(c2);
    points.push_back(p);
}

void Path::quadTo(Point c, Point p)
{
    const Point p0 = currentPoint();
    cubicTo({ p0.x + 2.0 / 3.0 * (c.x - p0.x), p0.y + 2.0 / 3.0 * (c.y - p0.y) },
            { p.x + 2.0 / 3.0 * (c.x - p.x), p.y + 2.0 / 3.0 * (c.y - p.y) }, p);
}

void Path::close()
{
    if (!verbs.empty() && verbs.back() != Verb::eClose)
        verbs.push_back(Verb::eClose);
}

Point Path::currentPoint() const
{
    if (verbs.empty())
        return {};
    if (verbs.back() != Verb::eClose)
        return points.back();
    // After a close, the current point is the start of that subpath.
    size_t pointIndex = points.size();
    for (size_t i = verbs.size(); i-- > 0;)
    {
        switch (verbs[i])
        {
        case Verb::eMove:
            return points[pointIndex - 1];
        case Verb::eLine:
            pointIndex -= 1;
            break;
        case Verb::eCubic:
            pointIndex -= 3;
            break;
        case Verb::eClose:
            break;
        }
    }
    return points.front();
}

void Path::arcTo(double rx, double ry, double xAxisRotationDegrees, bool largeArc, bool sweep, Point p)
{
    const Point p0 = currentPoint();
    if (verbs.empty())
    {
        moveTo(p);
        return;
    }
    if (p0.x == p.x && p0.y == p.y)
        return; // the same end points: no arc
    rx = std::fabs(rx);
    ry = std::fabs(ry);
    if (rx == 0.0 || ry == 0.0)
    {
        lineTo(p);
        return;
    }
    const double phi = xAxisRotationDegrees * kPi / 180.0;
    const double cosPhi = std::cos(phi);
    const double sinPhi = std::sin(phi);
    // The end point form to the center form (SVG implementation notes).
    const double dx = (p0.x - p.x) / 2.0;
    const double dy = (p0.y - p.y) / 2.0;
    const double x1 = cosPhi * dx + sinPhi * dy;
    const double y1 = -sinPhi * dx + cosPhi * dy;
    const double lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry);
    if (lambda > 1.0)
    {
        const double s = std::sqrt(lambda);
        rx *= s;
        ry *= s;
    }
    const double numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
    const double denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1;
    double coef = denominator > 0.0 ? std::sqrt(std::max(0.0, numerator / denominator)) : 0.0;
    if (largeArc == sweep)
        coef = -coef;
    const double cxp = coef * rx * y1 / ry;
    const double cyp = -coef * ry * x1 / rx;
    const double cx = cosPhi * cxp - sinPhi * cyp + (p0.x + p.x) / 2.0;
    const double cy = sinPhi * cxp + cosPhi * cyp + (p0.y + p.y) / 2.0;
    auto angle = [](double ux, double uy, double vx, double vy) {
        return std::atan2(ux * vy - uy * vx, ux * vx + uy * vy);
    };
    const double theta1 = angle(1.0, 0.0, (x1 - cxp) / rx, (y1 - cyp) / ry);
    double delta = angle((x1 - cxp) / rx, (y1 - cyp) / ry, (-x1 - cxp) / rx, (-y1 - cyp) / ry);
    if (!sweep && delta > 0.0)
        delta -= 2.0 * kPi;
    else if (sweep && delta < 0.0)
        delta += 2.0 * kPi;

    // Cubic pieces of at most 45 degrees each.
    const int pieces = std::max(1, static_cast<int>(std::ceil(std::fabs(delta) / (kPi / 4.0) - 1e-9)));
    const double step = delta / pieces;
    const double k = 4.0 / 3.0 * std::tan(step / 4.0);
    auto map = [&](double ux, double uy) {
        return Point{ cx + cosPhi * rx * ux - sinPhi * ry * uy, cy + sinPhi * rx * ux + cosPhi * ry * uy };
    };
    for (int i = 0; i < pieces; ++i)
    {
        const double t0 = theta1 + step * i;
        const double t1 = t0 + step;
        const double c0 = std::cos(t0), s0 = std::sin(t0);
        const double c1 = std::cos(t1), s1 = std::sin(t1);
        const Point a = map(c0 - k * s0, s0 + k * c0);
        const Point b = map(c1 + k * s1, s1 - k * c1);
        const Point end = (i == pieces - 1) ? p : map(c1, s1);
        cubicTo(a, b, end);
    }
}

Rect Path::bounds() const
{
    Rect r;
    bool any = false;
    auto add = [&](Point p) {
        if (!any)
        {
            r = Rect{ p.x, p.y, p.x, p.y };
            any = true;
            return;
        }
        r.x0 = std::min(r.x0, p.x);
        r.y0 = std::min(r.y0, p.y);
        r.x1 = std::max(r.x1, p.x);
        r.y1 = std::max(r.y1, p.y);
    };
    size_t pi = 0;
    Point current;
    for (Verb v : verbs)
    {
        switch (v)
        {
        case Verb::eMove:
        case Verb::eLine:
            current = points[pi++];
            add(current);
            break;
        case Verb::eCubic:
        {
            const Point p0 = current, p1 = points[pi], p2 = points[pi + 1], p3 = points[pi + 2];
            pi += 3;
            add(p3);
            // Extremes where the derivative of one coordinate is zero.
            for (int axis = 0; axis < 2; ++axis)
            {
                const double a0 = axis ? p0.y : p0.x, a1 = axis ? p1.y : p1.x;
                const double a2 = axis ? p2.y : p2.x, a3 = axis ? p3.y : p3.x;
                const double qa = -a0 + 3.0 * a1 - 3.0 * a2 + a3;
                const double qb = 2.0 * (a0 - 2.0 * a1 + a2);
                const double qc = a1 - a0;
                double roots[2];
                int count = 0;
                if (std::fabs(qa) < 1e-12)
                {
                    if (std::fabs(qb) > 1e-12)
                        roots[count++] = -qc / qb;
                }
                else
                {
                    const double disc = qb * qb - 4.0 * qa * qc;
                    if (disc >= 0.0)
                    {
                        const double s = std::sqrt(disc);
                        roots[count++] = (-qb + s) / (2.0 * qa);
                        roots[count++] = (-qb - s) / (2.0 * qa);
                    }
                }
                for (int i = 0; i < count; ++i)
                {
                    const double t = roots[i];
                    if (t > 0.0 && t < 1.0)
                    {
                        const double u = 1.0 - t;
                        const double w0 = u * u * u, w1 = 3.0 * u * u * t, w2 = 3.0 * u * t * t, w3 = t * t * t;
                        add({ w0 * p0.x + w1 * p1.x + w2 * p2.x + w3 * p3.x,
                              w0 * p0.y + w1 * p1.y + w2 * p2.y + w3 * p3.y });
                    }
                }
            }
            current = p3;
            break;
        }
        case Verb::eClose:
            break;
        }
    }
    return r;
}

bool parseSvgDocument(const std::string& text, Document& doc, std::string& error)
{
    doc = Document{};
    // Each thread keeps the memory of its XML elements for the next file,
    // unless the file was large. This is also done when an exception (for
    // example std::bad_alloc) leaves this function.
    thread_local XmlDocument xmlDoc;
    struct Release
    {
        XmlDocument& xml;
        ~Release()
        {
            if (xml.large())
                xml = XmlDocument{};
            else
                xml.clear();
        }
    } release{ xmlDoc };
    xmlDoc.clear();
    XmlReader xml(text);
    if (!xml.read(xmlDoc, error))
        return false;
    try
    {
        SvgReader reader(*xmlDoc.root, doc);
        return reader.read(error);
    }
    catch (const LimitError& limit)
    {
        // A file over a limit: no part of it is drawn.
        doc = Document{};
        error = limit.what();
        return false;
    }
}

} // namespace svg
} // namespace standalone
} // namespace ui
} // namespace omni
