/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Published-state contract for RasterImageProvider across source-URL changes.
 *
 * A fake IRasterImageLoader stands in for a backend loader so every branch is
 * reachable and deterministic, with no GPU, window or filesystem involved. In
 * particular the asynchronous terminal-failure branch (beginLoad reports
 * eLoading, a later poll reports eFailed) is unreachable through the standalone
 * loader, which is fully synchronous.
 *
 * The contract under test, for a provider whose source URL changes:
 *
 *   - a load that fails terminally must leave the provider reporting no image:
 *     isReferenceValid() false and getSize() 0x0, whether the failure is
 *     reported immediately by beginLoad or later by poll;
 *   - the requested (failed) URL stays readable through getSourceUrl();
 *   - a handle that has been handed back to the loader must never remain
 *     reachable through getImGuiReference();
 *   - failing from cold, replacing one valid source with another, recovering
 *     after a failure, and repeating transitions must all keep working;
 *   - a provider that outlives the registry loader (a Python global released
 *     after backend shutdown) must keep that loader alive until it is destroyed.
 *
 * Every case runs to completion and reports independently, so a regression in
 * one branch cannot mask the state of the others.
 */

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include "platform/IRasterImageLoader.h"
#include "ImageProvider/ImageProviderCache.h"
#include <omni/ui/ImageProvider/IByteImageGpu.h>

#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

using namespace omni::ui;

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
// Fake loader
// ---------------------------------------------------------------------------

/// How the fake loader should respond for a given URL.
enum class Behavior
{
    eSucceedImmediately, ///< beginLoad reports eCached with a handle
    eFailImmediately,    ///< beginLoad reports eFailed  (synchronous terminal failure)
    eLoadThenSucceed,    ///< beginLoad reports eLoading, poll then reports eReady
    eLoadThenFail,       ///< beginLoad reports eLoading, poll then reports eFailed
    eKeepLoading,        ///< Both beginLoad and poll remain pending
};

struct Response
{
    Behavior behavior = Behavior::eSucceedImmediately;
    UInt2 size = { 0, 0 };
};

class FakeRasterImageLoader : public IRasterImageLoader
{
public:
    std::map<std::string, Response> responses;

    /// Handles handed out to the provider, and those the loader has taken back.
    std::set<void*> liveHandles;
    std::set<void*> releasedHandles;
    std::vector<std::string> gpuReleases;
    std::vector<std::string> invalidations;

    void configure(const std::string& url, Behavior behavior, UInt2 size)
    {
        responses[url] = Response{ behavior, size };
    }

    bool isReleased(void* handle) const
    {
        return handle != nullptr && releasedHandles.count(handle) != 0;
    }

    LoadResult beginLoad(void* instanceKey, const std::string& url) override
    {
        LoadResult out;
        out.cacheKey = url;

        auto it = responses.find(url);
        const Response response = (it == responses.end()) ? Response{ Behavior::eFailImmediately, { 0, 0 } } : it->second;
        m_instanceUrl[instanceKey] = url;

        switch (response.behavior)
        {
            case Behavior::eSucceedImmediately:
                out.status = LoadResult::eCached;
                out.imGuiReference = _mintHandle(url);
                out.imageSize = response.size;
                out.imageFormat = PixelFormat::eRGBA8_UNORM;
                return out;
            case Behavior::eLoadThenSucceed:
            case Behavior::eLoadThenFail:
            case Behavior::eKeepLoading:
                out.status = LoadResult::eLoading;
                return out;
            case Behavior::eFailImmediately:
            default:
                out.status = LoadResult::eFailed;
                return out;
        }
    }

    LoadResult poll(void* instanceKey, const ImageProviderTextureOptions&, size_t) override
    {
        LoadResult out;
        auto keyIt = m_instanceUrl.find(instanceKey);
        if (keyIt == m_instanceUrl.end())
        {
            out.status = LoadResult::eFailed;
            return out;
        }

        const std::string url = keyIt->second;
        out.cacheKey = url;

        auto it = responses.find(url);
        const Response response = (it == responses.end()) ? Response{ Behavior::eFailImmediately, { 0, 0 } } : it->second;

        if (response.behavior == Behavior::eKeepLoading)
        {
            out.status = LoadResult::eLoading;
            return out;
        }

        if (response.behavior == Behavior::eLoadThenSucceed)
        {
            out.status = LoadResult::eReady;
            out.imGuiReference = _mintHandle(url);
            out.imageSize = response.size;
            out.imageFormat = PixelFormat::eRGBA8_UNORM;
            return out;
        }

        out.status = LoadResult::eFailed;
        return out;
    }

    void waitForCompletion(void*, int32_t) override
    {
    }

    /// Taking a load back invalidates every handle minted for that instance —
    /// this is what a real backend does when it destroys the GPU state.
    void releaseLoad(void* instanceKey) override
    {
        auto it = m_instanceHandles.find(instanceKey);
        if (it == m_instanceHandles.end())
        {
            return;
        }
        for (void* handle : it->second)
        {
            liveHandles.erase(handle);
            releasedHandles.insert(handle);
        }
        m_instanceHandles.erase(it);
    }

    void releaseGpuResource(const std::string& cacheKey) override
    {
        gpuReleases.push_back(cacheKey);
        auto it = m_urlHandles.find(cacheKey);
        if (it == m_urlHandles.end())
        {
            return;
        }
        for (void* handle : it->second)
        {
            liveHandles.erase(handle);
            releasedHandles.insert(handle);
        }
        m_urlHandles.erase(it);
    }

    void invalidateCacheEntry(const std::string& cacheKey) override
    {
        invalidations.push_back(cacheKey);
    }

private:
    void* _mintHandle(const std::string& url)
    {
        // Opaque, never-dereferenced, unique per mint.
        void* handle = reinterpret_cast<void*>(static_cast<uintptr_t>(++m_handleCounter) << 8);
        liveHandles.insert(handle);
        m_urlHandles[url].push_back(handle);
        for (auto& kv : m_instanceUrl)
        {
            if (kv.second == url)
            {
                m_instanceHandles[kv.first].push_back(handle);
            }
        }
        return handle;
    }

    uint64_t m_handleCounter = 0;
    std::map<void*, std::string> m_instanceUrl;
    std::map<void*, std::vector<void*>> m_instanceHandles;
    std::map<std::string, std::vector<void*>> m_urlHandles;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

constexpr float kWidgetW = 64.0f;
constexpr float kWidgetH = 64.0f;

/// Drive the provider's load state machine the way a drawing frame would.
/// Bounded so an unexpected pending state fails the case instead of hanging.
void advance(RasterImageProvider& provider, int frames = 8)
{
    for (int i = 0; i < frames; ++i)
    {
        provider.prepareDraw(kWidgetW, kWidgetH);
    }
}

void expectNoImage(RasterImageProvider& provider, const std::string& where)
{
    check(!provider.isReferenceValid(), where + ": isReferenceValid() must be false after a terminal failure");
    check(provider.getSize().x == 0 && provider.getSize().y == 0,
          where + ": size must be 0x0 after a terminal failure");
}

void expectImage(RasterImageProvider& provider, UInt2 expected, const std::string& where)
{
    check(provider.isReferenceValid(), where + ": isReferenceValid() must be true after a successful load");
    check(provider.getSize().x == expected.x && provider.getSize().y == expected.y,
          where + ": size must match the loaded image");
}

void expectNoReleasedHandlePublished(RasterImageProvider& provider,
                                     const FakeRasterImageLoader& loader,
                                     const std::string& where)
{
    check(!loader.isReleased(provider.getImGuiReference()),
          where + ": a handle already returned to the loader must not stay publicly reachable");
}

} // namespace

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

/// Constructing straight onto a failing source must report no image.
/// This already holds today and must keep holding.
static void caseColdFailure(FakeRasterImageLoader& loader)
{
    beginCase("cold_failure_reports_no_image");
    loader.configure("missing", Behavior::eFailImmediately, { 0, 0 });

    RasterImageProvider provider("missing");
    advance(provider);

    expectNoImage(provider, "cold failure");
    check(provider.getSourceUrl() == "missing", "cold failure: getSourceUrl() must report the requested URL");
    endCase();
}

/// Replacing one valid source with another. Already holds today.
static void caseValidToValid(FakeRasterImageLoader& loader)
{
    beginCase("valid_to_valid_replaces_image");
    loader.configure("a", Behavior::eSucceedImmediately, { 128, 128 });
    loader.configure("b", Behavior::eSucceedImmediately, { 64, 32 });

    RasterImageProvider provider("a");
    advance(provider);
    expectImage(provider, { 128, 128 }, "valid->valid first load");

    provider.setSourceUrl("b");
    advance(provider);

    expectImage(provider, { 64, 32 }, "valid->valid replacement");
    check(provider.getSourceUrl() == "b", "valid->valid: getSourceUrl() must report the new URL");
    expectNoReleasedHandlePublished(provider, loader, "valid->valid replacement");
    endCase();
}

/// THE TICKET, synchronous branch: a good load followed by a source change that
/// beginLoad rejects outright. Expected to fail until the defect is corrected.
static void caseTerminalFailureImmediate(FakeRasterImageLoader& loader)
{
    beginCase("terminal_failure_immediate_clears_published_state");
    loader.configure("good", Behavior::eSucceedImmediately, { 128, 128 });
    loader.configure("bad", Behavior::eFailImmediately, { 0, 0 });

    RasterImageProvider provider("good");
    advance(provider);
    expectImage(provider, { 128, 128 }, "immediate-failure precondition");

    provider.setSourceUrl("bad");
    advance(provider);

    expectNoImage(provider, "immediate terminal failure");
    check(provider.getSourceUrl() == "bad",
          "immediate terminal failure: getSourceUrl() must still report the requested URL");
    expectNoReleasedHandlePublished(provider, loader, "immediate terminal failure");
    endCase();
}

/// THE TICKET, asynchronous branch: beginLoad accepts the change and reports
/// progress, then poll reports terminal failure. Unreachable via the standalone
/// loader. Expected to fail until the defect is corrected.
static void caseTerminalFailureAsynchronous(FakeRasterImageLoader& loader)
{
    beginCase("terminal_failure_asynchronous_clears_published_state");
    loader.configure("good", Behavior::eSucceedImmediately, { 128, 128 });
    loader.configure("bad-async", Behavior::eLoadThenFail, { 0, 0 });

    RasterImageProvider provider("good");
    advance(provider);
    expectImage(provider, { 128, 128 }, "asynchronous-failure precondition");

    provider.setSourceUrl("bad-async");
    advance(provider);

    expectNoImage(provider, "asynchronous terminal failure");
    check(provider.getSourceUrl() == "bad-async",
          "asynchronous terminal failure: getSourceUrl() must still report the requested URL");
    expectNoReleasedHandlePublished(provider, loader, "asynchronous terminal failure");
    endCase();
}

/// Recovery after a terminal failure, including via the asynchronous path.
/// The recovery half already holds today.
static void caseRecoveryAfterFailure(FakeRasterImageLoader& loader)
{
    beginCase("recovery_after_terminal_failure");
    loader.configure("good", Behavior::eSucceedImmediately, { 128, 128 });
    loader.configure("bad", Behavior::eFailImmediately, { 0, 0 });
    loader.configure("later", Behavior::eLoadThenSucceed, { 32, 16 });

    RasterImageProvider provider("good");
    advance(provider);
    provider.setSourceUrl("bad");
    advance(provider);

    provider.setSourceUrl("later");
    advance(provider);

    expectImage(provider, { 32, 16 }, "recovery");
    check(provider.getSourceUrl() == "later", "recovery: getSourceUrl() must report the recovered URL");
    expectNoReleasedHandlePublished(provider, loader, "recovery");
    endCase();
}

/// Repeated transitions: every terminal failure must converge on the same
/// published state, and recovery must still work afterwards.
static void caseRepeatedTransitions(FakeRasterImageLoader& loader)
{
    beginCase("repeated_transitions_converge");
    loader.configure("good", Behavior::eSucceedImmediately, { 128, 128 });
    loader.configure("bad1", Behavior::eFailImmediately, { 0, 0 });
    loader.configure("bad2", Behavior::eLoadThenFail, { 0, 0 });
    loader.configure("good2", Behavior::eSucceedImmediately, { 8, 8 });

    RasterImageProvider provider("good");
    advance(provider);

    provider.setSourceUrl("bad1");
    advance(provider);
    expectNoImage(provider, "repeated transitions, first failure");
    expectNoReleasedHandlePublished(provider, loader, "repeated transitions, first failure");

    provider.setSourceUrl("bad2");
    advance(provider);
    expectNoImage(provider, "repeated transitions, second failure");
    expectNoReleasedHandlePublished(provider, loader, "repeated transitions, second failure");

    provider.setSourceUrl("good2");
    advance(provider);
    expectImage(provider, { 8, 8 }, "repeated transitions, final recovery");
    check(provider.getSourceUrl() == "good2", "repeated transitions: getSourceUrl() must report the final URL");
    endCase();
}

static void caseUnownedKeysAreNeverReleased(FakeRasterImageLoader& loader)
{
    beginCase("pending_and_failed_loads_do_not_release_unowned_keys");
    // Deliberately return keys even on pending/failed results, like older
    // backends. The provider must distinguish identity from ownership.
    for (auto behavior : { Behavior::eKeepLoading, Behavior::eFailImmediately, Behavior::eLoadThenFail })
    {
        loader.configure("unowned", behavior, { 0, 0 });
        {
            RasterImageProvider provider("unowned");
            advance(provider);
        }
        check(loader.gpuReleases.empty(), "destroying an unsuccessful load released a GPU reference");
    }
    endCase();
}

static void caseCompletedKeysAreReleasedOnce(FakeRasterImageLoader& loader)
{
    beginCase("completed_async_loads_release_once_on_replacement_and_destruction");
    loader.configure("first", Behavior::eLoadThenSucceed, { 32, 32 });
    loader.configure("second", Behavior::eLoadThenSucceed, { 64, 64 });
    {
        RasterImageProvider provider("first");
        advance(provider);
        expectImage(provider, { 32, 32 }, "first async load");
        check(loader.gpuReleases.empty(), "a live provider must retain its reference");
        provider.setSourceUrl("second");
        advance(provider);
        expectImage(provider, { 64, 64 }, "replacement async load");
        check(loader.gpuReleases == std::vector<std::string>{ "first" }, "replacement releases the first key once");
    }
    check(loader.gpuReleases == std::vector<std::string>{ "first", "second" }, "destruction releases the last key once");
    endCase();
}

/// Only setting the same source URL again means "the file may have been
/// replaced, read it again". Moving to another URL and back, or a provider
/// being destroyed, must leave the shared entry alone, or a peer still drawing
/// the file makes the next load of that same file decode and upload a second
/// copy of it.
static void caseOnlyReloadInvalidatesTheSharedEntry(FakeRasterImageLoader& loader)
{
    beginCase("only_a_reload_invalidates_the_shared_entry");
    loader.configure("shared", Behavior::eSucceedImmediately, { 32, 32 });
    loader.configure("other", Behavior::eSucceedImmediately, { 8, 8 });
    {
        RasterImageProvider provider("shared");
        advance(provider);
        expectImage(provider, { 32, 32 }, "shared load");
        check(loader.invalidations.empty(), "a first load must not invalidate anything");

        // Reloading the same path: the file may have been replaced.
        provider.setSourceUrl("shared");
        advance(provider);
        check(loader.invalidations == std::vector<std::string>{ "shared" },
              "reloading a source URL must stop the previous entry being shared");

        // Browsing to another file and back says nothing about either file.
        provider.setSourceUrl("other");
        advance(provider);
        expectImage(provider, { 8, 8 }, "browse to another URL");
        provider.setSourceUrl("shared");
        advance(provider);
        expectImage(provider, { 32, 32 }, "browse back");
        check(loader.invalidations == std::vector<std::string>{ "shared" },
              "browsing between URLs must keep the entries left behind shared");
    }
    check(loader.invalidations == std::vector<std::string>{ "shared" },
          "a destroyed provider must not invalidate the entry its peers still share");
    endCase();
}

static void caseProtectedLoadingOwnership(FakeRasterImageLoader& loader)
{
    beginCase("protected_loading_entrypoints_preserve_cache_ownership");
    struct DerivedProvider : RasterImageProvider
    {
        DerivedProvider() : RasterImageProvider("") {}
        using RasterImageProvider::_loadAsset;
        using RasterImageProvider::_waitAsset;
        using RasterImageProvider::_pollAsset;
        using RasterImageProvider::_releaseAsset;
    };
    loader.configure("pending", Behavior::eKeepLoading, { 0, 0 });
    loader.configure("ready", Behavior::eLoadThenSucceed, { 16, 16 });
    {
        DerivedProvider provider;
        provider._loadAsset("pending");
        provider._pollAsset();
        provider._releaseAsset();
        check(loader.gpuReleases.empty(), "protected cancellation releases no GPU reference");
        provider._loadAsset("ready");
        provider._waitAsset();
        provider._pollAsset();
        provider._pollAsset();
        expectImage(provider, { 16, 16 }, "protected ready load");
        provider._releaseAsset();
        provider._releaseAsset();
    }
    check(loader.gpuReleases == std::vector<std::string>{ "ready" }, "protected completion releases exactly once");
    endCase();
}

static void caseColdCompletionsShareOneAllocation()
{
    beginCase("cold_completions_acquire_one_allocation_and_release_last_owner");
    struct CountingGpu : IByteImageGpu
    {
        int created = 0, uploaded = 0, destroyed = 0;
        Handle createState() override { ++created; return new int(0); }
        void destroyState(Handle state) override { ++destroyed; delete static_cast<int*>(state); }
        void releaseImage(Handle) override {}
        UpdateResult updateImage(Handle state, const uint8_t* const*, size_t*, size_t, UInt2,
                                 PixelFormat, bool, uint32_t, uint32_t, uint32_t) override
        {
            ++uploaded;
            return { state, nullptr };
        }
    };
    auto gpu = std::make_shared<CountingGpu>();
    PlatformRegistry::instance().setByteImageGpu(gpu);
    GpuResourcesCache cache;
    // Both callers miss before either finishes its decode. Completion must
    // acquire again before initializing, rather than overwriting a live entry.
    check(cache.acquireGpuResource("shared") == nullptr, "first cold lookup");
    check(cache.acquireGpuResource("shared") == nullptr, "second cold lookup");
    const uint8_t pixel[] = { 0, 255, 0, 255 };
    auto complete = [&]() {
        auto* value = cache.acquireGpuResource("shared");
        return value ? value : cache.initGpuResource("shared", pixel, 4, { 1, 1 },
                                                     PixelFormat::eRGBA8_UNORM, {}, false);
    };
    auto* first = complete();
    auto* second = complete();
    check(first && first == second, "compatible completions share their provider");
    check(cache.gpuResources.at("shared").counter == 2, "each completion owns a reference");
    check(gpu->created == 1 && gpu->uploaded == 1, "a live resource must not be reallocated or uploaded again");
    check(cache.initGpuResource("shared", pixel, 4, { 1, 1 }, PixelFormat::eRGBA8_UNORM, {}, false) == nullptr,
          "non-overwriting init rejects a live entry");
    check(cache.gpuResources.at("shared").counter == 2 && gpu->uploaded == 1, "rejected init changes no ownership");
    cache.releaseGpuResource("shared");
    check(gpu->destroyed == 0 && cache.gpuResources.at("shared").counter == 1, "the survivor retains its texture");
    check(second->isReferenceValid(), "the surviving provider still publishes its texture");
    cache.releaseGpuResource("shared");
    check(gpu->destroyed == 1 && cache.gpuResources.empty(), "last release destroys exactly one allocation");
    cache.gpuResources["empty"] = {};
    check(cache.acquireGpuResource("empty") == nullptr && cache.gpuResources.at("empty").counter == 0,
          "a null provider cannot acquire a reference");
    cache.gpuResources.clear();
    PlatformRegistry::instance().setByteImageGpu(nullptr);
    endCase();
}

/// Backend shutdown resets the registry and frees the backend's own reference
/// to the loader, while Python can still hold a provider. The provider must
/// keep the loader alive and give its load back when it is destroyed.
static void caseProviderOutlivesRegistryLoader()
{
    beginCase("provider_outlives_registry_loader");
    auto loader = std::make_shared<FakeRasterImageLoader>();
    loader->configure("img", Behavior::eSucceedImmediately, { 16, 16 });
    PlatformRegistry::instance().setRasterImageLoader(loader);
    std::weak_ptr<FakeRasterImageLoader> weakLoader = loader;

    auto* provider = new RasterImageProvider("img");
    advance(*provider);
    expectImage(*provider, { 16, 16 }, "before shutdown");
    void* handle = provider->getImGuiReference();

    // Backend shutdown: the registry and the backend release the loader.
    PlatformRegistry::instance().setRasterImageLoader(nullptr);
    loader.reset();

    auto kept = weakLoader.lock();
    check(kept != nullptr, "the provider must keep the loader alive after the registry releases it");
    if (!kept)
    {
        // Do not delete: its destructor would call the freed loader.
        endCase();
        return;
    }

    delete provider;
    check(kept->isReleased(handle), "the destroyed provider must give its load back to the loader");
    kept.reset();
    check(weakLoader.expired(), "the loader must be freed with its last provider");
    endCase();
}

int main()
{
    auto loader = std::make_shared<FakeRasterImageLoader>();
    PlatformRegistry::instance().setRasterImageLoader(loader);

    // Each case gets a clean loader so handle bookkeeping cannot leak between them.
    auto fresh = [&loader]() -> FakeRasterImageLoader& {
        loader = std::make_shared<FakeRasterImageLoader>();
        PlatformRegistry::instance().setRasterImageLoader(loader);
        return *loader;
    };

    caseColdFailure(fresh());
    caseValidToValid(fresh());
    caseTerminalFailureImmediate(fresh());
    caseTerminalFailureAsynchronous(fresh());
    caseRecoveryAfterFailure(fresh());
    caseRepeatedTransitions(fresh());
    caseUnownedKeysAreNeverReleased(fresh());
    caseCompletedKeysAreReleasedOnce(fresh());
    caseOnlyReloadInvalidatesTheSharedEntry(fresh());
    caseProtectedLoadingOwnership(fresh());
    caseColdCompletionsShareOneAllocation();
    caseProviderOutlivesRegistryLoader();

    std::cout << "\n" << (g_totalCases - g_failedCases) << "/" << g_totalCases << " cases passed" << std::endl;

    PlatformRegistry::instance().setRasterImageLoader(nullptr);
    return g_failedCases == 0 ? 0 : 1;
}
