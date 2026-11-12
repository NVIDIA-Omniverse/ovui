/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * What a .svg image does in the standalone backend.
 *
 * VectorImageProvider asks the PlatformRegistry for an ISvgRasterizer. Without
 * one it draws nothing. The standalone backend registers StandaloneSvgRasterizer
 * (the project's own SVG reader and painter, StandaloneSvgDocument.h) when the
 * CMake option OMNIUI_ENABLE_SVG is ON, and StandaloneSvgOffRasterizer when it
 * is OFF.
 *
 * Cases that need the rasterizer (OMNIUI_HAS_SVG defined) run a real
 * VectorImageProvider against real SVG files and a counting fake IByteImageGpu:
 * the SVG is drawn with the right pixels and aspect ratio, textures are shared
 * and freed, and a bad file is logged once with its cause. The ui.Image
 * backend (StandaloneImageBackend) must load an .svg file through the same
 * rasterizer: the same texture as VectorImageProvider for the same file and
 * size, freed with its last user, and nothing released after shutdown. They
 * also paint
 * every file of tests/svg_corpus (shapes, paths, strokes, fills, gradients,
 * transforms, opacity, and the icons of ovui-widgets in icons/) and compare
 * the pixels with the pictures that Google Chrome made of the same files
 * (tests/svg_corpus/chrome/), and they feed broken and cut-off files to the
 * reader, which must fail cleanly (the B2 job runs this under ASan). Files
 * whose work multiplies (entity expansion, <use> fan-out, selectors over
 * nested groups, style rule and declaration products, long gradient stop
 * lists, deep nesting through <use>, nested layers, curves) must be refused
 * with the limit that they pass, each within a time and a memory bound. An
 * exception while a file is read or painted (a test seam throws it) must leave
 * the image empty and log the cause once.
 *
 * Cases that run in both builds check the rasterizer that `init` registers
 * with the option OFF (StandaloneSvgOffRasterizer): a provider has no image, and
 * each URL logs one error that names the option. With no rasterizer registered
 * at all, a provider has no image and logs nothing.
 *
 * No GPU, window or running application is involved.
 */

#ifdef OMNIUI_HAS_SVG
// The rasterizer reads file:// URLs through StandaloneImageBackend, which uses
// the raster loader, which needs stb_image.
#    define STB_IMAGE_IMPLEMENTATION
#    define STBI_NO_STDIO
#    include <stb_image.h>
#endif

#include "../../standalone/src/StandaloneSvgOffRasterizer.h"
#include "../../standalone/src/StandaloneSvgRasterizer.h"
#ifdef OMNIUI_HAS_SVG
#    include "../../standalone/src/StandaloneImageBackend.h"
#    include "../../standalone/src/StandaloneRasterImageLoader.h"
#    include "../../standalone/src/StandaloneSvgDocument.h"
#endif

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/platform/IUiLog.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <memory>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#if defined(__linux__)
#    include <unistd.h>
#elif defined(_WIN32)
#    ifndef NOMINMAX
#        define NOMINMAX
#    endif
#    define WIN32_LEAN_AND_MEAN
#    include <windows.h>
#    include <psapi.h>
#endif

using namespace omni::ui;
using omni::ui::standalone::StandaloneSvgOffRasterizer;
using omni::ui::standalone::StandaloneSvgRasterizer;

namespace
{

std::vector<std::string> g_caseFailures;
std::string g_caseName;
int g_failedCases = 0;

void check(bool condition, const std::string& what)
{
    if (!condition)
        g_caseFailures.push_back(what);
}

void beginCase(const std::string& name)
{
    g_caseName = name;
    g_caseFailures.clear();
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
        std::cout << "       " << failure << std::endl;
}

struct CountingGpu : IByteImageGpu
{
    int created = 0;
    int uploaded = 0;
    int destroyed = 0;
    std::set<void*> live;
    bool doubleDestroy = false;
    std::vector<uint8_t> lastPixels;
    UInt2 lastSize = {};

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

    void releaseImage(Handle) override {}

    UpdateResult updateImage(Handle state, const uint8_t* const* mips, size_t* strides, size_t, UInt2 size,
                             PixelFormat, bool, uint32_t, uint32_t, uint32_t) override
    {
        ++uploaded;
        lastSize = size;
        lastPixels.assign(mips[0], mips[0] + strides[0] * size.y);
        return { state, nullptr };
    }
};

struct CapturingLog : IUiLog
{
    std::vector<std::string> errors;
    std::vector<std::string> warnings;

    void logError(const char* fmt, va_list args) override
    {
        char buffer[1024];
        vsnprintf(buffer, sizeof(buffer), fmt, args);
        errors.emplace_back(buffer);
    }
    void logWarn(const char* fmt, va_list args) override
    {
        char buffer[1024];
        vsnprintf(buffer, sizeof(buffer), fmt, args);
        warnings.emplace_back(buffer);
    }
    void logInfo(const char*, va_list) override {}
};

// A 20x10 SVG: its left half is an opaque red square 10x10, its right half is empty.
const char* kRedSquareSvg =
    "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"10\" viewBox=\"0 0 20 10\">"
    "<rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" fill=\"#ff0000\"/></svg>";

std::filesystem::path g_dir;

// Makes a new, empty folder with a name that is unique for this run. A folder
// that already exists is never used: create_directory returns false for it, and
// the loop tries another name. The test deletes only the folder that it made.
std::filesystem::path makeUniqueTempDir()
{
    std::random_device device;
    const auto tick = std::chrono::steady_clock::now().time_since_epoch().count();
    for (int attempt = 0; attempt < 100; ++attempt)
    {
        const std::string name = "ovui_svg_rasterizer_test_" + std::to_string(static_cast<long long>(tick)) + "_" +
                                 std::to_string(device()) + "_" + std::to_string(attempt);
        std::filesystem::path candidate = std::filesystem::temp_directory_path() / name;
        std::error_code error;
        if (std::filesystem::create_directory(candidate, error) && !error)
            return candidate;
    }
    return {};
}

std::string writeFile(const char* name, const std::string& text)
{
    std::filesystem::path path = g_dir / name;
    std::ofstream(path, std::ios::binary) << text;
    return path.string();
}

struct Fixture
{
    std::shared_ptr<CountingGpu> gpu = std::make_shared<CountingGpu>();
    std::shared_ptr<CapturingLog> log = std::make_shared<CapturingLog>();

    Fixture()
    {
        PlatformRegistry::instance().setByteImageGpu(gpu);
        PlatformRegistry::instance().setLog(log);
    }
    ~Fixture()
    {
        PlatformRegistry::instance().setSvgRasterizer(nullptr);
        PlatformRegistry::instance().setByteImageGpu(nullptr);
        PlatformRegistry::instance().setLog(nullptr);
    }
};

#ifdef OMNIUI_HAS_SVG

void caseDrawsPixelsAtWidgetAspect()
{
    beginCase("svg: bitmap keeps the aspect ratio and the drawn pixels");
    StandaloneSvgRasterizer::Bitmap bitmap;
    std::string error;
    const bool ok = StandaloneSvgRasterizer::rasterizeToBitmap(kRedSquareSvg, 20.0f, 20.0f, bitmap, error);
    check(ok, "a valid SVG must draw: " + error);
    // 20x10 fits 20x20 at scale 1, drawn at twice that: 40x20.
    check(bitmap.width == 40 && bitmap.height == 20,
          "bitmap must be 40x20, got " + std::to_string(bitmap.width) + "x" + std::to_string(bitmap.height));
    if (bitmap.rgba.size() == 40u * 20u * 4u)
    {
        const uint8_t* left = &bitmap.rgba[(10 * 40 + 10) * 4];
        const uint8_t* right = &bitmap.rgba[(10 * 40 + 30) * 4];
        check(left[0] == 255 && left[1] == 0 && left[2] == 0 && left[3] == 255, "the square must be opaque red");
        check(right[3] == 0, "outside the square must be transparent");
    }
    endCase();
}

void caseBadSvgReportsCause()
{
    beginCase("svg: text that is not an SVG and a zero widget size are refused with a cause");
    StandaloneSvgRasterizer::Bitmap bitmap;
    std::string error;
    check(!StandaloneSvgRasterizer::rasterizeToBitmap("not an svg at all", 16.0f, 16.0f, bitmap, error),
          "text that is not an SVG must be refused");
    check(!error.empty(), "the refusal must name a cause");
    error.clear();
    check(!StandaloneSvgRasterizer::rasterizeToBitmap(kRedSquareSvg, 0.0f, 16.0f, bitmap, error),
          "a zero widget width must be refused");
    check(!error.empty(), "the refusal must name a cause");
    error.clear();
    check(!StandaloneSvgRasterizer::rasterizeToBitmap("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", 16.0f,
                                                      16.0f, bitmap, error),
          "an SVG with no size must be refused");
    check(!error.empty(), "the refusal must name a cause");
    endCase();
}

void caseProviderShowsSvgAndFreesTexture()
{
    beginCase("svg: VectorImageProvider shows a file, shares its texture without reading it again, and frees it");
    Fixture fx;
    auto rasterizer = std::make_shared<StandaloneSvgRasterizer>();
    PlatformRegistry::instance().setSvgRasterizer(rasterizer);
    const std::string path = writeFile("red.svg", kRedSquareSvg);
    {
        VectorImageProvider a(path);
        a.prepareDraw(20.0f, 20.0f);
        check(fx.gpu->uploaded == 1 && fx.gpu->lastSize.x == 40 && fx.gpu->lastSize.y == 20,
              "the first image must upload a 40x20 bitmap");
        // Another widget size gets its own texture.
        VectorImageProvider c(path);
        c.prepareDraw(40.0f, 40.0f);
        check(fx.gpu->uploaded == 2 && fx.gpu->lastSize.x == 80 && fx.gpu->lastSize.y == 40,
              "a 40x40 widget must upload its own 80x40 bitmap");
        // The file is gone: a second image of the same file and size must
        // still get the shared texture, so it did not read the file again.
        std::filesystem::remove(path);
        VectorImageProvider b(path);
        b.prepareDraw(20.0f, 20.0f);
        check(a.isReferenceValid() && b.isReferenceValid() && c.isReferenceValid(), "every provider must have an image");
        check(fx.gpu->uploaded == 2, "one file at one size must upload once, got " + std::to_string(fx.gpu->uploaded) +
                                         " uploads for two sizes");
        check(fx.log->errors.empty(), "the second image must not read the file again: " +
                                          (fx.log->errors.empty() ? std::string() : fx.log->errors[0]));
    }
    check(fx.gpu->destroyed == fx.gpu->created && fx.gpu->live.empty(), "the texture must be freed with its providers");
    check(!fx.gpu->doubleDestroy, "no texture may be destroyed twice");
    {
        // Nothing of the file is kept after its last image is gone.
        VectorImageProvider c(path);
        c.prepareDraw(20.0f, 20.0f);
        check(!c.isReferenceValid(), "a file that is gone after its images were freed must not be drawn");
        check(fx.log->errors.size() == 1 && fx.log->errors[0].find("does not exist") != std::string::npos,
              "the missing file must be reported once");
    }
    endCase();
}

void caseImageBackendSharesSvgTextureWithProvider()
{
    beginCase("svg: ui.Image loads an .svg file with the rasterizer of VectorImageProvider and shares its texture");
    using omni::ui::standalone::StandaloneImageBackend;
    using omni::ui::standalone::StandaloneRasterImageLoader;
    Fixture fx;
    auto loader = std::make_shared<StandaloneRasterImageLoader>();
    auto rasterizer = std::make_shared<StandaloneSvgRasterizer>();
    PlatformRegistry::instance().setSvgRasterizer(rasterizer);
    StandaloneImageBackend backend(loader, rasterizer);
    const std::string path = writeFile("red_image.svg", kRedSquareSvg);

    // Loads like Image::_loadSourceUrl: the texture is stored by the callback.
    auto load = [&](const std::string& url, float width, float height, IImageBackend::TextureInfo& out) {
        return backend.loadTexture(
            url, width, height,
            [&out](IImageBackend::TextureInfo info) {
                out = std::move(info);
                return true;
            },
            [] {});
    };

    auto provider = std::make_unique<VectorImageProvider>(path);
    provider->prepareDraw(20.0f, 20.0f);
    IImageBackend::TextureInfo image;
    check(load(path, 20.0f, 20.0f, image) == IImageBackend::LoadResult::eSyncComplete, "the .svg file must load");
    check(image.handle && image.width == 40 && image.height == 20,
          "the image must be the 40x20 bitmap of a 20x20 widget, got " + std::to_string(image.width) + "x" +
              std::to_string(image.height));
    check(image.handle && backend.getImGuiTextureId(*image.handle) == provider->getImGuiReference(),
          "ui.Image must draw the texture of ImageWithProvider for the same file and size");
    check(fx.gpu->uploaded == 1, "one file at one size must upload once, got " + std::to_string(fx.gpu->uploaded));
    check(fx.log->errors.empty(), "a good file must log no error: " +
                                      (fx.log->errors.empty() ? std::string() : fx.log->errors[0]));

    provider.reset();
    check(fx.gpu->live.size() == 1, "the image must keep the texture after the provider is gone");
    image.handle.reset();
    check(fx.gpu->live.empty() && fx.gpu->destroyed == fx.gpu->created, "the texture must be freed with its last user");

    // An image that outlives the backend (shutdown, then a new ui.init) must
    // release nothing: the texture is gone, and the new rasterizer has an
    // entry with the same key.
    check(load(path, 20.0f, 20.0f, image) == IImageBackend::LoadResult::eSyncComplete, "the file must load again");
    rasterizer->shutdown();
    PlatformRegistry::instance().setSvgRasterizer(nullptr);
    rasterizer.reset();
    check(fx.gpu->live.empty(), "shutdown must free the texture of the image");
    auto next = std::make_shared<StandaloneSvgRasterizer>();
    PlatformRegistry::instance().setSvgRasterizer(next);
    VectorImageProvider nextProvider(path);
    nextProvider.prepareDraw(20.0f, 20.0f);
    image.handle.reset();
    check(fx.gpu->live.size() == 1 && nextProvider.isReferenceValid(),
          "an image of the old rasterizer must not release the texture of the new one");
    check(!fx.gpu->doubleDestroy, "no texture may be destroyed twice");

    // Without a rasterizer the image is empty, and the cause is logged once.
    StandaloneImageBackend noSvg(loader, nullptr);
    IImageBackend::TextureInfo none;
    fx.log->errors.clear();
    check(noSvg.loadTexture(path, 20.0f, 20.0f, [&none](IImageBackend::TextureInfo info) {
        none = std::move(info);
        return true;
    }, [] {}) == IImageBackend::LoadResult::eFailed && !none.handle, "without a rasterizer the .svg must not load");
    check(fx.log->errors.size() == 1 && fx.log->errors[0].find("no SVG rasterizer is registered") != std::string::npos,
          "the missing rasterizer must be reported");
    endCase();
}

void caseTextOnlySvgLogsCause()
{
    beginCase("svg: an SVG with a size but only <text> draws nothing and logs why");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string path = writeFile(
        "text_only.svg",
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\">"
        "<text x=\"4\" y=\"40\" font-size=\"32\">SVG</text></svg>");
    for (int i = 0; i < 2; ++i)
    {
        VectorImageProvider p(path);
        p.prepareDraw(16.0f, 16.0f);
        check(!p.isReferenceValid(), "a text-only SVG must have no image");
    }
    check(fx.log->errors.size() == 1, "expected 1 error, got " + std::to_string(fx.log->errors.size()));
    if (fx.log->errors.size() == 1)
        check(fx.log->errors[0].find("text_only.svg") != std::string::npos &&
                  fx.log->errors[0].find("<text>") != std::string::npos,
              "the error must name the file and say that <text> is skipped: " + fx.log->errors[0]);
    check(fx.gpu->created == 0, "no texture may be made for it");
    endCase();
}

void caseFailedSourceChangeLeavesNoImage()
{
    beginCase("svg: changing the source to a missing file leaves no image (no freed texture)");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string good = writeFile("red3.svg", kRedSquareSvg);
    VectorImageProvider p(good);
    p.prepareDraw(20.0f, 20.0f);
    check(p.isReferenceValid(), "the first file must load");
    p.setSourceUrl((g_dir / "gone.svg").string().c_str());
    p.prepareDraw(20.0f, 20.0f);
    check(fx.gpu->live.empty(), "the first texture must be freed");
    check(!p.isReferenceValid(), "after a failed change the provider must not report a valid image");
    check(p.getWidth() == 0 && p.getHeight() == 0, "after a failed change the size must be 0x0");
    // A later good file must work again.
    p.setSourceUrl(good.c_str());
    p.prepareDraw(20.0f, 20.0f);
    check(p.isReferenceValid(), "a later good file must load");
    check(!fx.gpu->doubleDestroy, "no texture may be destroyed twice");
    endCase();
}

void caseMissingAndBrokenFilesLogOnce()
{
    beginCase("svg: a missing or broken file draws nothing and logs one error with the cause");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string missing = (g_dir / "missing.svg").string();
    const std::string broken = writeFile("broken.svg", "this is not xml");
    for (int i = 0; i < 3; ++i)
    {
        VectorImageProvider p(missing);
        p.prepareDraw(16.0f, 16.0f);
        p.prepareDraw(16.0f, 16.0f);
        check(!p.isReferenceValid(), "a missing file must have no image");
    }
    VectorImageProvider q(broken);
    q.prepareDraw(16.0f, 16.0f);
    check(!q.isReferenceValid(), "a broken file must have no image");
    check(fx.log->errors.size() == 2, "expected 2 errors (one per URL), got " + std::to_string(fx.log->errors.size()));
    if (fx.log->errors.size() == 2)
    {
        check(fx.log->errors[0].find("missing.svg") != std::string::npos &&
                  fx.log->errors[0].find("does not exist") != std::string::npos,
              "the first error must name the file and the cause: " + fx.log->errors[0]);
        check(fx.log->errors[1].find("broken.svg") != std::string::npos, "the second error must name the file");
    }
    check(fx.gpu->created == 0, "no texture may be made for a failed file");
    endCase();
}

void caseShutdownFreesAndRefuses()
{
    beginCase("svg: shutdown frees cached textures and later loads draw nothing");
    Fixture fx;
    auto rasterizer = std::make_shared<StandaloneSvgRasterizer>();
    PlatformRegistry::instance().setSvgRasterizer(rasterizer);
    const std::string path = writeFile("red2.svg", kRedSquareSvg);
    auto kept = std::make_unique<VectorImageProvider>(path);
    kept->prepareDraw(20.0f, 20.0f);
    check(fx.gpu->live.size() == 1, "one texture must be live");
    rasterizer->shutdown();
    check(fx.gpu->live.empty(), "shutdown must free the texture");
    VectorImageProvider later(path);
    later.prepareDraw(20.0f, 20.0f);
    check(!later.isReferenceValid(), "a load after shutdown must draw nothing");
    kept.reset(); // releasing after shutdown must not destroy twice
    check(!fx.gpu->doubleDestroy, "no texture may be destroyed twice");
    endCase();
}

void caseSkippedPartsWarnOnce()
{
    beginCase("svg: a file with shapes and <text> draws the shapes and warns once per URL about the text");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string path = writeFile(
        "with_text.svg",
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"10\" viewBox=\"0 0 20 10\">"
        "<rect width=\"10\" height=\"10\" fill=\"#ff0000\"/><text x=\"12\" y=\"8\">A</text></svg>");
    for (int i = 0; i < 2; ++i)
    {
        VectorImageProvider p(path);
        p.prepareDraw(20.0f, 20.0f);
        check(p.isReferenceValid(), "the shapes must draw");
    }
    check(fx.log->errors.empty(), "a file with shapes logs no error");
    check(fx.log->warnings.size() == 1, "expected 1 warning, got " + std::to_string(fx.log->warnings.size()));
    if (fx.log->warnings.size() == 1)
        check(fx.log->warnings[0].find("with_text.svg") != std::string::npos &&
                  fx.log->warnings[0].find("<text>") != std::string::npos,
              "the warning must name the file and <text>: " + fx.log->warnings[0]);
    if (fx.gpu->lastPixels.size() == 40u * 20u * 4u)
    {
        const uint8_t* red = &fx.gpu->lastPixels[(10 * 40 + 10) * 4];
        check(red[0] == 255 && red[1] == 0 && red[2] == 0 && red[3] == 255, "the rectangle must be opaque red");
    }
    endCase();
}

std::string readWholeFile(const std::filesystem::path& path)
{
    std::ifstream file(path, std::ios::binary);
    std::stringstream text;
    text << file.rdbuf();
    return text.str();
}

/// Files whose small differences from Chrome come from how Chrome itself
/// places short dashes on curves and samples the seam of a repeated gradient;
/// the rest of each file is held to the general limit.
bool hasKnownChromeDifference(const std::string& name)
{
    return name == "stroke_dash" || name == "gradient_linear";
}

void caseMatchesChrome()
{
    beginCase("svg: every file of tests/svg_corpus paints like Google Chrome (tests/svg_corpus/chrome)");
    const std::filesystem::path corpus = OVUI_SVG_CORPUS_DIR;
    std::vector<std::filesystem::path> files;
    for (const char* folder : { "", "icons" })
    {
        std::error_code error;
        for (const auto& entry : std::filesystem::directory_iterator(corpus / folder, error))
        {
            if (entry.path().extension() == ".svg")
                files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());
    check(files.size() >= 70, "the corpus must have its files, found " + std::to_string(files.size()));
    double worstMean = 0.0;
    for (const auto& svgPath : files)
    {
        const std::string name = svgPath.stem().string();
        const std::filesystem::path relative = std::filesystem::relative(svgPath.parent_path(), corpus);
        const std::filesystem::path pngPath = corpus / "chrome" / relative / (name + ".png");
        const std::string png = readWholeFile(pngPath);
        int width = 0, height = 0, channels = 0;
        stbi_uc* expected = png.empty() ? nullptr :
                                          stbi_load_from_memory(reinterpret_cast<const stbi_uc*>(png.data()),
                                                                static_cast<int>(png.size()), &width, &height,
                                                                &channels, 4);
        if (!expected)
        {
            check(false, "missing or unreadable Chrome picture " + pngPath.string());
            continue;
        }
        omni::ui::standalone::svg::Document doc;
        std::string error;
        const bool parsed = omni::ui::standalone::svg::parseSvgDocument(readWholeFile(svgPath), doc, error);
        check(parsed, name + ": must parse: " + error);
        check(doc.skipped.empty() && doc.changed.empty(), name + ": every part must be drawn as in the file");
        std::vector<uint8_t> actual;
        std::vector<std::string> changed;
        if (parsed)
            check(omni::ui::standalone::svg::renderSvgDocument(doc, static_cast<uint32_t>(width),
                                                               static_cast<uint32_t>(height), actual, error, changed) &&
                      changed.empty(),
                  name + ": must paint as in the file: " + error);
        if (actual.size() == static_cast<size_t>(width) * height * 4)
        {
            // Compare premultiplied colors, so that the color of an almost
            // transparent pixel does not count more than its alpha.
            double sum = 0.0;
            size_t farPixels = 0; // not `far`: <windows.h> defines `far` as an empty macro
            const size_t pixels = static_cast<size_t>(width) * height;
            for (size_t i = 0; i < pixels; ++i)
            {
                int worst = 0;
                const int ea = expected[i * 4 + 3], aa = actual[i * 4 + 3];
                for (int c = 0; c < 4; ++c)
                {
                    const int e = c == 3 ? ea : (expected[i * 4 + c] * ea + 127) / 255;
                    const int a = c == 3 ? aa : (actual[i * 4 + c] * aa + 127) / 255;
                    const int d = std::abs(e - a);
                    sum += d;
                    worst = std::max(worst, d);
                }
                if (worst > 96)
                    ++farPixels;
            }
            const double mean = sum / (pixels * 4.0);
            const double farShare = 100.0 * static_cast<double>(farPixels) / static_cast<double>(pixels);
            const double farLimit = hasKnownChromeDifference(name) ? 0.75 : 0.25;
            worstMean = std::max(worstMean, mean);
            check(mean <= 1.5, name + ": mean difference " + std::to_string(mean) + " > 1.5 (of 255)");
            check(farShare <= farLimit, name + ": " + std::to_string(farShare) + "% of the pixels differ by more than 96 (limit " +
                                            std::to_string(farLimit) + "%)");
        }
        else
        {
            check(false, name + ": no bitmap of " + std::to_string(width) + "x" + std::to_string(height));
        }
        stbi_image_free(expected);
    }
    std::cout << "       " << files.size() << " files, largest mean difference " << worstMean << " (of 255)" << std::endl;
    endCase();
}

void caseBrokenInputFailsCleanly()
{
    beginCase("svg: cut-off and changed files, and numbers and transforms near the double limit, are refused with a "
              "cause or drawn, without a crash");
    const std::filesystem::path corpus = OVUI_SVG_CORPUS_DIR;
    std::vector<std::string> texts;
    for (const char* folder : { "", "icons" })
    {
        std::error_code error;
        for (const auto& entry : std::filesystem::directory_iterator(corpus / folder, error))
        {
            if (entry.path().extension() == ".svg")
                texts.push_back(readWholeFile(entry.path()));
        }
    }
    std::string deep = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\">";
    for (int i = 0; i < 5000; ++i)
        deep += "<g>";
    texts.push_back(deep);
    texts.push_back("<svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" "
                    "width=\"8\" height=\"8\"><g id=\"a\"><use href=\"#a\"/><use xlink:href=\"#b\"/></g>"
                    "<use id=\"b\" href=\"#a\"/></svg>");
    texts.push_back("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\"><path d=\"M0 0 L1e308 1e308 "
                    "C-1e308 5 5 -1e308 1e-308 1e308 Z\" stroke=\"red\" stroke-width=\"1e300\" "
                    "stroke-dasharray=\"1e-300\"/><circle r=\"1e308\"/></svg>");
    // An edge of height 1e-308 next to coordinates of 1e308: its slope overflows.
    texts.push_back("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\"><path d=\"M0 0 L1e308 1e308 "
                    "C-1e308 5 5 -1 308 1e-308 1e308 Z\" stroke=\"red\" stroke-width=\"1e300\" "
                    "stroke-dasharray=\"1e-300\"/><circle r=\"1e308\"/></svg>");
    texts.push_back("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\"><path d=\"M0 0 L8 8\" "
                    "stroke=\"red\" stroke-dasharray=\"0.00001 0.00001\"/><rect width=\"8\" height=\"8\" "
                    "fill=\"url(#none)\" stroke=\"url(#none) blue\"/></svg>");
    // Transforms whose products overflow to infinity and then to NaN.
    texts.push_back("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\">"
                    "<g transform=\"scale(1e200) scale(1e200) translate(1e308 -1e308)\"><path d=\"M0 0 C1 2 3 4 5 6 Z\" "
                    "stroke=\"red\" stroke-width=\"3\" stroke-linejoin=\"round\" stroke-linecap=\"round\" "
                    "stroke-dasharray=\"1 2\"/><circle r=\"2\" fill=\"url(#g)\"/></g>"
                    "<linearGradient id=\"g\" gradientTransform=\"matrix(1e308 1e308 1e308 1e308 0 0)\">"
                    "<stop offset=\"0\"/><stop offset=\"1\" stop-color=\"red\"/></linearGradient>"
                    "<g transform=\"matrix(1e308 0 0 1e308 1e308 -1e308)\" opacity=\"0.5\" clip-path=\"url(#c)\">"
                    "<rect width=\"1\" height=\"1\" stroke=\"blue\" stroke-dasharray=\"0.5\"/></g>"
                    "<clipPath id=\"c\"><circle r=\"1e308\"/></clipPath></svg>");
    std::mt19937 random(12345);
    const char pieces[] = "<>/=\"' -.e0123456789#(),;:&MLCQAZz";
    size_t parsed = 0, refused = 0;
    auto tryText = [&](const std::string& text) {
        omni::ui::standalone::svg::Document doc;
        std::string error;
        if (omni::ui::standalone::svg::parseSvgDocument(text, doc, error))
        {
            std::vector<uint8_t> rgba;
            std::vector<std::string> changed;
            if (!omni::ui::standalone::svg::renderSvgDocument(doc, 12, 12, rgba, error, changed))
                check(!error.empty(), "a refused painting must name the cause");
            ++parsed;
        }
        else
        {
            check(!error.empty(), "a refused file must name the cause");
            ++refused;
        }
    };
    for (const std::string& text : texts)
    {
        tryText(text);
        for (size_t length = 0; length < text.size(); length += 7)
            tryText(text.substr(0, length));
        for (int i = 0; i < 40 && !text.empty(); ++i)
        {
            std::string changed = text;
            const size_t at = random() % changed.size();
            changed[at] = pieces[random() % (sizeof(pieces) - 1)];
            tryText(changed);
        }
    }
    std::cout << "       " << parsed << " drawn, " << refused << " refused" << std::endl;
    check(parsed > 0 && refused > 0, "both drawn and refused files are expected");
    endCase();
}


// ---------------------------------------------------------------------------
// Files whose work multiplies. Each runs on its own thread while this thread
// watches the time and the resident memory of the process. Past a bound the
// test fails at once and the process ends, because the work cannot be stopped.
// ---------------------------------------------------------------------------

/// The resident memory of this process in bytes; 0 where it is not known.
size_t residentBytes()
{
#if defined(__linux__)
    std::ifstream statm("/proc/self/statm");
    size_t pages = 0, resident = 0;
    statm >> pages >> resident;
    return resident * static_cast<size_t>(sysconf(_SC_PAGESIZE));
#elif defined(_WIN32)
    PROCESS_MEMORY_COUNTERS counters{};
    if (GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters)))
        return counters.WorkingSetSize;
    return 0;
#else
    return 0;
#endif
}

/// Bounds of one file. The fixed reader needs a small part of each (see the
/// numbers that the case prints); the reader without the limits needs much
/// more of one of them for every file of the case.
constexpr double kBoundSeconds = 20.0;
constexpr size_t kBoundBytes = 768u * 1024u * 1024u;

struct BoundedResult
{
    bool drawn = false;
    std::string error;
    StandaloneSvgRasterizer::Bitmap bitmap;
    std::vector<std::string> skipped;
    std::vector<std::string> changed;
    double seconds = 0.0;
    size_t growth = 0; ///< the largest growth of the resident memory seen
};

/// Runs `work` on a thread within kBoundSeconds and kBoundBytes. Past a bound
/// the test fails and the process ends at once: the work cannot be stopped.
/// Returns the time and the largest growth of the resident memory.
std::pair<double, size_t> runWatched(const std::string& name, const std::function<void()>& work)
{
    std::atomic<bool> done{ false };
    size_t growth = 0;
    const size_t start = residentBytes();
    const auto t0 = std::chrono::steady_clock::now();
    std::thread worker([&] {
        work();
        done = true;
    });
    while (!done)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
        const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        const size_t now = residentBytes();
        if (now > start)
            growth = std::max(growth, now - start);
        if (seconds > kBoundSeconds || growth > kBoundBytes)
        {
            std::cout << "FAIL " << g_caseName << std::endl
                      << "       " << name << ": "
                      << (seconds > kBoundSeconds ? "no result after " + std::to_string(seconds) + " s" :
                                                    "the memory grew by " + std::to_string(growth >> 20) + " MiB")
                      << " (bounds " << kBoundSeconds << " s, " << (kBoundBytes >> 20) << " MiB); the work cannot "
                      << "be stopped, so the test ends here" << std::endl;
            std::_Exit(1);
        }
    }
    worker.join();
    return { std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(), growth };
}

/// rasterizeToBitmap() of `text` at a square widget of `widget` pixels, on a
/// thread, within kBoundSeconds and kBoundBytes.
BoundedResult rasterizeBounded(const std::string& name, const std::string& text, float widget)
{
    BoundedResult result;
    const auto [seconds, growth] = runWatched(name, [&] {
        try
        {
            result.drawn = StandaloneSvgRasterizer::rasterizeToBitmap(text, widget, widget, result.bitmap, result.error,
                                                                      &result.skipped, &result.changed);
        }
        catch (const std::exception& e)
        {
            result.error = std::string("exception: ") + e.what();
        }
    });
    result.seconds = seconds;
    result.growth = growth;
    return result;
}

const std::string kSvgOpen = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\">";

std::string repeat(const std::string& text, size_t count)
{
    std::string out;
    out.reserve(text.size() * count);
    for (size_t i = 0; i < count; ++i)
        out += text;
    return out;
}

/// `levels` groups that each use the group below twice (2^levels copies of a
/// full-size rectangle).
std::string useFanOut(int levels)
{
    std::string text = kSvgOpen + "<defs><rect id=\"a0\" width=\"64\" height=\"64\" fill=\"#36c\"/>";
    for (int n = 1; n <= levels; ++n)
        text += "<g id=\"a" + std::to_string(n) + "\"><use href=\"#a" + std::to_string(n - 1) + "\"/><use href=\"#a" +
                std::to_string(n - 1) + "\"/></g>";
    return text + "</defs><use href=\"#a" + std::to_string(levels) + "\"/></svg>";
}

void caseMultiplyingFilesAreBounded()
{
    beginCase("svg: files whose work multiplies are refused with their limit, each within " +
              std::to_string(static_cast<int>(kBoundSeconds)) + " s and " + std::to_string(kBoundBytes >> 20) +
              " MiB");
    struct Hostile
    {
        std::string name;
        std::string text;
        float widget;
        std::string cause; ///< a part of the expected error; empty: the file draws
    };
    std::vector<Hostile> files;
    const std::string deepGroups = repeat("<g>", 100) + "<rect width=\"64\" height=\"64\" fill=\"#2a7\"/>" +
                                   repeat("</g>", 100);
    // Review 6429047566 point 1: 862 bytes; the old matcher tried every way to
    // place the 12 parts on 100 ancestors. Nothing matches "x": it draws green.
    files.push_back({ "selector over 100 nested groups",
                      kSvgOpen + "<style>x g g g g g g g g g g g g{fill:red}</style>" + deepGroups + "</svg>", 32.0f,
                      "" });
    // 200,000 attributes on one element, 2.6 MB: the old reader compared each
    // name with every earlier name of the element. It draws green.
    {
        std::string attributes;
        for (int n = 0; n < 200000; ++n)
            attributes += " a" + std::to_string(n) + "=\"1\"";
        files.push_back({ "200,000 attributes on one element",
                          kSvgOpen + "<rect width=\"64\" height=\"64\" fill=\"#2a7\"" + attributes + "/></svg>",
                          32.0f, "" });
    }
    // The same kind of selector, 400 times over 254 nested groups: past the
    // number of selector tests.
    files.push_back({ "400 such selectors over 254 nested groups",
                      kSvgOpen + "<style>" + repeat("x g g g g g g g g g g g g{fill:red}", 400) + "</style>" +
                          repeat("<g>", 254) + "<rect width=\"64\" height=\"64\"/>" + repeat("</g>", 254) + "</svg>",
                      32.0f, "selector tests and declarations" });
    // Point 2A: a 1 MiB entity used 30,000 times (30 GiB of text).
    files.push_back({ "a 1 MiB entity used 30,000 times",
                      "<!DOCTYPE svg [<!ENTITY a \"" + std::string(1 << 20, 'A') + "\">]>" + kSvgOpen + "<desc>" +
                          repeat("&a;", 30000) + "</desc><rect width=\"64\" height=\"64\"/></svg>",
                      32.0f, "entity references add more than 1048576 bytes of text" });
    // Point 2B: 30 levels of two <use> each (2^30 shapes), 1.7 KB.
    files.push_back({ "30 levels of two <use>", useFanOut(30), 32.0f, "more than 100000 groups and shapes" });
    // Point 3, inline declarations: a rect with a 5,000-declaration style
    // attribute, repeated by 20 levels of two <use>. The inline parse, sort
    // and apply are charged, so the <use> fan-out cannot multiply them.
    {
        std::string inlineRect = kSvgOpen + "<defs><rect id=\"a0\" width=\"64\" height=\"64\" style=\"" +
                                 repeat("fill:red;", 5000) + "\"/>";
        for (int n = 1; n <= 20; ++n)
            inlineRect += "<g id=\"a" + std::to_string(n) + "\"><use href=\"#a" + std::to_string(n - 1) +
                          "\"/><use href=\"#a" + std::to_string(n - 1) + "\"/></g>";
        inlineRect += "</defs><use href=\"#a20\"/></svg>";
        files.push_back({ "5,000 inline declarations repeated by two <use> for 20 levels", inlineRect, 32.0f,
                          "selector tests and declarations" });
    }
    // Point 3A: a list of 5,000 selectors with 5,000 declarations, 55 KB.
    files.push_back({ "5,000 selectors with 5,000 declarations",
                      kSvgOpen + "<style>" + repeat("g,", 4999) + "g{" + repeat("fill:red;", 5000) +
                          "}</style><g><rect width=\"64\" height=\"64\"/></g></svg>",
                      32.0f, "more than 100000 selector and declaration pairs" });
    // Point 3B: a gradient with 500,000 stops, used by 20 shapes, 3.5 MB.
    std::string rects;
    for (int i = 0; i < 20; ++i)
        rects += "<rect x=\"" + std::to_string((i % 5) * 12 + 2) + "\" y=\"" + std::to_string((i / 5) * 16 + 2) +
                 "\" width=\"10\" height=\"14\" fill=\"url(#g)\"/>";
    files.push_back({ "a gradient with 500,000 stops",
                      kSvgOpen + "<linearGradient id=\"g\">" + repeat("<stop/>", 500000) +
                          "<stop offset=\"1\" stop-color=\"#36c\"/></linearGradient>" + rects + "</svg>",
                      32.0f, "a gradient has more than 4096 stops" });
    // 1,000,001 empty groups, 4 MB: past the number of XML elements.
    files.push_back({ "1,000,001 elements", kSvgOpen + repeat("<g/>", 1000001) + "</svg>", 32.0f,
                      "more than 1000000 XML elements" });
    // 30 <use> levels that each hold 250 nested groups: 7,500 levels deep
    // (the reader without the depth limit ran out of stack).
    std::string nested = kSvgOpen + "<defs><rect id=\"d0\" width=\"64\" height=\"64\"/>";
    for (int n = 1; n <= 30; ++n)
        nested += "<g id=\"d" + std::to_string(n) + "\">" + repeat("<g>", 249) + "<use href=\"#d" +
                  std::to_string(n - 1) + "\"/>" + repeat("</g>", 249) + "</g>";
    files.push_back({ "250 nested groups in each of 30 <use> levels", nested + "</defs><use href=\"#d30\"/></svg>",
                      32.0f, "nested deeper than 256 levels" });
    // 250 nested groups with opacity, each a layer of the whole 2048 x 2048 bitmap.
    files.push_back({ "250 nested group layers at 2048 x 2048",
                      kSvgOpen + repeat("<g opacity=\"0.99\">", 250) + "<rect width=\"64\" height=\"64\"/>" +
                          repeat("</g>", 250) + "</svg>",
                      1024.0f, "MiB for its group layers" });
    // 20,000 curves whose control points are far out: 4,096 line pieces each.
    files.push_back({ "20,000 curves of 4,096 line pieces each",
                      kSvgOpen + "<path d=\"M32 32" + repeat(" C1e6 1e6 -1e6 -1e6 32 32", 20000) +
                          "\" fill=\"none\" stroke=\"#36c\"/></svg>",
                      32.0f, "line pieces" });
    // 1,024 copies of a full-size rectangle at 2048 x 2048: 4 billion pixels.
    files.push_back({ "1,024 full-size shapes at 2048 x 2048", useFanOut(10), 1024.0f, "pixel visits" });

    for (const Hostile& file : files)
    {
        const BoundedResult r = rasterizeBounded(file.name, file.text, file.widget);
        std::cout << "       " << file.name << " (" << file.text.size() << " bytes): "
                  << (r.drawn ? "drawn" : "refused: " + r.error) << "; " << r.seconds << " s, +"
                  << (r.growth >> 20) << " MiB" << std::endl;
        if (file.cause.empty())
        {
            check(r.drawn, file.name + ": must draw: " + r.error);
            if (r.drawn && r.bitmap.rgba.size() == 64u * 64u * 4u)
            {
                const uint8_t* c = &r.bitmap.rgba[(32 * 64 + 32) * 4];
                check(c[0] == 0x22 && c[1] == 0xaa && c[2] == 0x77 && c[3] == 255,
                      file.name + ": no rule matches, so the rectangle stays green");
            }
            continue;
        }
        check(!r.drawn, file.name + ": must be refused");
        check(r.error.find(file.cause) != std::string::npos,
              file.name + ": the error must name the limit ('" + file.cause + "'): " + r.error);
        check(r.bitmap.rgba.empty() || !r.drawn, file.name + ": a refused file has no bitmap");
    }
    endCase();
}

void caseFileOverALimitLogsItsCauseOnce()
{
    beginCase("svg: a file over a limit has no image and logs one error that names the file and the limit");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string path = writeFile("fan_out.svg", useFanOut(30));
    // The reader without the limits allocates without end for this file, so
    // the provider runs within the same bounds as the cases above.
    runWatched("30 levels of two <use> through VectorImageProvider", [&] {
        for (int i = 0; i < 2; ++i)
        {
            VectorImageProvider p(path);
            try
            {
                p.prepareDraw(32.0f, 32.0f);
            }
            catch (...)
            {
                check(false, "no exception may leave prepareDraw()");
            }
            check(!p.isReferenceValid(), "a file over a limit must have no image");
        }
    });
    check(fx.log->errors.size() == 1, "expected 1 error, got " + std::to_string(fx.log->errors.size()));
    if (fx.log->errors.size() == 1)
        check(fx.log->errors[0].find("SVG: cannot draw '") != std::string::npos &&
                  fx.log->errors[0].find("fan_out.svg") != std::string::npos &&
                  fx.log->errors[0].find("too complex to draw") != std::string::npos &&
                  fx.log->errors[0].find("100000 groups and shapes") != std::string::npos,
              "the error must name the file and the limit: " + fx.log->errors[0]);
    check(fx.gpu->created == 0, "no texture may be made for a refused file");
    endCase();
}

void caseExceptionLeavesNoImageAndLogsOnce()
{
    beginCase("svg: an exception while a file is read or painted leaves no image and logs the cause once per URL");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string path = writeFile("throws.svg", kRedSquareSvg);
    for (int i = 0; i < 2; ++i)
    {
        omni::ui::standalone::g_svgThrowOnNextDrawForTest = 1; // std::bad_alloc
        VectorImageProvider p(path);
        try
        {
            p.prepareDraw(20.0f, 20.0f);
        }
        catch (...)
        {
            check(false, "no exception may leave prepareDraw()");
        }
        check(!p.isReferenceValid(), "after the exception the provider must have no image");
    }
    check(fx.log->errors.size() == 1, "the same cause must be logged once, got " + std::to_string(fx.log->errors.size()));
    if (!fx.log->errors.empty())
        check(fx.log->errors[0].find("throws.svg") != std::string::npos &&
                  fx.log->errors[0].find("std::bad_alloc") != std::string::npos,
              "the error must name the file and std::bad_alloc: " + fx.log->errors[0]);
    // The next read of the same file draws (the reader and painter of the
    // thread work after the exception), and then another exception is new.
    {
        VectorImageProvider ok(path);
        ok.prepareDraw(30.0f, 30.0f);
        check(ok.isReferenceValid(), "after an exception the next read of the file must draw");
    }
    omni::ui::standalone::g_svgThrowOnNextDrawForTest = 2; // std::runtime_error
    VectorImageProvider again(path);
    try
    {
        again.prepareDraw(40.0f, 40.0f);
    }
    catch (...)
    {
        check(false, "no exception may leave prepareDraw()");
    }
    check(!again.isReferenceValid(), "after the exception the provider must have no image");
    check(fx.log->errors.size() == 2, "a later failure after a good draw must be logged, got " +
                                          std::to_string(fx.log->errors.size()));
    if (fx.log->errors.size() == 2)
        check(fx.log->errors[1].find("injected failure for the test") != std::string::npos,
              "the second error must give the cause: " + fx.log->errors[1]);
    omni::ui::standalone::g_svgThrowOnNextDrawForTest = 0;
    endCase();
}

void caseErrorIsLoggedAgainAfterTheFileDraws()
{
    beginCase("svg: an error is logged once while it lasts, and again when it comes back after the file drew");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string path = (g_dir / "comes_and_goes.svg").string();
    auto load = [&](float size) {
        VectorImageProvider p(path);
        p.prepareDraw(size, size);
        return p.isReferenceValid();
    };
    check(!load(16.0f) && !load(16.0f), "a missing file has no image");
    check(fx.log->errors.size() == 1, "one error while the file is missing, got " + std::to_string(fx.log->errors.size()));
    writeFile("comes_and_goes.svg", kRedSquareSvg);
    check(load(17.0f), "the file draws when it is there");
    std::filesystem::remove(path);
    check(!load(18.0f), "a missing file has no image");
    check(fx.log->errors.size() == 2, "the error must be logged again after the file drew, got " +
                                          std::to_string(fx.log->errors.size()));
    endCase();
}

/// The bitmap of `text` at a 32 px widget (64 x 64 for a 64 x 64 file).
BoundedResult draw64(const std::string& text)
{
    return rasterizeBounded("file", text, 32.0f);
}

const uint8_t* pixel(const BoundedResult& r, int x, int y)
{
    static const uint8_t kNone[4] = { 0, 0, 0, 0 };
    if (!r.drawn || r.bitmap.width != 64 || r.bitmap.height != 64)
        return kNone;
    return &r.bitmap.rgba[(static_cast<size_t>(y) * 64 + static_cast<size_t>(x)) * 4];
}

bool hasText(const std::vector<std::string>& list, const std::string& part)
{
    for (const std::string& item : list)
    {
        if (item.find(part) != std::string::npos)
            return true;
    }
    return false;
}

void caseFallbacksNameTheirCause()
{
    beginCase("svg: a dash pattern too fine to draw, a deep <use> chain and numbers below the double range are drawn "
              "as browsers do, and each fallback is reported with its cause");
    // Dashes of 0.0004: drawn as one line with half the cover, and reported.
    const BoundedResult dash = draw64(kSvgOpen + "<path d=\"M2 32 H62\" stroke=\"black\" stroke-width=\"4\" "
                                                 "stroke-dasharray=\"0.0004 0.0004\"/></svg>");
    const uint8_t* d = pixel(dash, 32, 32);
    check(dash.drawn && d[3] >= 120 && d[3] <= 136, "the dashes cover half the line: alpha " + std::to_string(d[3]));
    check(hasText(dash.changed, "dash pattern") && hasText(dash.changed, "100000 dashes"),
          "the dash fallback must be reported with its cause");
    // With square caps the same dashes cover the whole line.
    const BoundedResult capped =
        draw64(kSvgOpen + "<path d=\"M2 32 H62\" stroke=\"black\" stroke-width=\"4\" stroke-linecap=\"square\" "
                          "stroke-dasharray=\"0.0004 0.0004\"/></svg>");
    check(pixel(capped, 32, 32)[3] == 255, "square caps of tiny dashes cover the line");
    // A chain of 40 <use> that is not a cycle draws (Chrome draws it).
    std::string chain = kSvgOpen + "<defs><g id=\"u0\"><rect x=\"8\" y=\"8\" width=\"48\" height=\"48\" "
                                   "fill=\"#36c\"/></g>";
    for (int n = 1; n <= 40; ++n)
        chain += "<g id=\"u" + std::to_string(n) + "\"><use href=\"#u" + std::to_string(n - 1) + "\"/></g>";
    const BoundedResult deep = draw64(chain + "</defs><use href=\"#u40\"/></svg>");
    const uint8_t* b = pixel(deep, 32, 32);
    check(deep.drawn && b[0] == 0x33 && b[1] == 0x66 && b[2] == 0xcc && b[3] == 255,
          "a <use> chain of 40 must draw its rectangle: " + deep.error);
    check(deep.skipped.empty(), "a chain that is not a cycle must not be reported as one");
    // A cycle keeps its own message.
    const BoundedResult cycle =
        draw64(kSvgOpen + "<g id=\"a\"><rect width=\"8\" height=\"8\"/><use href=\"#a\"/></g></svg>");
    check(hasText(cycle.skipped, "refers to itself"), "a cycle must be reported as a cycle");
    // 1e-400 is 0; 1e400 is an error of the path data: drawn up to it, reported.
    const BoundedResult under = draw64(kSvgOpen + "<path d=\"M4 4 L60 4 L1e-400 60 L60 60 Z\"/></svg>");
    check(pixel(under, 32, 8)[3] == 255 && pixel(under, 32, 56)[3] == 255,
          "1e-400 must be read as 0: both triangles of the path are drawn");
    check(under.changed.empty() && under.skipped.empty(), "a number below the double range is not an error");
    const BoundedResult over =
        draw64(kSvgOpen + "<path d=\"M4 4 L60 4 L60 60 Z M4 40 L1e400 60 L4 60 Z\"/></svg>");
    check(pixel(over, 50, 20)[3] == 255, "the path is drawn up to the error");
    check(hasText(over.changed, "drawn up to the error"), "a path data error must be reported");
    endCase();
}

void caseMalformedXmlIsRefusedWithItsPlace()
{
    beginCase("svg: malformed XML is refused with its line, column and cause; escaped and valid controls draw");
    const std::string rect = "<rect width=\"64\" height=\"64\" fill=\"red\"/>";
    struct Bad
    {
        std::string text;
        std::string cause;
    };
    const Bad bad[] = {
        { kSvgOpen + "<rect width=\"64\" height=\"64\" fill=\"red\" data-note=\"<\"/></svg>",
          "line 1, column 115: a '<' in the value of data-note" },
        { kSvgOpen + "<!-- bad--comment -->" + rect + "</svg>", "line 1, column 72: '--' inside a comment" },
        { kSvgOpen + "<!-- ends with a dash --->" + rect + "</svg>", "'--' inside a comment" },
        { kSvgOpen + "<!oops>" + rect + "</svg>", "line 1, column 64: an unknown markup declaration <!oops>" },
        { kSvgOpen + "\n<!DOCTYPE svg>" + rect + "</svg>", "line 2, column 1: a <!DOCTYPE> that is not the only one" },
    };
    for (const Bad& b : bad)
    {
        const BoundedResult r = draw64(b.text);
        check(!r.drawn, "malformed XML must be refused: " + b.text);
        check(r.error.find("not a valid SVG (XML error on ") != std::string::npos &&
                  r.error.find(b.cause) != std::string::npos,
              "the error must give '" + b.cause + "': " + r.error);
    }
    const std::string good[] = {
        kSvgOpen + "<rect width=\"64\" height=\"64\" fill=\"green\" data-note=\"&lt;\"/></svg>",
        kSvgOpen + "<!-- a normal comment --><rect width=\"64\" height=\"64\" fill=\"green\"/></svg>",
        "<?xml version=\"1.0\"?><!DOCTYPE svg PUBLIC \"-//W3C//DTD SVG 1.1//EN\" "
        "\"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd\">" +
            kSvgOpen + "<!---->" + "<rect width=\"64\" height=\"64\" fill=\"green\"/></svg>",
    };
    for (const std::string& text : good)
    {
        const BoundedResult r = draw64(text);
        check(r.drawn && pixel(r, 32, 32)[1] == 0x80 && pixel(r, 32, 32)[3] == 255,
              "a valid file must draw green: " + r.error);
    }
    endCase();
}

void caseRootEffectsWarnOnce()
{
    beginCase("svg: a filter or mask on the root <svg> draws the shapes and warns once per URL, as on a child");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgRasterizer>());
    const std::string shapes = "<rect x=\"16\" y=\"16\" width=\"32\" height=\"32\" fill=\"red\"/>";
    struct File
    {
        const char* name;
        std::string text;
        const char* part;
    };
    const File files[] = {
        { "root_filter.svg",
          "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" filter=\"url(#f)\"><filter id=\"f\">"
          "<feGaussianBlur stdDeviation=\"4\"/></filter>" + shapes + "</svg>",
          "filter" },
        { "root_mask.svg",
          "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" mask=\"url(#m)\"><mask id=\"m\">"
          "<rect width=\"32\" height=\"64\" fill=\"white\"/></mask>" + shapes + "</svg>",
          "mask" },
        { "child_filter.svg",
          kSvgOpen + "<filter id=\"f\"><feGaussianBlur stdDeviation=\"4\"/></filter><g filter=\"url(#f)\">" + shapes +
              "</g></svg>",
          "filter" },
        { "root_transform.svg",
          "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" transform=\"rotate(10)\">" + shapes +
              "</svg>",
          "transform on <svg>" },
        { "nested_transform.svg",
          kSvgOpen + "<svg transform=\"translate(32 32)\" width=\"64\" height=\"64\">" + shapes + "</svg></svg>",
          "transform on <svg>" },
    };
    for (const File& file : files)
    {
        const size_t before = fx.log->warnings.size();
        const std::string path = writeFile(file.name, file.text);
        for (float size : { 32.0f, 32.0f, 33.0f })
        {
            VectorImageProvider p(path);
            p.prepareDraw(size, size);
            check(p.isReferenceValid(), std::string(file.name) + ": the shapes must draw");
        }
        check(fx.log->warnings.size() == before + 1, std::string(file.name) + ": expected 1 warning, got " +
                                                         std::to_string(fx.log->warnings.size() - before));
        if (fx.log->warnings.size() == before + 1)
            check(fx.log->warnings.back().find(file.name) != std::string::npos &&
                      fx.log->warnings.back().find(std::string("ovui does not draw: ") + file.part) != std::string::npos,
                  std::string(file.name) + ": the warning must name the file and the part: " + fx.log->warnings.back());
    }
    check(fx.log->errors.empty(), "these files log no error");
    endCase();
}

void caseDocumentSizeOutOfRangeIsRefused()
{
    beginCase("svg: a document size whose scale to the widget overflows is refused with a cause");
    StandaloneSvgRasterizer::Bitmap bitmap;
    std::string error;
    check(!StandaloneSvgRasterizer::rasterizeToBitmap("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1e-307\" "
                                                      "height=\"1e-307\" viewBox=\"0 0 1 1\"><rect width=\"1\" "
                                                      "height=\"1\"/></svg>",
                                                      48.0f, 48.0f, bitmap, error),
          "a 1e-307 document must be refused");
    check(error.find("the SVG size (1e-307 x 1e-307 pixels) is too small to scale") != std::string::npos,
          "the cause must be given with the size: " + error);
    error.clear();
    check(StandaloneSvgRasterizer::rasterizeToBitmap("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1e-300\" "
                                                     "height=\"2e-300\" viewBox=\"0 0 1 2\"><rect width=\"1\" "
                                                     "height=\"2\" fill=\"red\"/></svg>",
                                                     48.0f, 48.0f, bitmap, error) &&
              bitmap.width == 48 && bitmap.height == 96,
          "a tiny document with a finite scale draws at the widget size: " + error);
    endCase();
}

#endif // OMNIUI_HAS_SVG

void caseSvgOffDrawsNothingAndLogsCause()
{
    beginCase("svg off (OMNIUI_ENABLE_SVG=OFF): a provider has no image and each URL logs the cause once");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(std::make_shared<StandaloneSvgOffRasterizer>());
    const std::string first = writeFile("off_first.svg", kRedSquareSvg);
    const std::string second = writeFile("off_second.svg", kRedSquareSvg);
    for (int i = 0; i < 2; ++i)
    {
        VectorImageProvider p(first);
        p.prepareDraw(20.0f, 20.0f);
        p.prepareDraw(20.0f, 20.0f);
        check(!p.isReferenceValid(), "with the option OFF the provider has no image");
    }
    VectorImageProvider q(second);
    q.prepareDraw(20.0f, 20.0f);
    check(!q.isReferenceValid(), "with the option OFF the provider has no image");
    check(fx.log->errors.size() == 2, "expected 2 errors (one per URL), got " + std::to_string(fx.log->errors.size()));
    if (fx.log->errors.size() == 2)
    {
        check(fx.log->errors[0].find("off_first.svg") != std::string::npos &&
                  fx.log->errors[0].find("OMNIUI_ENABLE_SVG=OFF") != std::string::npos,
              "the first error must name the file and the option: " + fx.log->errors[0]);
        check(fx.log->errors[1].find("off_second.svg") != std::string::npos, "the second error must name the file");
    }
    check(fx.gpu->created == 0, "with the option OFF no texture is made");
    endCase();
}

void caseWithoutRasterizerDrawsNothingSilently()
{
    beginCase("no rasterizer registered: a provider has no image and nothing is logged");
    Fixture fx;
    PlatformRegistry::instance().setSvgRasterizer(nullptr);
    const std::string path = writeFile("plain.svg", kRedSquareSvg);
    VectorImageProvider p(path);
    p.prepareDraw(20.0f, 20.0f);
    check(!p.isReferenceValid(), "without a rasterizer the provider has no image");
    check(fx.log->errors.empty(), "without a rasterizer nothing is logged");
    check(fx.gpu->created == 0, "without a rasterizer no texture is made");
    endCase();
}

} // anonymous namespace

int main()
{
    g_dir = makeUniqueTempDir();
    if (g_dir.empty())
    {
        std::cout << "FAIL cannot make a new temporary folder" << std::endl;
        return 1;
    }

#ifdef OMNIUI_HAS_SVG
    caseDrawsPixelsAtWidgetAspect();
    caseBadSvgReportsCause();
    caseProviderShowsSvgAndFreesTexture();
    caseImageBackendSharesSvgTextureWithProvider();
    caseTextOnlySvgLogsCause();
    caseFailedSourceChangeLeavesNoImage();
    caseMissingAndBrokenFilesLogOnce();
    caseShutdownFreesAndRefuses();
    caseSkippedPartsWarnOnce();
    caseMatchesChrome();
    caseBrokenInputFailsCleanly();
    caseMultiplyingFilesAreBounded();
    caseFileOverALimitLogsItsCauseOnce();
    caseExceptionLeavesNoImageAndLogsOnce();
    caseErrorIsLoggedAgainAfterTheFileDraws();
    caseFallbacksNameTheirCause();
    caseMalformedXmlIsRefusedWithItsPlace();
    caseRootEffectsWarnOnce();
    caseDocumentSizeOutOfRangeIsRefused();
#else
    std::cout << "SVG support is not built (OMNIUI_ENABLE_SVG=OFF)" << std::endl;
#endif
    caseSvgOffDrawsNothingAndLogsCause();
    caseWithoutRasterizerDrawsNothingSilently();

    std::filesystem::remove_all(g_dir);
    return g_failedCases == 0 ? 0 : 1;
}
