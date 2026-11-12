/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Thread rules of ImageProvider (issue 227).
 *
 * The main thread of this program is the UI thread: it calls
 * ImageProvider::applyPublishedUpdates(), as a frame does. A second thread
 * plays a render thread. A fake backend stands in for the GPU and records the
 * thread of each upload. The cases check that:
 *
 *   - a change given with publishOnUiThread() on another thread does not
 *     change the provider until the UI thread runs it, and then runs there,
 *     in order, with the reference and the size of the same change;
 *   - an upload given that way runs in the backend on the UI thread;
 *   - with replacePending only the newest waiting frame stays, the replaced
 *     frames are released at once, and a change given without it is never
 *     dropped;
 *   - the waiting changes of a destroyed provider are released and never run;
 *   - a change that throws does not stop the next one;
 *   - a change given while a pass runs waits for the next pass, also when it
 *     replaces a waiting change (replacePending);
 *   - a changing call on another thread is counted and still made (release
 *     build) or stops the process with an assert (debug build), a call on the
 *     UI thread is not counted, and destroying a provider on another thread is
 *     not counted;
 *   - under load, every read of the UI thread sees a reference and a size of
 *     the same change.
 *
 * Every case runs to the end and reports alone.
 */

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <atomic>
#include <cstdint>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#if !defined(NDEBUG) && defined(__unix__)
#    include <csignal>
#    include <sys/wait.h>
#    include <unistd.h>
#endif

using namespace omni::ui;

namespace
{

std::vector<std::string> g_caseFailures;
std::string g_caseName;
int g_failedCases = 0;

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
    // This thread is the UI thread, as in a frame.
    ImageProvider::applyPublishedUpdates();
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

void* ref(uintptr_t value)
{
    return reinterpret_cast<void*>(value);
}

uintptr_t refOf(ImageProvider& p)
{
    return reinterpret_cast<uintptr_t>(p.getImGuiReference());
}

/// Records the thread of each upload.
class ThreadRecordingGpu : public IByteImageGpu
{
public:
    Handle createState() override { return new int(0); }
    void destroyState(Handle h) override { delete static_cast<int*>(h); }
    void releaseImage(Handle) override {}

    UpdateResult updateImage(Handle, const uint8_t* const*, size_t*, size_t, UInt2, PixelFormat, bool, uint32_t,
                             uint32_t, uint32_t) override
    {
        std::lock_guard<std::mutex> lock(mutex);
        threads.push_back(std::this_thread::get_id());
        UpdateResult r;
        r.imGuiReference = ref(0x1000 + threads.size());
        return r;
    }

    std::mutex mutex;
    std::vector<std::thread::id> threads;
};

/// Counts how many copies of a frame are still owned.
struct Frame
{
    explicit Frame(std::atomic<int>& alive, int number) : alive(alive), number(number) { ++alive; }
    ~Frame() { --alive; }
    std::atomic<int>& alive;
    int number;
};

void casePublishedChangesRunOnTheUiThread()
{
    beginCase("a change from another thread runs on the UI thread, in order, as one unit");
    auto provider = ImageProvider::create<ImageProvider>();
    const auto uiThread = std::this_thread::get_id();
    std::vector<int> order;
    bool allOnUiThread = true;
    std::vector<uint64_t> ids;

    std::thread render([&]() {
        for (int i = 1; i <= 3; ++i)
        {
            ids.push_back(provider->publishOnUiThread([&, i](ImageProvider& p) {
                order.push_back(i);
                allOnUiThread = allOnUiThread && std::this_thread::get_id() == uiThread;
                p.setImageData(ref(0x10 + i), { uint32_t(i), uint32_t(2 * i) }, PixelFormat::eRGBA8_UNORM);
            }));
        }
    });
    render.join();

    check(ids == std::vector<uint64_t>({ 1, 2, 3 }), "the changes get the numbers 1, 2, 3");
    check(refOf(*provider) == 0 && provider->getWidth() == 0, "nothing changes before the UI thread runs the changes");
    check(provider->getAppliedPublicationId() == 0, "no change counts as applied before the UI thread ran it");
    check(order.empty(), "no change runs on the render thread");

    const size_t ran = ImageProvider::applyPublishedUpdates();
    check(ran == 3, "the UI thread runs the 3 changes, got " + std::to_string(ran));
    check(order == std::vector<int>({ 1, 2, 3 }), "the changes run in the order of the calls");
    check(allOnUiThread, "every change runs on the UI thread");
    check(refOf(*provider) == 0x13 && provider->getWidth() == 3 && provider->getHeight() == 6,
          "the reference and the size come from the last change");
    check(provider->getAppliedPublicationId() == 3, "the applied number is 3");
    check(ImageProvider::applyPublishedUpdates() == 0, "a second pass has nothing to run");
    endCase();
}

void casePublishedUploadRunsInTheBackendOnTheUiThread()
{
    beginCase("an upload given from a render thread reaches the backend on the UI thread");
    auto gpu = std::make_shared<ThreadRecordingGpu>();
    PlatformRegistry::instance().setByteImageGpu(gpu);
    {
        auto provider = ImageProvider::create<ByteImageProvider>();
        const uint64_t offThreadBefore = ImageProvider::getOffUiThreadCallCount();
        auto pixels = std::make_shared<std::vector<uint8_t>>(4 * 2 * 2, uint8_t(7));
        std::thread render([&]() {
            provider->publishOnUiThread(
                [pixels](ImageProvider& p) {
                    static_cast<ByteImageProvider&>(p).setBytesData(pixels->data(), { 2, 2 });
                },
                true);
        });
        render.join();
        check(gpu->threads.empty(), "the render thread does not call the backend");
        ImageProvider::applyPublishedUpdates();
        check(gpu->threads.size() == 1 && gpu->threads[0] == std::this_thread::get_id(),
              "the backend gets the upload on the UI thread");
        check(provider->getWidth() == 2 && provider->isReferenceValid(), "the provider shows the uploaded image");
        check(ImageProvider::getOffUiThreadCallCount() == offThreadBefore,
              "an upload given with publishOnUiThread is not reported");
    }
    PlatformRegistry::instance().reset();
    endCase();
}

void caseReplacePendingKeepsTheNewestFrame()
{
    beginCase("replacePending keeps only the newest waiting frame; other changes are never dropped");
    auto provider = ImageProvider::create<ImageProvider>();
    std::atomic<int> alive{ 0 };
    std::vector<int> ran;

    std::thread render([&]() {
        for (int i = 1; i <= 5; ++i)
        {
            auto frame = std::make_shared<Frame>(alive, i);
            provider->publishOnUiThread(
                [frame, &ran](ImageProvider& p) {
                    ran.push_back(frame->number);
                    p.setImageData(ref(frame->number), { 1, 1 }, PixelFormat::eRGBA8_UNORM);
                },
                true);
        }
    });
    render.join();
    check(alive == 1, "the 4 replaced frames are released at once, " + std::to_string(alive.load()) + " still owned");
    check(ImageProvider::applyPublishedUpdates() == 1, "one change runs");
    check(ran == std::vector<int>({ 5 }) && refOf(*provider) == 5, "the newest frame is shown");
    check(provider->getAppliedPublicationId() == 5, "the applied number is the number of the newest frame");
    check(alive == 0, "the frame is released after it ran");

    // A change given without replacePending is never replaced, and a replaceable change after it is a
    // new entry.
    ran.clear();
    auto give = [&](int number, bool replace) {
        provider->publishOnUiThread([number, &ran](ImageProvider&) { ran.push_back(number); }, replace);
    };
    std::thread mixed([&]() {
        give(10, true);
        give(11, false);
        give(12, true);
        give(13, true);
        give(14, false);
        give(15, false);
    });
    mixed.join();
    ImageProvider::applyPublishedUpdates();
    check(ran == std::vector<int>({ 10, 11, 13, 14, 15 }),
          "only 12 is replaced (by 13); the other changes run in order");
    endCase();
}

void caseDestroyedProviderDropsItsChanges()
{
    beginCase("the waiting changes of a destroyed provider are released and never run");
    std::atomic<int> alive{ 0 };
    bool ran = false;
    {
        auto provider = ImageProvider::create<ImageProvider>();
        auto frame = std::make_shared<Frame>(alive, 1);
        provider->publishOnUiThread([frame, &ran](ImageProvider&) { ran = true; });
        provider->publishOnUiThread([frame, &ran](ImageProvider&) { ran = true; });
    }
    check(alive == 0, "the captured frame is released with the provider");
    check(ImageProvider::applyPublishedUpdates() == 0 && !ran, "no change of the destroyed provider runs");
    endCase();
}

void caseFailingChangeDoesNotStopTheNext()
{
    beginCase("a change that throws does not stop the next change");
    auto provider = ImageProvider::create<ImageProvider>();
    provider->publishOnUiThread([](ImageProvider&) { throw std::runtime_error("test failure"); });
    provider->publishOnUiThread(
        [](ImageProvider& p) { p.setImageData(ref(0x55), { 5, 5 }, PixelFormat::eRGBA8_UNORM); });
    check(ImageProvider::applyPublishedUpdates() == 2, "both changes are taken");
    check(refOf(*provider) == 0x55, "the change after the failing one is made");
    check(provider->getAppliedPublicationId() == 2, "the applied number is 2");
    endCase();
}

void caseChangeGivenDuringAPassWaits()
{
    beginCase("a change given while a pass runs waits for the next pass");
    auto provider = ImageProvider::create<ImageProvider>();
    int second = 0;
    provider->publishOnUiThread([&](ImageProvider& p) {
        p.publishOnUiThread([&](ImageProvider&) { ++second; });
    });
    check(ImageProvider::applyPublishedUpdates() == 1 && second == 0, "the first pass runs only the first change");
    check(ImageProvider::applyPublishedUpdates() == 1 && second == 1, "the next pass runs the second change");
    endCase();
}

void caseReplacementGivenDuringAPassWaits()
{
    beginCase("a change that replaces a waiting change while a pass runs waits for the next pass");
    auto first = ImageProvider::create<ImageProvider>();
    auto second = ImageProvider::create<ImageProvider>();
    int replacedRuns = 0;
    int replacementRuns = 0;
    // A gives C, which replaces the waiting change B of the second provider.
    first->publishOnUiThread([&](ImageProvider&) {
        second->publishOnUiThread([&](ImageProvider&) { ++replacementRuns; }, /*replacePending*/ true);
    });
    second->publishOnUiThread([&](ImageProvider&) { ++replacedRuns; }, /*replacePending*/ true);
    check(ImageProvider::applyPublishedUpdates() == 1 && replacementRuns == 0,
          "the first pass runs only A; C was given during it");
    check(replacedRuns == 0, "B was replaced and never runs");
    check(ImageProvider::applyPublishedUpdates() == 1 && replacementRuns == 1, "the next pass runs C");
    endCase();
}

void caseChangeOnAnotherThreadIsReported()
{
    beginCase("a changing call on another thread is reported; a call on the UI thread is not");
    auto provider = ImageProvider::create<ImageProvider>();
    const uint64_t before = ImageProvider::getOffUiThreadCallCount();
    provider->setImageData(ref(0x21), { 2, 1 }, PixelFormat::eRGBA8_UNORM);
    provider->setImageData(ref(0x21), { 2, 1 }, PixelFormat::eRGBA8_UNORM);
    check(ImageProvider::getOffUiThreadCallCount() == before, "calls on the UI thread are not counted");

#if defined(NDEBUG)
    std::thread render([&]() {
        provider->setImageData(ref(0x22), { 4, 1 }, PixelFormat::eRGBA8_UNORM);
        provider->setImageData(ref(0x22), { 4, 1 }, PixelFormat::eRGBA8_UNORM);
    });
    render.join();
    check(ImageProvider::getOffUiThreadCallCount() == before + 2, "each call on the render thread is counted");
    check(refOf(*provider) == 0x22 && provider->getWidth() == 4, "the change is still made, as before");
#elif defined(__unix__)
    // A debug build stops at the first such call. Run it in a child process.
    std::cout.flush();
    const pid_t child = fork();
    if (child == 0)
    {
        std::thread render([&]() { provider->setImageData(ref(0x22), { 4, 1 }, PixelFormat::eRGBA8_UNORM); });
        render.join();
        _exit(0);
    }
    int status = 0;
    waitpid(child, &status, 0);
    check(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT, "the debug build stops with an assert");
#endif

    // Destroying a provider that nothing draws is not a change of a drawn image.
    const uint64_t beforeDestroy = ImageProvider::getOffUiThreadCallCount();
    std::thread owner([p = std::move(provider)]() mutable { p.reset(); });
    owner.join();
    check(ImageProvider::getOffUiThreadCallCount() == beforeDestroy, "destroying on another thread is not counted");
    endCase();
}

void caseUnderLoadEveryReadIsOneUnit()
{
    beginCase("under load, the UI thread always reads the reference and the size of one change");
    auto provider = ImageProvider::create<ImageProvider>();
    const uint64_t offThreadBefore = ImageProvider::getOffUiThreadCallCount();
    constexpr uint32_t kFrames = 20000;
    std::atomic<bool> done{ false };
    std::thread render([&]() {
        for (uint32_t i = 1; i <= kFrames; ++i)
        {
            provider->publishOnUiThread(
                [i](ImageProvider& p) { p.setImageData(ref(i), { i, i }, PixelFormat::eRGBA8_UNORM); }, true);
        }
        done = true;
    });
    uint64_t mixed = 0;
    uint64_t reads = 0;
    while (!done || provider->getAppliedPublicationId() < kFrames)
    {
        ImageProvider::applyPublishedUpdates();
        const uintptr_t r = refOf(*provider);
        const UInt2 size = provider->getSize();
        ++reads;
        if (r != size.x || r != size.y)
            ++mixed;
    }
    render.join();
    check(mixed == 0, std::to_string(mixed) + " of " + std::to_string(reads) + " reads mixed two changes");
    check(refOf(*provider) == kFrames, "the last frame is shown");
    check(ImageProvider::getOffUiThreadCallCount() == offThreadBefore, "nothing is reported");
    endCase();
}

} // namespace

int main()
{
    casePublishedChangesRunOnTheUiThread();
    casePublishedUploadRunsInTheBackendOnTheUiThread();
    caseReplacePendingKeepsTheNewestFrame();
    caseDestroyedProviderDropsItsChanges();
    caseFailingChangeDoesNotStopTheNext();
    caseChangeGivenDuringAPassWaits();
    caseReplacementGivenDuringAPassWaits();
    caseChangeOnAnotherThreadIsReported();
    caseUnderLoadEveryReadIsOneUnit();
    std::cout << (g_failedCases == 0 ? "ALL PASS" : "SOME FAILED") << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
