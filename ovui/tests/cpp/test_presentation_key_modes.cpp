/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Presentation-key mode of ImageProvider.
 *
 * A fake IImageProviderRenderer and a fake IByteImageGpu replace the real
 * back ends, so every outcome is reachable and deterministic. No GPU or window
 * is needed. The fake renderer keeps the global present setting on, as another
 * presentation user in the same process does. One fake also keeps its own list
 * of keys that have a drawable; the other one has none, like the shipped renderer.
 *
 * What is checked:
 *   - a failed key entry stores no key and keeps the earlier mode;
 *   - a good entry, and a same-resource entry, store the key;
 *   - there is a supported way to leave key mode, and it does not touch the
 *     texture reference or the managed resource;
 *   - a good CPU or GPU byte upload leaves key mode, a failed one does not;
 *   - a key that the feeder retires is not used again, so a live feed of
 *     another provider cannot keep a dead key in use;
 *   - by default (no lease) a feed that is bound once, paused or slow keeps its key when the
 *     renderer reports no key state; a lease is opt-in. This case runs with the initial lease;
 *   - the draw guard removes every key command that the renderer does not map
 *     (also a key that was never notified, and a key retired after the widget
 *     asked for it), and it checks a reference that a client kept in later frames
 *     while a provider holds the key. The renderer as shipped has no key table, so it keeps none;
 *   - when the last provider of a key lets it go, the feed is done: its key is still checked in the
 *     frame of the exit and one more, then its records are freed. So an app that opens and closes
 *     many feeds does not make the guard slower or bigger. This holds also when more feeds than the
 *     record limit end in one frame, after their keys were drawn; a host that draws frames without
 *     the guard keeps its records within the limit;
 *   - each fallback to the texture, and each removal of draw commands, writes one log
 *     line with the key and the reason, not one for each frame. Presentation that is off is not a
 *     fallback and writes no line.
 *
 * Each case runs to the end and reports alone. The test uses only calls that
 * exist before and after the change, or a detection idiom, so it also builds
 * on the old code and shows the failures there.
 */

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/platform/IUiLog.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include "platform/IImageProviderRenderer.h"
#include <omni/ui/ImageProvider/IByteImageGpu.h>

#include <imgui.h>

#if __has_include(<omni/ui/ImageProvider/PresentationKeyGuard.h>)
#    include <omni/ui/ImageProvider/PresentationKeyGuard.h>
#    if __has_include("ImageProvider/PresentationKeyState.h")
#        include "ImageProvider/PresentationKeyState.h"
#        define HAS_STATE_RESET 1
#    endif
#    define HAS_DRAW_GUARD 1
#else
#    define HAS_DRAW_GUARD 0
#endif

#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace rtx { namespace resourcemanager { class RpResource; } }

using namespace omni::ui;
using RpResource = rtx::resourcemanager::RpResource;

namespace
{

std::vector<std::string> g_caseFailures;
std::string g_caseName;
int g_failedCases = 0;
int g_totalCases = 0;

void check(bool condition, const std::string& what)
{
    if (!condition)
        g_caseFailures.push_back(what);
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
    for (const auto& f : g_caseFailures)
        std::cout << "     - " << f << std::endl;
}

// Detection idiom: the exit call does not exist in the old code.
template <class T>
auto callClear(T& p, int) -> decltype(p.clearPresentationKey(), true)
{
    p.clearPresentationKey();
    return true;
}
template <class T>
bool callClear(T&, long)
{
    return false;
}

constexpr uint64_t kKeyA = 0xFFFFFFF1ull;
constexpr uint64_t kKeyB = 0xFFFFFFF2ull;
constexpr uint64_t kKeyC = 0xFFFFFFFDull;

struct FakeRenderer : IImageProviderRenderer
{
    bool globalEnabled = true; // another presentation user keeps it on
    std::set<uint64_t> mapped; // keys that have a drawable
    int ensureCalls = 0;
    bool failEnsure = false;
    std::map<void*, int> handles;

    void* acquireRenderer() override { return this; }
    bool isPresentThreadEnabled(void*) override { return globalEnabled; }

    void* handleFor(void* rsrc)
    {
        auto it = handles.find(rsrc);
        if (it == handles.end())
            it = handles.emplace(rsrc, 0).first;
        return &it->second;
    }

    EnsureResourceResult ensureResourceWithTextureInfo(void*, void* rsrc, uint32_t) override
    {
        ++ensureCalls;
        EnsureResourceResult r;
        if (failEnsure)
            return r;
        r.resource = rsrc;
        r.textureHandlePtr = handleFor(rsrc);
        r.width = 16;
        r.height = 16;
        r.format = PixelFormat::eRGBA8_UNORM;
        return r;
    }
    void* ensureResourceSimple(void*, void* rsrc, uint32_t) override { return rsrc; }
    void releaseResource(void*, void*) override {}
};

// A renderer that maps keys itself before the back end reads the draw data.
// Not marked override: the old interface has no such function.
struct MappingRenderer : FakeRenderer
{
#if HAS_DRAW_GUARD
    size_t queries = 0; // how many keys the draw guard asked about: the key records that it walks
    PresentationKeyState presentationKeyState(void*, uint64_t key)
    {
        ++queries;
        return mapped.count(key) ? PresentationKeyState::eMapped : PresentationKeyState::eUnmapped;
    }
#endif
};

struct FakeGpu : IByteImageGpu
{
    bool failUpload = false;
    bool gpuSupported = true;
    std::deque<int> slots; // one stable handle for each upload: a deque keeps its elements in place
    Handle createState() override { return new int(0); }
    void destroyState(Handle h) override { delete static_cast<int*>(h); }
    void releaseImage(Handle) override {}
    UpdateResult updateImage(Handle, const uint8_t* const*, size_t*, size_t, UInt2, PixelFormat, bool fromGpu,
                             uint32_t, uint32_t, uint32_t) override
    {
        if (failUpload || (fromGpu && !gpuSupported))
            return {};
        slots.emplace_back(0);
        return { &slots.back(), nullptr };
    }
    bool supportsFromGpu() const override { return gpuSupported; }
};

#if HAS_DRAW_GUARD
uint64_t g_nowNs = 1000000000ull;
uint64_t fakeNow() { return g_nowNs; }
void advanceMs(uint64_t ms) { g_nowNs += ms * 1000000ull; }
#else
void advanceMs(uint64_t) {}
#endif

struct Env
{
    std::shared_ptr<FakeRenderer> renderer;
    std::shared_ptr<FakeGpu> gpu = std::make_shared<FakeGpu>();
    alignas(8) char resA[8] = {};
    alignas(8) char resB[8] = {};
    alignas(8) char resC[8] = {};
#if HAS_DRAW_GUARD
    uint32_t leaseMs = 0; // the lease that this Env found; a case that opts in to a lease changes it
#endif
    // resolving=false is the renderer as shipped: it has no key table, the default is used.
    explicit Env(bool resolving = true)
    {
        if (resolving)
            renderer = std::make_shared<MappingRenderer>();
        else
            renderer = std::make_shared<FakeRenderer>();
        PlatformRegistry::instance().setImageProviderRenderer(renderer);
        PlatformRegistry::instance().setByteImageGpu(gpu);
#ifdef HAS_STATE_RESET
        resetPresentationKeyGuardForTest(); // keys that earlier cases issued must not leak into this one
#endif
#if HAS_DRAW_GUARD
        // The Env does not write the lease: the default case must see the initial lease of the library.
        leaseMs = getPresentationKeyLeaseMs();
        setPresentationKeyClock(&fakeNow);
#endif
    }
    ~Env()
    {
#if HAS_DRAW_GUARD
        setPresentationKeyClock(nullptr);
        setPresentationKeyLeaseMs(leaseMs);
#endif
        PlatformRegistry::instance().setImageProviderRenderer(nullptr);
        PlatformRegistry::instance().setByteImageGpu(nullptr);
    }
    RpResource& rsrc(char* storage) { return *reinterpret_cast<RpResource*>(storage); }
};

// The feed of the key ends or sends an invalid frame: the feeder retires the key.
bool retireKey(uint64_t key)
{
#if HAS_DRAW_GUARD
    ImageProvider::retirePresentationKey(key);
    return true;
#else
    (void)key;
    return false;
#endif
}

const uint8_t kPixel[4] = { 0, 255, 0, 255 };

void uploadCpu(ByteImageProvider& p)
{
    p.setBytesData(kPixel, { 1, 1 }, 4, PixelFormat::eRGBA8_UNORM);
}

void uploadGpu(ByteImageProvider& p)
{
    p.setBytesDataFromGPU(kPixel, { 1, 1 }, 4, PixelFormat::eRGBA8_UNORM);
}

// ---------------------------------------------------------------------------

void caseFailedEntryStoresNoKey()
{
    beginCase("failed_entry_stores_no_key");
    Env env;
    ByteImageProvider p;
    uploadCpu(p);
    void* texture = p.getImGuiReference();
    check(texture != nullptr, "setup: the upload gives a texture reference");

    env.renderer->failEnsure = true;
    env.renderer->mapped.insert(kKeyA);
    check(!p.setImageData(env.rsrc(env.resA), kKeyA), "a failed setup reports false");
    check(p.getImGuiReference() == texture, "a failed entry must not make the key the reference");

    // A failed entry on a provider already in key mode keeps the old key.
    env.renderer->failEnsure = false;
    env.renderer->mapped.insert(kKeyB);
    check(p.setImageData(env.rsrc(env.resB), kKeyB), "a good entry reports true");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "setup: key B is in use");
    env.renderer->failEnsure = true;
    check(!p.setImageData(env.rsrc(env.resC), kKeyC), "a second failed setup reports false");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "a failed entry keeps the earlier key");
    endCase();
}

void caseGoodEntryStoresKey()
{
    beginCase("good_entry_stores_key");
    Env env;
    ByteImageProvider p;
    env.renderer->mapped.insert(kKeyA);
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "a good entry reports true");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "a key with a drawable is the reference");
    check(p.getManagedResource() != nullptr, "the resource is retained");
    // Key 0 means texture mode.
    check(p.setImageData(env.rsrc(env.resB), 0), "entry with key 0 reports true");
    check(p.getImGuiReference() == env.renderer->handleFor(&env.resB), "key 0 gives the texture reference");
    endCase();
}

void caseSameResourceEntryRelatches()
{
    beginCase("same_resource_entry_relatches_key");
    Env env;
    ByteImageProvider p;
    env.renderer->mapped = { kKeyA, kKeyB };
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "first entry");
    const int ensured = env.renderer->ensureCalls;
    check(p.setImageData(env.rsrc(env.resA), kKeyB), "same resource, new key reports true");
    check(env.renderer->ensureCalls == ensured, "the same resource is not set up again");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "the new key is stored on the same-resource path");
    callClear(p, 0);
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "same resource after an exit reports true");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "the key is stored again after an exit");
    endCase();
}

void caseExplicitExit()
{
    beginCase("explicit_exit_without_destroying_provider");
    Env env;
    ByteImageProvider p;
    env.renderer->mapped = { kKeyA };
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "setup");
    void* texture = env.renderer->handleFor(&env.resA);
    auto* managed = p.getManagedResource();
    check(callClear(p, 0), "there is a supported call to leave key mode");
    check(p.getImGuiReference() == texture, "after the exit the texture reference is used, while the key is mapped");
    check(p.getManagedResource() == managed, "the exit does not change the managed resource");
    check(p.isReferenceValid(), "the exit does not change the texture reference");
    callClear(p, 0); // twice is safe
    check(p.getImGuiReference() == texture, "a second exit changes nothing");
    ByteImageProvider plain;
    uploadCpu(plain);
    void* ref = plain.getImGuiReference();
    callClear(plain, 0);
    check(plain.getImGuiReference() == ref, "an exit on a provider that is not in key mode changes nothing");
    endCase();
}

void caseByteUploadTransitions(bool fromGpu)
{
    beginCase(fromGpu ? "gpu_byte_upload_success_and_failure" : "cpu_byte_upload_success_and_failure");
    Env env;
    ByteImageProvider p;
    auto upload = [&](ByteImageProvider& q) { fromGpu ? uploadGpu(q) : uploadCpu(q); };
    env.renderer->mapped = { kKeyA };
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "setup");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "setup: key mode");

    // Failure keeps the earlier mode.
    env.gpu->failUpload = true;
    upload(p);
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "a failed upload keeps key mode");
    env.gpu->failUpload = false;

    // Success leaves key mode, although the key still has a drawable.
    upload(p);
    void* shown = p.getImGuiReference();
    check(shown != reinterpret_cast<void*>(kKeyA), "a good upload must leave key mode");
    check(shown == &env.gpu->slots.back(), "the uploaded texture is shown");

    // A failed upload on a texture-mode provider keeps the texture.
    env.gpu->failUpload = true;
    upload(p);
    check(p.getImGuiReference() == shown, "a failed upload keeps the texture mode and its reference");
    endCase();
}

void caseGpuUploadUnsupported()
{
    beginCase("gpu_upload_unsupported_keeps_key_mode");
    Env env;
    ByteImageProvider p;
    env.gpu->gpuSupported = false;
    env.renderer->mapped = { kKeyA };
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "setup");
    uploadGpu(p);
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "an unsupported GPU upload is a failure and keeps key mode");
    endCase();
}

void caseIndependentFeeds()
{
    beginCase("independent_feeds_dead_key_is_not_kept_by_live_feed");
    Env env;
    ByteImageProvider a, b;
    env.renderer->mapped = { kKeyA, kKeyB };
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "feed A entry");
    check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B entry");
    check(env.renderer->globalEnabled, "the global present setting is on");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "A shows its key while live");
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "B shows its key while live");

    // Feed A dies (invalid subframe, or teardown). Feed B stays live, so the global setting stays on.
    env.renderer->mapped.erase(kKeyA); // the renderer reports no drawable for A; no other call is made
    check(a.getImGuiReference() != reinterpret_cast<void*>(kKeyA), "the dead key of A is not used while B is live");
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "B keeps its live key");

    // The fallback upload of A is visible and does not change B.
    uploadCpu(a);
    check(a.getImGuiReference() == &env.gpu->slots.back(), "the fallback upload of A is shown");
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "B is not changed by the fallback of A");

    // A key that comes back (a new feed with the same key) works again.
    env.renderer->mapped.insert(kKeyA);
    check(a.setImageData(env.rsrc(env.resC), kKeyA), "A enters key mode again");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "A shows the key again");
    endCase();
}

// The reported case with the renderer as shipped: it keeps no per-key state, the global present
// setting stays on, and nobody calls a retire function. Feed A stops; feed B keeps delivering frames.
void caseStoppedFeedLosesKeyWhileOtherFeedIsLive()
{
    beginCase("opt_in_lease_ends_the_key_of_a_stopped_feed_while_another_feed_is_live");
    Env env(false);
#if HAS_DRAW_GUARD
    setPresentationKeyLeaseMs(500); // opt in: the default keeps every key
#endif
    ByteImageProvider a, b;
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "feed A entry");
    check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B entry");
    for (int i = 0; i < 4; ++i)
    {
        advanceMs(100);
        check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B delivers a frame"); // A is silent
    }
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "the live feed B keeps its key");
    advanceMs(300); // A is silent for 700 ms; B for 300 ms
    check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B delivers a frame");
    check(env.renderer->globalEnabled, "the global present setting is still on");
    check(a.getImGuiReference() == env.renderer->handleFor(&env.resA), "the stopped feed A uses its last texture, not its dead key");
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "B is not changed");
    // A fallback upload is visible, and a new frame of A takes the key again.
    uploadCpu(a);
    check(a.getImGuiReference() == &env.gpu->slots.back(), "the fallback upload of A is shown");
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "A delivers again");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "a new frame arms the key again");
    endCase();
}

// A valid feed that the renderer reports as mapped keeps its key, however slowly it delivers
// frames (bound once, or a slow feed), also while another feed updates all the time.
void caseMappedFeedIsNotExpiredByLease()
{
    beginCase("mapped_feed_bound_once_keeps_its_key_after_the_lease");
    Env env; // the renderer reports per-key state
#if HAS_DRAW_GUARD
    setPresentationKeyLeaseMs(500);
#endif
    ByteImageProvider a, b;
    env.renderer->mapped = { kKeyA, kKeyB };
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "feed A bound once");
    check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B entry");
    for (int i = 0; i < 7; ++i)
    {
        advanceMs(100);
        check(b.setImageData(env.rsrc(env.resB), kKeyB), "feed B delivers a frame");
    }
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "A is mapped, so its key stays after 700 ms without a call");
    check(b.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "B keeps its key");
    env.renderer->mapped.erase(kKeyA); // when the renderer reports A unmapped, A leaves key mode
    check(a.getImGuiReference() == env.renderer->handleFor(&env.resA), "A uses its texture once it is unmapped");
    endCase();
}

// The same two feed cases with the real clock and the real 500 ms lease (no fake time).
void caseRealClockTwoFeeds()
{
    beginCase("real_clock_opt_in_lease_valid_bound_once_feed_and_stopped_feed");
#if HAS_DRAW_GUARD
    Env mapping;
    setPresentationKeyClock(nullptr);
    setPresentationKeyLeaseMs(500);
    ByteImageProvider a, b;
    mapping.renderer->mapped = { kKeyA, kKeyB };
    check(a.setImageData(mapping.rsrc(mapping.resA), kKeyA), "valid feed A bound once");
    check(b.setImageData(mapping.rsrc(mapping.resB), kKeyB), "feed B entry");
    std::this_thread::sleep_for(std::chrono::milliseconds(700));
    check(b.setImageData(mapping.rsrc(mapping.resB), kKeyB), "feed B delivers a frame");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "valid mapped A keeps its key after 700 ms");

    Env shipped(false); // no per-key state
    setPresentationKeyClock(nullptr);
    setPresentationKeyLeaseMs(500);
    ByteImageProvider c, d;
    check(c.setImageData(shipped.rsrc(shipped.resA), kKeyA), "feed C entry");
    check(d.setImageData(shipped.rsrc(shipped.resB), kKeyB), "feed D entry");
    std::this_thread::sleep_for(std::chrono::milliseconds(700));
    check(d.setImageData(shipped.rsrc(shipped.resB), kKeyB), "feed D delivers a frame");
    check(c.getImGuiReference() == shipped.renderer->handleFor(&shipped.resA), "stopped C uses its texture after 700 ms");
    check(d.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "live D keeps its key");
    PlatformRegistry::instance().setImageProviderRenderer(mapping.renderer);
#else
    check(false, "there is no lease");
#endif
    endCase();
}

void caseUnknownStateKeepsKeyMode()
{
    beginCase("renderer_without_key_state_keeps_valid_key_mode");
    Env env(false); // a renderer that is not updated: the state of every key is unknown
    ByteImageProvider p;
    check(p.setImageData(env.rsrc(env.resA), kKeyA), "setup");
    check(p.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "a key of unknown state stays in use");
    endCase();
}

void caseInvalidSubframeKeyIsRetired()
{
    beginCase("invalid_subframe_key_is_retired_for_every_provider_that_holds_it");
    Env env(false); // the renderer as shipped: no per-key table
    ByteImageProvider a, b, other;
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "setup A");
    check(b.setImageData(env.rsrc(env.resB), kKeyA), "setup B with the same key");
    check(other.setImageData(env.rsrc(env.resC), kKeyB), "setup a live feed with another key");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "the key is in use before the invalid frame");
    check(retireKey(kKeyA), "the feeder retires the key");
    check(a.getImGuiReference() == env.renderer->handleFor(&env.resA), "A uses its texture after the key is retired");
    check(b.getImGuiReference() == env.renderer->handleFor(&env.resB), "B uses its texture after the key is retired");
    check(other.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "a feed with another key is not changed");
    // Leaving key mode forgets the state; a new feed with the same key is live again.
    callClear(a, 0);
    callClear(b, 0);
    check(a.setImageData(env.rsrc(env.resA), kKeyA), "A enters again with the same key");
    check(a.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "the new feed with the same key is live");
    endCase();
}

#if HAS_DRAW_GUARD
// ImGui draw data with one image command per key.
struct DrawFixture
{
    ImGuiContext* ctx = ImGui::CreateContext();
    std::vector<std::unique_ptr<ImDrawList>> lists;
    ImDrawData data;
    ~DrawFixture()
    {
        lists.clear(); // the draw lists must go before the context that owns their shared data
        ImGui::DestroyContext(ctx);
    }

    ImDrawList& addList()
    {
        lists.emplace_back(new ImDrawList(ImGui::GetDrawListSharedData()));
        ImDrawList& l = *lists.back();
        l._ResetForNewFrame();
        l.PushClipRect(ImVec2(0, 0), ImVec2(100, 100));
        return l;
    }
    void image(ImDrawList& l, uint64_t id)
    {
        l.AddImage(ImTextureRef(static_cast<ImTextureID>(id)), ImVec2(0, 0), ImVec2(10, 10));
    }
    ImDrawData& finish()
    {
        data.Valid = true;
        data.CmdLists.clear();
        for (auto& l : lists)
            data.CmdLists.push_back(l.get());
        data.CmdListsCount = data.CmdLists.Size;
        return data;
    }
    static int countId(ImDrawList& l, uint64_t id)
    {
        int n = 0;
        for (const ImDrawCmd& c : l.CmdBuffer)
            if (!c.UserCallback && c.TexRef._TexData == nullptr && c.TexRef._TexID == static_cast<ImTextureID>(id))
                ++n;
        return n;
    }
};
#endif


// The default of the library: no lease. A valid feed that does not renew the provider every frame
// keeps its key when the renderer has no key state (unknown). The case runs first, with the lease
// that the library has at start: nothing before it writes the lease (Env and the test reset do not),
// and each case that opts in to a lease gives back the value that it found. So the case fails when
// the initial lease is not 0.
void caseDefaultKeepsKeyOfBoundOncePausedAndSlowFeeds()
{
    beginCase("default_keeps_key_of_bound_once_paused_and_slow_feeds_unknown_state");
    Env env(false); // the renderer as shipped: the key state is unknown
    ByteImageProvider boundOnce, paused, slow;
    check(boundOnce.setImageData(env.rsrc(env.resA), kKeyA), "bound-once feed entry");
    check(paused.setImageData(env.rsrc(env.resB), kKeyB), "feed entry before a pause");
    check(slow.setImageData(env.rsrc(env.resC), kKeyC), "slow feed entry");
    advanceMs(1500);
    check(slow.setImageData(env.rsrc(env.resC), kKeyC), "slow feed: one frame after 1.5 s");
    advanceMs(1500);
    check(slow.setImageData(env.rsrc(env.resC), kKeyC), "slow feed: one frame after 3 s");
    // The viewport is paused with no call at all, for longer than the longest lease that the
    // setting can hold (2^32 - 1 ms, about 50 days). So any initial lease other than 0 ends the keys.
    advanceMs(0xFFFFFFFFull + 1000);
    check(boundOnce.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "bound-once feed keeps its key");
    check(paused.getImGuiReference() == reinterpret_cast<void*>(kKeyB), "paused feed keeps its key");
    check(slow.getImGuiReference() == reinterpret_cast<void*>(kKeyC), "slower-than-twice-per-second feed keeps its key");
    endCase();
}

#if HAS_DRAW_GUARD
// A client can keep the reference that getImGuiReference() gave and draw it in a later frame.
// The guard must still check it against the state of the renderer in that frame.
void caseDrawGuardChecksCachedReferencesInLaterFrames()
{
    beginCase("draw_guard_checks_cached_references_in_later_frames");
    Env env;
    env.renderer->mapped = { kKeyA, kKeyB, kKeyC };
    ByteImageProvider kept, cleared;
    check(kept.setImageData(env.rsrc(env.resA), kKeyA), "setup");
    check(cleared.setImageData(env.rsrc(env.resB), kKeyB), "setup second provider");
    std::unique_ptr<ByteImageProvider> gone(new ByteImageProvider());
    check(gone->setImageData(env.rsrc(env.resC), kKeyC), "setup third provider");

    // Frame 1: the widgets ask for their references and keep them. All keys are mapped.
    const uint64_t cachedKept = reinterpret_cast<uintptr_t>(kept.getImGuiReference());
    const uint64_t cachedCleared = reinterpret_cast<uintptr_t>(cleared.getImGuiReference());
    const uint64_t cachedGone = reinterpret_cast<uintptr_t>(gone->getImGuiReference());
    check(cachedKept == kKeyA && cachedCleared == kKeyB && cachedGone == kKeyC, "setup: the widgets got their keys");
    {
        DrawFixture f1;
        ImDrawList& l = f1.addList();
        f1.image(l, cachedKept);
        f1.image(l, cachedCleared);
        f1.image(l, cachedGone);
        check(dropUnmappedPresentationKeys(&f1.finish()) == 0, "frame 1: mapped keys are kept");
    }

    // Later frames: no provider is asked again. The clients draw the cached ids.
    cleared.clearPresentationKey();
    gone.reset();
    env.renderer->mapped.clear(); // the renderer reports all three keys unmapped
    {
        DrawFixture f2;
        ImDrawList& l = f2.addList();
        f2.image(l, cachedKept);
        f2.image(l, cachedCleared);
        f2.image(l, cachedGone);
        f2.image(l, 7); // an ordinary texture
        check(dropUnmappedPresentationKeys(&f2.finish()) == 3, "frame 2: the cached references of unmapped keys are removed");
        check(DrawFixture::countId(l, cachedKept) == 0, "frame 2: the key of a live provider is removed");
        check(DrawFixture::countId(l, cachedCleared) == 0, "frame 2: the key of a cleared provider is removed");
        check(DrawFixture::countId(l, cachedGone) == 0, "frame 2: the key of a destroyed provider is removed");
        check(DrawFixture::countId(l, 7) == 1, "frame 2: an ordinary texture is kept");
    }
    {
        DrawFixture f3; // the same again, much later, with the draw data in a different list
        ImDrawList& l0 = f3.addList();
        ImDrawList& l1 = f3.addList();
        f3.image(l0, cachedKept);
        f3.image(l1, cachedKept);
        check(dropUnmappedPresentationKeys(&f3.finish()) == 2, "frame 3: still removed in every draw list");
    }
    // A key that the renderer maps again is drawn again.
    env.renderer->mapped.insert(kKeyA);
    {
        DrawFixture f4;
        ImDrawList& l = f4.addList();
        f4.image(l, cachedKept);
        check(dropUnmappedPresentationKeys(&f4.finish()) == 0, "frame 4: a key that is mapped again is kept");
    }

    // The renderer as shipped reports no state: a cached key never reaches the back end.
    Env shipped(false);
    ByteImageProvider s;
    check(s.setImageData(shipped.rsrc(shipped.resA), kKeyA), "shipped: setup");
    const uint64_t cachedShipped = reinterpret_cast<uintptr_t>(s.getImGuiReference());
    for (int frame = 0; frame < 3; ++frame)
    {
        DrawFixture f;
        ImDrawList& l = f.addList();
        f.image(l, cachedShipped);
        check(dropUnmappedPresentationKeys(&f.finish()) == 1, "shipped: the cached key is removed in every frame");
    }
    endCase();
}

// A key that the feeder retired stays retired for the references that clients kept, while the renderer
// still reports the key mapped: while a provider holds it, and in the guard passes of the frame in
// which the last provider cleared it or was destroyed (and one more). Then the feed is done and its
// records, the retired state too, are freed: the renderer alone decides about the key again. A new
// feed with the same key (a new setImageData) is live again.
void caseRetiredCachedKeyAfterProviderExit()
{
    beginCase("retired_cached_key_is_removed_until_its_done_feed_is_freed");
    Env env;
    env.renderer->mapped = { kKeyA, kKeyB };
    ByteImageProvider cleared;
    std::unique_ptr<ByteImageProvider> destroyed(new ByteImageProvider());
    check(cleared.setImageData(env.rsrc(env.resA), kKeyA), "setup first provider");
    check(destroyed->setImageData(env.rsrc(env.resB), kKeyB), "setup second provider");
    const uint64_t cachedA = reinterpret_cast<uintptr_t>(cleared.getImGuiReference());
    const uint64_t cachedB = reinterpret_cast<uintptr_t>(destroyed->getImGuiReference());
    check(cachedA == kKeyA && cachedB == kKeyB, "setup: the widgets got their keys");
    auto drawCached = [&]() {
        DrawFixture f;
        ImDrawList& l = f.addList();
        f.image(l, cachedA);
        f.image(l, cachedB);
        return dropUnmappedPresentationKeys(&f.finish());
    };
    check(drawCached() == 0, "mapped keys are kept");
    retireKey(kKeyA);
    retireKey(kKeyB);
    for (int frame = 0; frame < 3; ++frame)
        check(drawCached() == 2, "retired keys that providers hold are removed in every frame");
    cleared.clearPresentationKey();
    destroyed.reset();
    // The renderer keeps the mapping. No new feed and no new key entry happened.
    for (uint64_t pass = 0; pass < kReleasedPresentationKeyPasses; ++pass)
        check(drawCached() == 2, "in the frame of the clear or destroy, and one more, the retired keys are removed");
    // The feeder retires a key after the last provider is gone, in the frame of the exit.
    {
        std::unique_ptr<ByteImageProvider> late(new ByteImageProvider());
        env.renderer->mapped.insert(kKeyC);
        check(late->setImageData(env.rsrc(env.resC), kKeyC), "setup third provider");
        const uint64_t cachedC = reinterpret_cast<uintptr_t>(late->getImGuiReference());
        late.reset();
        retireKey(kKeyC);
        DrawFixture f;
        ImDrawList& l = f.addList();
        f.image(l, cachedC);
        check(dropUnmappedPresentationKeys(&f.finish()) == 1, "a key retired after the last provider is gone is removed");
    }
    // The feeds are done and their last passes are over: the retired state is freed with the other
    // records. The renderer still maps the two keys, so their commands stay for it to replace.
    check(drawCached() == 0, "after the last passes of the done feeds their retired state is freed");
    // A new feed with the same key is live again.
    ByteImageProvider again;
    check(again.setImageData(env.rsrc(env.resA), kKeyA), "a new feed enters with the same key");
    {
        DrawFixture f;
        ImDrawList& l = f.addList();
        f.image(l, reinterpret_cast<uintptr_t>(again.getImGuiReference()));
        check(dropUnmappedPresentationKeys(&f.finish()) == 0, "the new feed key is drawn");
    }
    endCase();
}

// An app opens and closes many feeds with new keys. The records of each done feed are freed, so the
// work of the guard in each frame does not grow with the number of feeds that ended. A key that a
// provider still holds stays protected: its cached reference is checked in every frame.
void caseDoneFeedsAreFreedHeldKeysStayProtected()
{
    beginCase("done_feeds_free_their_key_records_held_keys_stay_protected");
    constexpr int kFeeds = 1000;
    {
        Env env;
        auto& renderer = static_cast<MappingRenderer&>(*env.renderer);
        ByteImageProvider held;
        env.renderer->mapped.insert(kKeyA);
        check(held.setImageData(env.rsrc(env.resA), kKeyA), "setup held feed");
        const uint64_t cachedHeld = reinterpret_cast<uintptr_t>(held.getImGuiReference());
        check(cachedHeld == kKeyA, "setup: the client keeps the key of the held feed");

        // Each feed: a new key enters, a widget draws it, the feed ends in one of four ways, and the
        // frame is drawn with the key of the feed and the cached key of the held feed.
        size_t lastFrameQueries = 0;
        for (int i = 0; i < kFeeds; ++i)
        {
            const uint64_t key = 0x100000000ull + static_cast<uint64_t>(i);
            env.renderer->mapped.insert(key);
            std::unique_ptr<ByteImageProvider> feed(new ByteImageProvider());
            check(feed->setImageData(env.rsrc(env.resB), key), "feed entry");
            const uint64_t drawn = reinterpret_cast<uintptr_t>(feed->getImGuiReference());
            switch (i % 4)
            {
            case 0:
                feed.reset();
                break;
            case 1:
                feed->clearPresentationKey();
                break;
            case 2:
                uploadCpu(*feed);
                break;
            default:
                retireKey(key);
                feed.reset();
                break;
            }
            env.renderer->mapped.erase(key); // the renderer drops the mapping of the done feed
            DrawFixture f;
            ImDrawList& l = f.addList();
            f.image(l, drawn);
            f.image(l, cachedHeld);
            const size_t asked = renderer.queries;
            check(dropUnmappedPresentationKeys(&f.finish()) == 1, "the key of the feed that ended in this frame is removed");
            check(DrawFixture::countId(l, cachedHeld) == 1, "the mapped key of the held feed is kept");
            lastFrameQueries = renderer.queries - asked;
        }
        // The guard asks about the held key and the feeds of the last passes, not about every feed.
        check(lastFrameQueries <= 1 + kReleasedPresentationKeyPasses,
              "the work of the guard does not grow with the feeds that ended: " + std::to_string(lastFrameQueries) +
                  " keys checked after " + std::to_string(kFeeds) + " feeds");
        for (uint64_t pass = 0; pass < kReleasedPresentationKeyPasses; ++pass)
        {
            DrawFixture f;
            f.addList();
            dropUnmappedPresentationKeys(&f.finish());
        }
        const size_t asked = renderer.queries;
        {
            DrawFixture f;
            f.addList();
            dropUnmappedPresentationKeys(&f.finish());
        }
        check(renderer.queries - asked == 1, "the records of all done feeds are freed; only the held key is checked");

        // The held key stays protected after all of that.
        env.renderer->mapped.erase(kKeyA);
        for (int frame = 0; frame < 3; ++frame)
        {
            DrawFixture f;
            ImDrawList& l = f.addList();
            f.image(l, cachedHeld);
            check(dropUnmappedPresentationKeys(&f.finish()) == 1, "the cached key of the held feed is removed once it is unmapped");
        }
        env.renderer->mapped.insert(kKeyA);
        retireKey(kKeyA);
        {
            DrawFixture f;
            ImDrawList& l = f.addList();
            f.image(l, cachedHeld);
            check(dropUnmappedPresentationKeys(&f.finish()) == 1, "the cached key of the held feed is removed once it is retired");
        }
    }
    {
        // The renderer as shipped (no key table): a feed that ends after its widget drew the key, in
        // the same frame, still has its key removed before the back end reads it.
        Env shipped(false);
        std::unique_ptr<ByteImageProvider> feed(new ByteImageProvider());
        check(feed->setImageData(shipped.rsrc(shipped.resA), kKeyB), "shipped: feed entry");
        const uint64_t drawn = reinterpret_cast<uintptr_t>(feed->getImGuiReference());
        feed.reset();
        DrawFixture f;
        ImDrawList& l = f.addList();
        f.image(l, drawn);
        check(dropUnmappedPresentationKeys(&f.finish()) == 1, "shipped: the key of a feed that ended in this frame is removed");
        check(DrawFixture::countId(l, kKeyB) == 0, "shipped: the key does not reach the back end");
    }
    {
        // A host that does not call the guard: the records of done feeds have a limit.
        Env env;
        auto& renderer = static_cast<MappingRenderer&>(*env.renderer);
        const size_t feeds = kMaxReleasedPresentationKeys + kFeeds;
        for (size_t i = 0; i < feeds; ++i)
        {
            const uint64_t key = 0x200000000ull + static_cast<uint64_t>(i);
            env.renderer->mapped.insert(key);
            ByteImageProvider feed;
            check(feed.setImageData(env.rsrc(env.resA), key), "feed entry without a guard");
            feed.getImGuiReference();
        }
        const size_t asked = renderer.queries;
        DrawFixture f;
        f.addList();
        dropUnmappedPresentationKeys(&f.finish());
        check(renderer.queries - asked <= kMaxReleasedPresentationKeys,
              "without a guard the records of done feeds are limited: " + std::to_string(renderer.queries - asked) +
                  " keys checked after " + std::to_string(feeds) + " feeds");
    }
    endCase();
}

// More feeds than the limit of done-feed records (kMaxReleasedPresentationKeys) end in one frame, after their
// widgets drew their keys and before the guard runs. Every key must still be removed: a key whose record was
// freed would reach the back end raw. In the next frame a client draws a kept reference of the first feed while
// as many feeds end again: the guard still checks that key in its second pass. Then the records are freed.
// A host that draws ImGui frames without the guard keeps the records of done feeds within the limit.
void caseFeedsBeyondTheRecordLimitEndInOneFrame()
{
    beginCase("feeds_beyond_the_record_limit_end_in_one_frame_every_key_is_checked");
    const size_t feeds = kMaxReleasedPresentationKeys + 1;
    {
        Env env;
        auto& renderer = static_cast<MappingRenderer&>(*env.renderer);
        // Each feed enters key mode and its widget draws the key; then all feeds end, the first one first, and the
        // renderer drops the mappings of the done feeds.
        auto openDrawAndEnd = [&](uint64_t firstKey, DrawFixture& f, ImDrawList& l) {
            std::vector<std::unique_ptr<ByteImageProvider>> open;
            size_t drawn = 0;
            for (size_t i = 0; i < feeds; ++i)
            {
                env.renderer->mapped.insert(firstKey + i);
                open.emplace_back(new ByteImageProvider());
                open.back()->setImageData(env.rsrc(env.resA), firstKey + i);
                const uint64_t id = reinterpret_cast<uintptr_t>(open.back()->getImGuiReference());
                drawn += id == firstKey + i ? 1 : 0;
                f.image(l, id);
            }
            check(drawn == feeds, "setup: every widget drew the key of its feed");
            open.clear();
            for (size_t i = 0; i < feeds; ++i)
                env.renderer->mapped.erase(firstKey + i);
        };
        auto keysLeft = [&](ImDrawList& l, uint64_t firstKey) {
            int n = 0;
            for (size_t i = 0; i < feeds; ++i)
                n += DrawFixture::countId(l, firstKey + i);
            return n;
        };
        const uint64_t first = 0x300000000ull;
        {
            DrawFixture f;
            ImDrawList& l = f.addList();
            openDrawAndEnd(first, f, l);
            const int queued = keysLeft(l, first);
            const size_t removed = dropUnmappedPresentationKeys(&f.finish());
            const int left = keysLeft(l, first);
            check(queued == static_cast<int>(feeds) && removed == feeds && left == 0,
                  "every key of the feeds that ended before the guard is removed: queued " + std::to_string(queued) +
                      ", removed " + std::to_string(removed) + ", left " + std::to_string(left));
            check(DrawFixture::countId(l, first) == 0, "the key of the first feed that ended does not reach the back end");
        }
        const uint64_t second = 0x400000000ull;
        {
            DrawFixture f;
            ImDrawList& l = f.addList();
            f.image(l, first); // a client draws the reference that it kept from the last frame
            openDrawAndEnd(second, f, l);
            const size_t removed = dropUnmappedPresentationKeys(&f.finish());
            check(removed == feeds + 1 && keysLeft(l, second) == 0,
                  "the next frame: every key of the new done feeds is removed: removed " + std::to_string(removed));
            check(DrawFixture::countId(l, first) == 0,
                  "the next frame: the kept key of the first feed is still checked in its second pass");
        }
        for (uint64_t pass = 0; pass < kReleasedPresentationKeyPasses; ++pass)
        {
            DrawFixture f;
            f.addList();
            dropUnmappedPresentationKeys(&f.finish());
        }
        const size_t asked = renderer.queries;
        {
            DrawFixture f;
            f.addList();
            dropUnmappedPresentationKeys(&f.finish());
        }
        check(renderer.queries == asked, "after their passes the records of all done feeds are freed: " +
                                             std::to_string(renderer.queries - asked) + " keys still checked");
    }
    {
        // A host that draws ImGui frames and never calls the guard. Its records of done feeds stay within the limit.
        Env env;
        auto& renderer = static_cast<MappingRenderer&>(*env.renderer);
        ImGuiContext* ctx = ImGui::CreateContext();
        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(100, 100);
        io.DeltaTime = 1.0f / 60.0f;
        io.BackendFlags |= ImGuiBackendFlags_RendererHasTextures; // there is no back end to upload the font atlas
        const size_t perFrame = 10;
        const size_t total = (kMaxReleasedPresentationKeys + 1000) / perFrame * perFrame;
        size_t drawn = 0;
        for (size_t i = 0; i < total; i += perFrame)
        {
            ImGui::NewFrame();
            for (size_t k = 0; k < perFrame; ++k)
            {
                const uint64_t key = 0x500000000ull + i + k;
                env.renderer->mapped.insert(key);
                ByteImageProvider feed;
                feed.setImageData(env.rsrc(env.resA), key);
                drawn += reinterpret_cast<uintptr_t>(feed.getImGuiReference()) == key ? 1 : 0;
            }
            ImGui::Render();
        }
        check(drawn == total, "setup: every feed gave out its key");
        ImDrawData data;
        data.Valid = true;
        const size_t asked = renderer.queries;
        dropUnmappedPresentationKeys(&data);
        check(renderer.queries - asked <= kMaxReleasedPresentationKeys,
              "frames without a guard: the records of done feeds are limited: " +
                  std::to_string(renderer.queries - asked) + " keys checked after " + std::to_string(total) + " feeds");
        ImGui::DestroyContext(ctx);
    }
    endCase();
}

struct CaptureLog : IUiLog
{
    std::vector<std::string> lines;
    void add(const char* fmt, va_list args)
    {
        char buf[512];
        vsnprintf(buf, sizeof(buf), fmt, args);
        lines.push_back(buf);
    }
    void logError(const char* fmt, va_list args) override { add(fmt, args); }
    void logWarn(const char* fmt, va_list args) override { add(fmt, args); }
    void logInfo(const char* fmt, va_list args) override { add(fmt, args); }

    size_t count(const std::string& a, const std::string& b = std::string()) const
    {
        size_t n = 0;
        for (const auto& l : lines)
            if (l.find(a) != std::string::npos && l.find(b) != std::string::npos)
                ++n;
        return n;
    }
};

// A fallback to the retained texture, and a removed draw command, must say why. One line for each
// transition, not one for each frame.
void caseFallbacksAreLoggedOncePerTransition()
{
    beginCase("fallbacks_are_logged_once_per_transition_with_key_and_reason");
    auto log = std::make_shared<CaptureLog>();
    PlatformRegistry::instance().setLog(log);
    {
        Env env;
        env.renderer->mapped = { kKeyA, kKeyB, kKeyC };
        setPresentationKeyLeaseMs(500);
        ByteImageProvider unmapped, retired, expired;
        check(unmapped.setImageData(env.rsrc(env.resA), kKeyA), "setup unmapped");
        check(retired.setImageData(env.rsrc(env.resB), kKeyB), "setup retired");
        check(expired.setImageData(env.rsrc(env.resC), kKeyC), "setup expired");
        for (int i = 0; i < 3; ++i) // the keys are in use: nothing to report
        {
            unmapped.getImGuiReference();
            retired.getImGuiReference();
            expired.getImGuiReference();
        }
        check(log->lines.empty(), "no line while the keys are in use");

        env.renderer->mapped.erase(kKeyA);
        retireKey(kKeyB);
        for (int i = 0; i < 5; ++i)
        {
            unmapped.getImGuiReference();
            retired.getImGuiReference();
        }
        check(log->count(std::to_string(kKeyA), "unmapped") == 1, "unmapped key: one line with the key and the reason");
        check(log->count(std::to_string(kKeyB), "retired") == 1, "retired key: one line with the key and the reason");
        check(log->lines.size() == 2, "five frames of fallback did not add lines");

        // Removed draw commands: one line for a key while it is removed.
        log->lines.clear();
        PlatformRegistry::instance().setLog(log);
        DrawFixture fx;
        for (int frame = 0; frame < 4; ++frame)
        {
            ImDrawList& l = fx.addList();
            fx.image(l, kKeyA);
            fx.image(l, kKeyB);
        }
        check(dropUnmappedPresentationKeys(&fx.finish()) == 8, "the commands are removed");
        for (int i = 0; i < 3; ++i)
        {
            DrawFixture again;
            ImDrawList& l = again.addList();
            again.image(l, kKeyA);
            again.image(l, kKeyB);
            dropUnmappedPresentationKeys(&again.finish());
        }
        check(log->count(std::to_string(kKeyA), "draw") == 1, "removed commands of the unmapped key: one line");
        check(log->count(std::to_string(kKeyB), "draw") == 1, "removed commands of the retired key: one line");
        check(log->count(std::to_string(kKeyA), "unmapped") == 1, "the removal line gives the reason (unmapped)");
        check(log->count(std::to_string(kKeyB), "retired") == 1, "the removal line gives the reason (retired)");
    }
    {
        log->lines.clear();
        // The renderer reports no key state: the opt-in lease ends the key of a silent feed.
        Env unknown(false);
        setPresentationKeyLeaseMs(500);
        ByteImageProvider silent;
        check(silent.setImageData(unknown.rsrc(unknown.resA), kKeyC), "setup silent feed");
        advanceMs(600);
        for (int i = 0; i < 5; ++i)
            silent.getImGuiReference();
        check(log->count(std::to_string(kKeyC), "expired") == 1, "expired key: one line with the key and the reason");

        // After a new frame the key is in use again; a second stop gives a second line.
        check(silent.setImageData(unknown.rsrc(unknown.resA), kKeyC), "the feed delivers again");
        check(silent.getImGuiReference() == reinterpret_cast<void*>(kKeyC), "the key is in use again");
        advanceMs(600);
        silent.getImGuiReference();
        silent.getImGuiReference();
        check(log->count(std::to_string(kKeyC), "expired") == 2, "a new transition gives a new line");

    }
    {
        log->lines.clear();
        // Presentation is off: a provider that holds a key uses its texture, as it always did without the present
        // thread. That is not a fallback, so there is no line, also not when presentation is on again.
        Env env;
        env.renderer->mapped = { kKeyA };
        ByteImageProvider held;
        check(held.setImageData(env.rsrc(env.resA), kKeyA), "setup held key");
        env.renderer->globalEnabled = false;
        for (int i = 0; i < 3; ++i)
            check(held.getImGuiReference() == env.renderer->handleFor(&env.resA), "presentation off: the texture is used");
        env.renderer->globalEnabled = true;
        check(held.getImGuiReference() == reinterpret_cast<void*>(kKeyA), "presentation on: the key is used");
        check(log->lines.empty(), "presentation off and on again writes no line: " + std::to_string(log->lines.size()) +
                                      " lines");
        // A real fallback that starts while presentation is off is reported once presentation is on again.
        env.renderer->globalEnabled = false;
        retireKey(kKeyA);
        held.getImGuiReference();
        env.renderer->globalEnabled = true;
        held.getImGuiReference();
        held.getImGuiReference();
        check(log->count(std::to_string(kKeyA), "retired") == 1 && log->lines.size() == 1,
              "a key retired while presentation is off: one line once presentation is on");
    }
    PlatformRegistry::instance().setLog(nullptr);
    endCase();
}
#endif

void caseDrawGuard()
{
    beginCase("draw_guard_removes_keys_without_a_drawable");
#if HAS_DRAW_GUARD
    Env env;
    DrawFixture fx;
    ByteImageProvider live, dying, retired;
    env.renderer->mapped = { kKeyA, kKeyB, kKeyC };
    check(live.setImageData(env.rsrc(env.resA), kKeyA), "setup live");
    check(dying.setImageData(env.rsrc(env.resB), kKeyB), "setup dying");
    check(retired.setImageData(env.rsrc(env.resC), kKeyC), "setup retired");
    ImDrawList& l0 = fx.addList();
    ImDrawList& l1 = fx.addList();
    // The widgets ask for the references while building the frame.
    const uint64_t liveId = reinterpret_cast<uintptr_t>(live.getImGuiReference());
    const uint64_t dyingId = reinterpret_cast<uintptr_t>(dying.getImGuiReference());
    const uint64_t retiredId = reinterpret_cast<uintptr_t>(retired.getImGuiReference());
    check(liveId == kKeyA && dyingId == kKeyB && retiredId == kKeyC, "setup: the widgets got their keys");
    fx.image(l0, liveId);
    fx.image(l0, dyingId);
    fx.image(l1, dyingId);
    fx.image(l1, retiredId);
    fx.image(l1, 7); // an ordinary texture name is not a key
    // After the widgets asked: the renderer drops the mapping of B, and the feed of C is retired.
    env.renderer->mapped.erase(kKeyB);
    retireKey(kKeyC);
    size_t dropped = dropUnmappedPresentationKeys(&fx.finish());
    check(dropped == 3, "the commands of the two dead keys are removed");
    check(DrawFixture::countId(l0, kKeyB) == 0 && DrawFixture::countId(l1, kKeyB) == 0, "no command of the unmapped key is left");
    check(DrawFixture::countId(l1, kKeyC) == 0, "no command of the retired key is left");
    check(DrawFixture::countId(l0, kKeyA) == 1, "the live key is kept");
    check(DrawFixture::countId(l1, 7) == 1, "an ordinary texture is kept");
    check(dropUnmappedPresentationKeys(&fx.finish()) == 0, "the frame state is cleared");

    // The renderer as shipped has no key table: no key may reach the back end, also a key that
    // was never notified.
    Env shipped(false);
    DrawFixture fx2;
    ByteImageProvider never;
    check(never.setImageData(shipped.rsrc(shipped.resA), kKeyC), "setup never-notified feed");
    ImDrawList& l2 = fx2.addList();
    const uint64_t id = reinterpret_cast<uintptr_t>(never.getImGuiReference());
    fx2.image(l2, id);
    fx2.image(l2, 7);
    check(dropUnmappedPresentationKeys(&fx2.finish()) == (id == kKeyC ? 1u : 0u), "a key without a table is removed");
    check(DrawFixture::countId(l2, kKeyC) == 0, "the never-notified key does not reach the back end");
    check(DrawFixture::countId(l2, 7) == 1, "an ordinary texture is kept");

    // No renderer at all: nothing can map a key.
    DrawFixture fx3;
    ImDrawList& l3 = fx3.addList();
    fx3.image(l3, kKeyA);
    recordIssuedPresentationKey(env.renderer.get(), kKeyA);
    PlatformRegistry::instance().setImageProviderRenderer(nullptr);
    check(dropUnmappedPresentationKeys(&fx3.finish()) == 1, "without a renderer an issued key is removed");
    PlatformRegistry::instance().setImageProviderRenderer(shipped.renderer);
#else
    check(false, "there is no draw-side guard for unmapped keys");
#endif
    endCase();
}

} // namespace

int main()
{
    caseDefaultKeepsKeyOfBoundOncePausedAndSlowFeeds(); // first: it checks the initial lease, untouched
    caseFailedEntryStoresNoKey();
    caseGoodEntryStoresKey();
    caseSameResourceEntryRelatches();
    caseExplicitExit();
    caseByteUploadTransitions(false);
    caseByteUploadTransitions(true);
    caseGpuUploadUnsupported();
    caseIndependentFeeds();
    caseStoppedFeedLosesKeyWhileOtherFeedIsLive();
    caseMappedFeedIsNotExpiredByLease();
    caseRealClockTwoFeeds();
    caseUnknownStateKeepsKeyMode();
    caseInvalidSubframeKeyIsRetired();
    caseDrawGuard();
#if HAS_DRAW_GUARD
    caseDrawGuardChecksCachedReferencesInLaterFrames();
    caseRetiredCachedKeyAfterProviderExit();
    caseDoneFeedsAreFreedHeldKeysStayProtected();
    caseFeedsBeyondTheRecordLimitEndInOneFrame();
    caseFallbacksAreLoggedOncePerTransition();
#endif

    std::cout << (g_totalCases - g_failedCases) << "/" << g_totalCases << " cases passed" << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
