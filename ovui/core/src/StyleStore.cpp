/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/StyleStore.h>

#include <limits>
#include <string.h>
#include <limits>

#ifdef _WIN32
#    define strdup _strdup
#endif

OMNIUI_NAMESPACE_OPEN_SCOPE

ColorStore::ColorStore()
{
    m_store.reserve(147);
    // https://www.w3.org/wiki/CSS/Properties/color/keywords
    // Basic Colors
    m_store.emplace_back("black", 0xff000000, true);
    m_store.emplace_back("silver", 0xffc0c0c0, true);
    m_store.emplace_back("gray", 0xff808080, true);
    m_store.emplace_back("white", 0xffffffff, true);
    m_store.emplace_back("maroon", 0xff000080, true);
    m_store.emplace_back("red", 0xff0000ff, true);
    m_store.emplace_back("purple", 0xff800080, true);
    m_store.emplace_back("fuchsia", 0xffff00ff, true);
    m_store.emplace_back("green", 0xff008000, true);
    m_store.emplace_back("lime", 0xff00ff00, true);
    m_store.emplace_back("olive", 0xff008080, true);
    m_store.emplace_back("yellow", 0xff00ffff, true);
    m_store.emplace_back("navy", 0xff800000, true);
    m_store.emplace_back("blue", 0xffff0000, true);
    m_store.emplace_back("teal", 0xff808000, true);
    m_store.emplace_back("aqua", 0xffffff00, true);
    // Extended colors
    m_store.emplace_back("aliceblue", 0xfffff8f0, true);
    m_store.emplace_back("antiquewhite", 0xffd7ebfa, true);
    // m_store.emplace_back("aqua", 0xffffff00, true);
    m_store.emplace_back("aquamarine", 0xffd4ff7f, true);
    m_store.emplace_back("azure", 0xfffffff0, true);
    m_store.emplace_back("beige", 0xffdcf5f5, true);
    m_store.emplace_back("bisque", 0xffc4e4ff, true);
    // m_store.emplace_back("black", 0xff000000, true);
    m_store.emplace_back("blanchedalmond", 0xffcdebff, true);
    // m_store.emplace_back("blue", 0xffff0000, true);
    m_store.emplace_back("blueviolet", 0xffe22b8a, true);
    m_store.emplace_back("brown", 0xff2a2aa5, true);
    m_store.emplace_back("burlywood", 0xff87b8de, true);
    m_store.emplace_back("cadetblue", 0xffa09e5f, true);
    m_store.emplace_back("chartreuse", 0xff00ff7f, true);
    m_store.emplace_back("chocolate", 0xff1e69d2, true);
    m_store.emplace_back("coral", 0xff507fff, true);
    m_store.emplace_back("cornflowerblue", 0xffed9564, true);
    m_store.emplace_back("cornsilk", 0xffdcf8ff, true);
    m_store.emplace_back("crimson", 0xff3c14dc, true);
    m_store.emplace_back("cyan", 0xffffff00, true);
    m_store.emplace_back("darkblue", 0xff8b0000, true);
    m_store.emplace_back("darkcyan", 0xff8b8b00, true);
    m_store.emplace_back("darkgoldenrod", 0xff0b86b8, true);
    m_store.emplace_back("darkgray", 0xffa9a9a9, true);
    m_store.emplace_back("darkgreen", 0xff006400, true);
    m_store.emplace_back("darkgrey", 0xffa9a9a9, true);
    m_store.emplace_back("darkkhaki", 0xff6bb7bd, true);
    m_store.emplace_back("darkmagenta", 0xff8b008b, true);
    m_store.emplace_back("darkolivegreen", 0xff2f6b55, true);
    m_store.emplace_back("darkorange", 0xff008cff, true);
    m_store.emplace_back("darkorchid", 0xffcc3299, true);
    m_store.emplace_back("darkred", 0xff00008b, true);
    m_store.emplace_back("darksalmon", 0xff7a96e9, true);
    m_store.emplace_back("darkseagreen", 0xff8fbc8f, true);
    m_store.emplace_back("darkslateblue", 0xff8b3d48, true);
    m_store.emplace_back("darkslategray", 0xff4f4f2f, true);
    m_store.emplace_back("darkslategrey", 0xff4f4f2f, true);
    m_store.emplace_back("darkturquoise", 0xffd1ce00, true);
    m_store.emplace_back("darkviolet", 0xffd30094, true);
    m_store.emplace_back("deeppink", 0xff9314ff, true);
    m_store.emplace_back("deepskyblue", 0xffffbf00, true);
    m_store.emplace_back("dimgray", 0xff696969, true);
    m_store.emplace_back("dimgrey", 0xff696969, true);
    m_store.emplace_back("dodgerblue", 0xffff901e, true);
    m_store.emplace_back("firebrick", 0xff2222b2, true);
    m_store.emplace_back("floralwhite", 0xfff0faff, true);
    m_store.emplace_back("forestgreen", 0xff228b22, true);
    // m_store.emplace_back("fuchsia", 0xffff00ff, true);
    m_store.emplace_back("gainsboro", 0xffdcdcdc, true);
    m_store.emplace_back("ghostwhite", 0xfffff8f8, true);
    m_store.emplace_back("gold", 0xff00d7ff, true);
    m_store.emplace_back("goldenrod", 0xff20a5da, true);
    // m_store.emplace_back("gray", 0xff808080, true);
    // m_store.emplace_back("green", 0xff008000, true);
    m_store.emplace_back("greenyellow", 0xff2fffad, true);
    m_store.emplace_back("grey", 0xff808080, true);
    m_store.emplace_back("honeydew", 0xfff0fff0, true);
    m_store.emplace_back("hotpink", 0xffb469ff, true);
    m_store.emplace_back("indianred", 0xff5c5ccd, true);
    m_store.emplace_back("indigo", 0xff82004b, true);
    m_store.emplace_back("ivory", 0xfff0ffff, true);
    m_store.emplace_back("khaki", 0xff8ce6f0, true);
    m_store.emplace_back("lavender", 0xfffae6e6, true);
    m_store.emplace_back("lavenderblush", 0xfff5f0ff, true);
    m_store.emplace_back("lawngreen", 0xff00fc7c, true);
    m_store.emplace_back("lemonchiffon", 0xffcdfaff, true);
    m_store.emplace_back("lightblue", 0xffe6d8ad, true);
    m_store.emplace_back("lightcoral", 0xff8080f0, true);
    m_store.emplace_back("lightcyan", 0xffffffe0, true);
    m_store.emplace_back("lightgoldenrodyellow", 0xffd2fafa, true);
    m_store.emplace_back("lightgray", 0xffd3d3d3, true);
    m_store.emplace_back("lightgreen", 0xff90ee90, true);
    m_store.emplace_back("lightgrey", 0xffd3d3d3, true);
    m_store.emplace_back("lightpink", 0xffc1b6ff, true);
    m_store.emplace_back("lightsalmon", 0xff7aa0ff, true);
    m_store.emplace_back("lightseagreen", 0xffaab220, true);
    m_store.emplace_back("lightskyblue", 0xffface87, true);
    m_store.emplace_back("lightslategray", 0xff998877, true);
    m_store.emplace_back("lightslategrey", 0xff998877, true);
    m_store.emplace_back("lightsteelblue", 0xffdec4b0, true);
    m_store.emplace_back("lightyellow", 0xffe0ffff, true);
    // m_store.emplace_back("lime", 0xff00ff00, true);
    m_store.emplace_back("limegreen", 0xff32cd32, true);
    m_store.emplace_back("linen", 0xffe6f0fa, true);
    m_store.emplace_back("magenta", 0xffff00ff, true);
    // m_store.emplace_back("maroon", 0xff000080, true);
    m_store.emplace_back("mediumaquamarine", 0xffaacd66, true);
    m_store.emplace_back("mediumblue", 0xffcd0000, true);
    m_store.emplace_back("mediumorchid", 0xffd355ba, true);
    m_store.emplace_back("mediumpurple", 0xffdb7093, true);
    m_store.emplace_back("mediumseagreen", 0xff71b33c, true);
    m_store.emplace_back("mediumslateblue", 0xffee687b, true);
    m_store.emplace_back("mediumspringgreen", 0xff9afa00, true);
    m_store.emplace_back("mediumturquoise", 0xffccd148, true);
    m_store.emplace_back("mediumvioletred", 0xff8515c7, true);
    m_store.emplace_back("midnightblue", 0xff701919, true);
    m_store.emplace_back("mintcream", 0xfffafff5, true);
    m_store.emplace_back("mistyrose", 0xffe1e4ff, true);
    m_store.emplace_back("moccasin", 0xffb5e4ff, true);
    m_store.emplace_back("navajowhite", 0xffaddeff, true);
    // m_store.emplace_back("navy", 0xff800000, true);
    m_store.emplace_back("oldlace", 0xffe6f5fd, true);
    // m_store.emplace_back("olive", 0xff008080, true);
    m_store.emplace_back("olivedrab", 0xff238e6b, true);
    m_store.emplace_back("orange", 0xff00a5ff, true);
    m_store.emplace_back("orangered", 0xff0045ff, true);
    m_store.emplace_back("orchid", 0xffd670da, true);
    m_store.emplace_back("palegoldenrod", 0xffaae8ee, true);
    m_store.emplace_back("palegreen", 0xff98fb98, true);
    m_store.emplace_back("paleturquoise", 0xffeeeeaf, true);
    m_store.emplace_back("palevioletred", 0xff9370db, true);
    m_store.emplace_back("papayawhip", 0xffd5efff, true);
    m_store.emplace_back("peachpuff", 0xffb9daff, true);
    m_store.emplace_back("peru", 0xff3f85cd, true);
    m_store.emplace_back("pink", 0xffcbc0ff, true);
    m_store.emplace_back("plum", 0xffdda0dd, true);
    m_store.emplace_back("powderblue", 0xffe6e0b0, true);
    // m_store.emplace_back("purple", 0xff800080, true);
    // m_store.emplace_back("red", 0xff0000ff, true);
    m_store.emplace_back("rosybrown", 0xff8f8fbc, true);
    m_store.emplace_back("royalblue", 0xffe16941, true);
    m_store.emplace_back("saddlebrown", 0xff13458b, true);
    m_store.emplace_back("salmon", 0xff7280fa, true);
    m_store.emplace_back("sandybrown", 0xff60a4f4, true);
    m_store.emplace_back("seagreen", 0xff578b2e, true);
    m_store.emplace_back("seashell", 0xffeef5ff, true);
    m_store.emplace_back("sienna", 0xff2d52a0, true);
    // m_store.emplace_back("silver", 0xffc0c0c0, true);
    m_store.emplace_back("skyblue", 0xffebce87, true);
    m_store.emplace_back("slateblue", 0xffcd5a6a, true);
    m_store.emplace_back("slategray", 0xff908070, true);
    m_store.emplace_back("slategrey", 0xff908070, true);
    m_store.emplace_back("snow", 0xfffafaff, true);
    m_store.emplace_back("springgreen", 0xff7fff00, true);
    m_store.emplace_back("steelblue", 0xffb48246, true);
    m_store.emplace_back("tan", 0xff8cb4d2, true);
    // m_store.emplace_back("teal", 0xff808000, true);
    m_store.emplace_back("thistle", 0xffd8bfd8, true);
    m_store.emplace_back("tomato", 0xff4763ff, true);
    m_store.emplace_back("turquoise", 0xffd0e040, true);
    m_store.emplace_back("violet", 0xffee82ee, true);
    m_store.emplace_back("wheat", 0xffb3def5, true);
    // m_store.emplace_back("white", 0xffffffff, true);
    m_store.emplace_back("whitesmoke", 0xfff5f5f5, true);
    // m_store.emplace_back("yellow", 0xff00ffff, true);
    m_store.emplace_back("yellowgreen", 0xff32cd9a, true);

    m_store.emplace_back("transparent", 0x0, true);
}

ColorStore& ColorStore::getInstance()
{
    static ColorStore instance;
    return instance;
}

FloatStore::FloatStore()
{
    m_store.reserve(5);
    m_store.emplace_back("zero", 0.f, true);
    m_store.emplace_back("one", 1.f, true);
    m_store.emplace_back("min", std::numeric_limits<float>::min(), true);
    m_store.emplace_back("max", std::numeric_limits<float>::max(), true);
    m_store.emplace_back("inf", std::numeric_limits<float>::infinity(), true);
}

FloatStore& FloatStore::getInstance()
{
    static FloatStore instance;
    return instance;
}

StringStore::StringStore()
{
}

StringStore::~StringStore()
{
    for (auto& entry : m_store)
    {
        free((void*)entry.value);
    }
}

void StringStore::store(const std::string& name, const char* string_value, bool readOnly)
{
    size_t found = this->find(name);
    if (found == SIZE_MAX)
    {
        m_store.emplace_back(__toLower(name), strdup(string_value), readOnly);
    }
    else if (!m_store[found].readOnly && strcmp(m_store[found].value, string_value) != 0)
    {
        // Free the string if it's stored.
        free((void*)m_store[found].value);
        m_store[found].value = strdup(string_value);
        m_store[found].readOnly = readOnly;
    }
}

StringStore& StringStore::getInstance()
{
    static StringStore instance;
    return instance;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
