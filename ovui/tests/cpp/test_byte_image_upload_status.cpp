/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Upload results of ByteImageProvider.
 *
 * A fake backend stands in for the GPU, so every outcome is reachable without
 * a device, a window or a patched renderer. The cases check that:
 *
 *   - a rejected upload is reported as eFailed and counted, and the previous
 *     texture stays in place;
 *   - a backend that rejects an upload but returns its old texture reference
 *     (the Vulkan "no free slot" case) is not taken as success;
 *   - an upload for several devices is accepted only when all of them took it;
 *   - eEnqueued and eComplete differ, and completion arrives later through
 *     getCompletedUploadId() and an event that names the devices of its own
 *     upload, also after a later upload was refused;
 *   - a subscriber that throws does not undo the upload and does not hide the
 *     event from the other subscribers;
 *   - a failed result says why;
 *   - a backend that has no IByteImageGpuChecked still gives a truthful
 *     answer for the cases it can tell apart;
 *   - injectUploadFailures() makes the uploads of one provider fail without a
 *     renderer patch, also for code that uploads for it without its upload
 *     functions, and other providers are not affected;
 *   - no backend is not a failure: nothing is counted and no event is sent;
 *   - a backend without IByteImageGpuChecked never gets a completed id, since
 *     nothing proves that a copy ended;
 *   - replacing the backend does not keep the checked interface of the old one;
 *   - the old setBytesData* functions still work.
 *
 * Every case runs to the end and reports alone.
 */

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

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

/// How the next upload of the fake backend ends.
enum class Next
{
    eAccept,            ///< new reference, eComplete
    eAcceptPending,     ///< new reference, eEnqueued
    eReject,            ///< empty result
    eRejectKeepOld,     ///< eFailed, but the old reference is still returned
    eAcceptNoReference, ///< claims success with no texture
    ePartialDevices,    ///< eFailed, only one of two requested devices took it
};

/// Legacy backend: only IByteImageGpu.
class LegacyGpu : public IByteImageGpu
{
public:
    Next next = Next::eAccept;
    int uploads = 0;
    int serial = 0;
    void* lastRef = nullptr;

    Handle createState() override { return new int(0); }
    void destroyState(Handle h) override { delete static_cast<int*>(h); }
    void releaseImage(Handle) override {}

    UpdateResult updateImage(Handle, const uint8_t* const*, size_t*, size_t, UInt2, PixelFormat, bool, uint32_t,
                             uint32_t, uint32_t) override
    {
        ++uploads;
        UpdateResult r;
        switch (next)
        {
            case Next::eAccept:
            case Next::eAcceptPending:
                lastRef = reinterpret_cast<void*>(static_cast<uintptr_t>(0x1000 + ++serial));
                r.imGuiReference = lastRef;
                break;
            case Next::eRejectKeepOld:
                r.imGuiReference = lastRef;
                break;
            default:
                break;
        }
        return r;
    }
};

/// Checked backend: reports status, ids and devices.
class CheckedGpu : public LegacyGpu, public IByteImageGpuChecked
{
public:
    uint64_t completedId = 0;
    uint64_t lastId = 0;
    int checkedCalls = 0;

    UploadResult updateImageChecked(Handle h, const uint8_t* const* b, size_t* s, size_t mips, UInt2 size,
                                    PixelFormat format, bool fromGpu, uint32_t mask, uint32_t, uint32_t) override
    {
        ++checkedCalls;
        const Next what = next;
        UploadResult out;
        out.requestedDeviceMask = mask;
        out.update = LegacyGpu::updateImage(h, b, s, mips, size, format, fromGpu, mask, 0, 0);
        switch (what)
        {
            case Next::eAccept:
                out.status = UploadStatus::eComplete;
                out.uploadId = completedId = ++lastId;
                out.uploadedDeviceMask = mask;
                break;
            case Next::eAcceptPending:
            case Next::eAcceptNoReference:
                out.status = UploadStatus::eEnqueued;
                out.uploadId = ++lastId;
                out.uploadedDeviceMask = mask;
                break;
            case Next::ePartialDevices:
                out.uploadedDeviceMask = mask & 1u;
                out.cause = "fake: device 1 refused";
                break;
            case Next::eRejectKeepOld:
                out.cause = "fake: all slots busy";
                break;
            default:
                break;
        }
        if (what == Next::eAcceptNoReference)
        {
            out.update.imGuiReference = nullptr;
        }
        return out;
    }

    uint64_t getCompletedUploadId(Handle) override { return completedId; }
};

template <class Gpu>
std::shared_ptr<Gpu> install(bool checked)
{
    auto gpu = std::make_shared<Gpu>();
    auto& reg = PlatformRegistry::instance();
    reg.setByteImageGpu(gpu);
    if constexpr (std::is_base_of_v<IByteImageGpuChecked, Gpu>)
    {
        if (checked)
        {
            reg.setByteImageGpuChecked(gpu);
        }
    }
    return gpu;
}

void uninstall()
{
    PlatformRegistry::instance().reset();
}

const uint8_t kPixels[4 * 4 * 4] = {};
const UInt2 kSize = { 4, 4 };

void caseLegacyAcceptReject()
{
    beginCase("legacy backend: accept, then reject keeps the old texture and reports the failure");
    auto gpu = install<LegacyGpu>(false);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        ByteImageUploadResult a = p->uploadBytesData(kPixels, kSize);
        check(a.accepted() && a.status == UploadStatus::eEnqueued, "first upload is accepted (eEnqueued)");
        check(a.uploadId == 1, "first upload id is 1");
        check(p->isReferenceValid(), "reference valid after first upload");
        void* ref = p->getImGuiReference();

        gpu->next = Next::eReject;
        ByteImageUploadResult b = p->uploadBytesData(kPixels, kSize);
        check(!b.accepted() && !static_cast<bool>(b), "rejected upload is not accepted");
        check(b.uploadId == 0, "rejected upload has no id");
        check(p->getImGuiReference() == ref, "previous texture stays after rejection");
        check(p->getUploadFailureCount() == 1, "one failure is counted");
        check(!p->getLastUploadResult().accepted(), "last result is the failure");

        gpu->next = Next::eAccept;
        ByteImageUploadResult c = p->uploadBytesData(kPixels, kSize);
        check(c.accepted() && c.uploadId == 2, "recovers on the next upload; ids keep growing");
        check(p->getImGuiReference() != ref, "new texture published after recovery");
    }
    uninstall();
    endCase();
}

void caseFirstUploadFails()
{
    beginCase("first upload fails: provider has no image");
    auto gpu = install<LegacyGpu>(false);
    gpu->next = Next::eReject;
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(!r.accepted(), "first upload is rejected");
        check(r.cause && std::string(r.cause) == "the backend returned no texture", "the failure says why");
        check(!p->isReferenceValid(), "no reference after a failed first upload");
        check(p->getWidth() == 0, "size stays 0");
    }
    uninstall();
    endCase();
}

void caseCheckedStaleReference()
{
    beginCase("checked backend: eFailed with the old reference is not success");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        check(p->uploadBytesData(kPixels, kSize).status == UploadStatus::eComplete, "first upload is eComplete");
        void* ref = p->getImGuiReference();
        gpu->next = Next::eRejectKeepOld;
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(!r.accepted(), "stale-reference rejection is a failure");
        check(r.cause && std::string(r.cause) == "fake: all slots busy", "the cause of the backend is passed on");
        check(p->getImGuiReference() == ref, "old texture is kept");
        check(p->getUploadFailureCount() == 1, "failure counted");
        check(gpu->checkedCalls == 2, "the checked entry point was used");
    }
    uninstall();
    endCase();
}

void caseAcceptedWithoutReference()
{
    beginCase("checked backend: success without a texture is a failure");
    auto gpu = install<CheckedGpu>(true);
    gpu->next = Next::eAcceptNoReference;
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(!r.accepted(), "no reference means failure");
        check(r.cause != nullptr, "the failure says why");
        check(!p->isReferenceValid(), "no reference published");
    }
    uninstall();
    endCase();
}

/// Gives the test access to the texture options of a provider.
class DeviceMaskProvider : public ByteImageProvider
{
public:
    void setDeviceMask(uint32_t mask)
    {
        TextureOptions options;
        options.gpuDeviceMask = mask;
        setTextureOptions(options);
    }
};

void caseDevices()
{
    beginCase("several devices: accepted only when all took it");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<DeviceMaskProvider>();
        p->setDeviceMask(3u);
        gpu->next = Next::ePartialDevices;
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(!r.accepted(), "one of two devices is a failure");
        check(r.requestedDeviceMask == 3u && r.uploadedDeviceMask == 1u, "result tells which device took the pixels");
        check(p->getLastUploadResult().uploadedDeviceMask == 1u, "last result keeps the masks");
        check(!p->isReferenceValid(), "nothing published");
        gpu->next = Next::eAccept;
        r = p->uploadBytesData(kPixels, kSize);
        check(r.accepted() && r.uploadedDeviceMask == 3u, "all devices took it: accepted");
    }
    uninstall();
    endCase();
}

void caseCompletion()
{
    beginCase("eEnqueued and completion: id, event, once");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        std::vector<ByteImageUploadEvent> events;
        const uint64_t sub = p->subscribeUploadEvents([&](const ByteImageUploadEvent& e) { events.push_back(e); });
        check(sub != 0, "subscription id is not 0");

        gpu->next = Next::eAcceptPending;
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(r.status == UploadStatus::eEnqueued && r.uploadId == 1, "pending upload is eEnqueued");
        check(p->getCompletedUploadId() == 0, "not completed yet");
        check(events.size() == 1 && events[0].kind == ByteImageUploadEvent::Kind::eEnqueued, "only eEnqueued event");

        gpu->completedId = 1;
        check(p->getCompletedUploadId() == 1, "completed after the backend says so");
        check(events.size() == 2 && events[1].kind == ByteImageUploadEvent::Kind::eCompleted &&
                  events[1].uploadId == 1,
              "eCompleted event for upload 1");
        p->getCompletedUploadId();
        p->prepareDraw(1.f, 1.f);
        check(events.size() == 2, "the same completion is sent once");

        gpu->next = Next::eAccept;
        p->uploadBytesData(kPixels, kSize);
        check(events.size() == 4 && events[2].kind == ByteImageUploadEvent::Kind::eEnqueued &&
                  events[3].kind == ByteImageUploadEvent::Kind::eCompleted && events[3].uploadId == 2,
              "synchronous upload sends eEnqueued then eCompleted");

        gpu->next = Next::eReject;
        p->uploadBytesData(kPixels, kSize);
        check(events.size() == 5 && events[4].kind == ByteImageUploadEvent::Kind::eFailed, "failure event");

        p->unsubscribeUploadEvents(sub);
        p->uploadBytesData(kPixels, kSize);
        check(events.size() == 5, "no event after unsubscribe");
    }
    uninstall();
    endCase();
}

void caseCompletionKeepsItsDevices()
{
    beginCase("a completion event names the devices of its own upload, not of a later refused one");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<DeviceMaskProvider>();
        std::vector<ByteImageUploadEvent> events;
        p->subscribeUploadEvents([&](const ByteImageUploadEvent& e) { events.push_back(e); });
        p->setDeviceMask(1u);
        gpu->next = Next::eAcceptPending;
        const ByteImageUploadResult a = p->uploadBytesData(kPixels, kSize);
        check(a.status == UploadStatus::eEnqueued && a.uploadId == 1, "A is queued on device 0");
        p->setDeviceMask(3u);
        gpu->next = Next::eReject;
        check(!p->uploadBytesData(kPixels, kSize).accepted(), "B, for devices 0 and 1, is refused");
        gpu->completedId = 1;
        check(p->getCompletedUploadId() == 1, "A completes");
        const ByteImageUploadEvent& done = events.back();
        check(done.kind == ByteImageUploadEvent::Kind::eCompleted && done.uploadId == 1, "completion event for A");
        check(done.requestedDeviceMask == 1u && done.uploadedDeviceMask == 1u,
              "the completion of A reports A's devices (requested 1, uploaded 1), not B's");

        // Two queued uploads with different devices complete one after the other.
        p->setDeviceMask(1u);
        gpu->next = Next::eAcceptPending;
        p->uploadBytesData(kPixels, kSize); // id 2, device 0
        p->setDeviceMask(0u);
        p->uploadBytesData(kPixels, kSize); // id 3, default device
        gpu->completedId = 2;
        p->getCompletedUploadId();
        check(events.back().uploadId == 2 && events.back().requestedDeviceMask == 1u, "upload 2 completes with mask 1");
        gpu->completedId = 3;
        p->getCompletedUploadId();
        check(events.back().uploadId == 3 && events.back().requestedDeviceMask == 0u, "upload 3 completes with mask 0");
    }
    uninstall();
    endCase();
}

void caseThrowingSubscriber()
{
    beginCase("a subscriber that throws does not undo the upload or hide the event");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        int seenByOther = 0;
        p->subscribeUploadEvents([](const ByteImageUploadEvent&) { throw std::runtime_error("subscriber bug"); });
        p->subscribeUploadEvents([&](const ByteImageUploadEvent&) { ++seenByOther; });
        bool threw = false;
        ByteImageUploadResult r;
        try
        {
            r = p->uploadBytesData(kPixels, kSize);
        }
        catch (...)
        {
            threw = true;
        }
        check(!threw, "the upload call does not throw");
        check(r.accepted() && p->getLastUploadResult().accepted(), "the upload is accepted");
        check(seenByOther == 2, "the other subscriber gets eEnqueued and eCompleted");
    }
    uninstall();
    endCase();
}

void caseInjection()
{
    beginCase("injectUploadFailures: fails before the backend, then recovers");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        auto other = ImageProvider::create<ByteImageProvider>();
        check(p->uploadBytesData(kPixels, kSize).accepted(), "baseline upload works");
        void* ref = p->getImGuiReference();
        const int before = gpu->checkedCalls;
        p->injectUploadFailures(2);
        check(other->uploadBytesData(kPixels, kSize).accepted(), "another provider is not affected");
        ByteImageUploadResult first = p->uploadBytesData(kPixels, kSize);
        check(!first.accepted(), "first injected failure");
        check(first.cause && std::string(first.cause).find("injectUploadFailures") != std::string::npos,
              "the cause names the hook");
        check(!p->uploadBytesDataFromGPU(kPixels, kSize).accepted(), "second injected failure (GPU source)");
        check(gpu->checkedCalls == before + 1, "the backend got only the upload of the other provider");
        check(p->getImGuiReference() == ref, "old texture stays");
        check(p->getUploadFailureCount() == 2, "two failures counted");
        check(other->getUploadFailureCount() == 0, "no failure for the other provider");
        check(p->uploadBytesData(kPixels, kSize).accepted(), "the third upload works");
        check(p->injectUploadFailures(0) == 0, "no injected failure is left");
    }
    uninstall();
    endCase();
}

void caseLegacyNeverCompletes()
{
    beginCase("legacy backend: accepted, but no completed id and no completed event");
    auto gpu = install<LegacyGpu>(false);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        std::vector<ByteImageUploadEvent> events;
        p->subscribeUploadEvents([&](const ByteImageUploadEvent& e) { events.push_back(e); });
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(r.status == UploadStatus::eEnqueued, "accepted as eEnqueued, never eComplete");
        check(p->getCompletedUploadId() == 0, "completed id stays 0");
        p->prepareDraw(1.f, 1.f);
        check(p->getCompletedUploadId() == 0, "completed id stays 0 after a draw");
        bool anyCompleted = false;
        for (const auto& e : events)
            anyCompleted = anyCompleted || e.kind == ByteImageUploadEvent::Kind::eCompleted;
        check(!anyCompleted, "no completed event");
    }
    uninstall();
    endCase();
}

void caseBackendReplacement()
{
    beginCase("replacing the backend drops the checked interface of the old one");
    auto oldGpu = install<CheckedGpu>(true);
    auto replacement = std::make_shared<LegacyGpu>();
    PlatformRegistry::instance().setByteImageGpu(replacement);
    check(PlatformRegistry::instance().byteImageGpuChecked() == nullptr, "no checked interface after the swap");
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        ByteImageUploadResult r = p->uploadBytesData(kPixels, kSize);
        check(r.accepted(), "the upload is accepted by the replacement");
        check(replacement->uploads == 1, "the replacement got the upload");
        check(oldGpu->checkedCalls == 0, "the old backend got nothing");
    }
    uninstall();
    endCase();
}

void caseInjectionWithoutUploadFunctions()
{
    beginCase("takeInjectedUploadFailure serves code that uploads for a provider without its upload functions");
    auto p = ImageProvider::create<ByteImageProvider>();
    auto other = ImageProvider::create<ByteImageProvider>();
    p->injectUploadFailures(1);
    check(!other->takeInjectedUploadFailure(), "another provider has none");
    check(p->takeInjectedUploadFailure(), "the first call takes the failure");
    check(!p->takeInjectedUploadFailure(), "the second call finds none");
    endCase();
}

void caseNoBackendAndNull()
{
    beginCase("no backend is not a failure; null bytes are failures with a cause");
    uninstall();
    auto p = ImageProvider::create<ByteImageProvider>();
    std::vector<ByteImageUploadEvent> events;
    p->subscribeUploadEvents([&](const ByteImageUploadEvent& e) { events.push_back(e); });
    ByteImageUploadResult none = p->uploadBytesData(kPixels, kSize);
    check(none.status == UploadStatus::eNoBackend && !none.accepted(), "no backend: eNoBackend, not accepted");
    check(none.cause != nullptr, "no backend: says why nothing was uploaded");
    check(p->getUploadFailureCount() == 0, "no backend: no failure counted");
    check(events.empty(), "no backend: no event");
    check(p->getLastUploadResult().status == UploadStatus::eNoBackend, "no backend: it is the last result");
    ByteImageUploadResult null = p->uploadBytesData(nullptr, kSize);
    check(!null.accepted() && null.status == UploadStatus::eFailed, "null bytes is a failure");
    check(null.cause && std::string(null.cause).find("null") != std::string::npos, "the cause names the null pointer");
    check(!p->uploadBytesDataFromGPU(nullptr, kSize).accepted(), "null GPU bytes is a failure");
    check(p->getUploadFailureCount() == 2, "two failures counted");
    check(events.size() == 2 && events[0].kind == ByteImageUploadEvent::Kind::eFailed, "two failure events");
    ByteImageUploadResult input = p->rejectUpload("test: the input cannot be read");
    check(!input.accepted() && std::string(input.cause) == "test: the input cannot be read",
          "rejectUpload records the refusal with its cause");
    check(p->getUploadFailureCount() == 3 && events.size() == 3, "rejectUpload counts it and sends an event");
    endCase();
}

void caseMipAndLegacySetters()
{
    beginCase("mip upload returns a result; old setters still work");
    auto gpu = install<CheckedGpu>(true);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        ByteImageUploadResult r = p->uploadMipMappedBytesData(kPixels, kSize, 16, PixelFormat::eRGBA8_UNORM);
        check(r.accepted(), "generated mip chain is accepted");
        const int calls = gpu->uploads;
        p->setBytesData(kPixels, kSize);
        p->setMipMappedBytesData(kPixels, kSize, 16);
        p->setBytesDataFromGPU(kPixels, kSize);
        check(gpu->uploads == calls + 3, "old setters reach the backend");
        static_assert(std::is_void_v<decltype(p->setBytesData(kPixels, kSize))>,
                      "setBytesData keeps its void result for binary compatibility");
        gpu->next = Next::eReject;
        p->setBytesData(kPixels, kSize);
        check(p->getUploadFailureCount() == 1, "failure of an old setter is still recorded");
        check(!p->uploadMipMappedBytesData(kPixels, kSize, 16, PixelFormat::eRGBA8_UNORM).accepted(),
              "failed mip upload returns eFailed");
    }
    uninstall();
    endCase();
}

} // namespace

void caseShapeRefusedBeforeTheBackend()
{
    beginCase("a zero size, an unknown format or a short stride is refused before the backend, with a cause");
    auto gpu = install<LegacyGpu>(false);
    {
        auto p = ImageProvider::create<ByteImageProvider>();
        std::vector<ByteImageUploadEvent> events;
        p->subscribeUploadEvents([&](const ByteImageUploadEvent& e) { events.push_back(e); });
        ByteImageUploadResult zero = p->uploadBytesData(kPixels, { 0, 4 });
        check(!zero.accepted() && zero.status == UploadStatus::eFailed, "zero width is a failure");
        check(zero.cause && std::string(zero.cause).find("size, format or stride") != std::string::npos,
              "the cause names the shape");
        check(!p->uploadBytesData(kPixels, kSize, kAutoCalculateStride, PixelFormat::eUnknown).accepted(),
              "an unknown format is a failure");
        check(!p->uploadBytesData(kPixels, kSize, 8).accepted(), "a stride shorter than one row is a failure");
        check(!p->uploadBytesDataFromGPU(kPixels, { 4, 0 }).accepted(), "zero height from the GPU is a failure");
        size_t strides[1] = { kAutoCalculateStride };
        const uint8_t* mips[1] = { kPixels };
        check(!p->uploadMipMappedBytesData(mips, strides, 0, kSize).accepted(), "no mip levels is a failure");
        check(!p->uploadMipMappedBytesData(kPixels, { 0, 0 }, kAutoCalculateStride).accepted(),
              "a zero size with generated mip levels is a failure");
        check(gpu->uploads == 0, "the backend is not called");
        check(p->getUploadFailureCount() == 6 && events.size() == 6, "each refusal is counted and sends an event");
        check(p->uploadBytesData(kPixels, kSize).accepted(), "a good upload is still accepted");
    }
    uninstall();
    endCase();
}

int main()
{
    caseLegacyAcceptReject();
    caseFirstUploadFails();
    caseCheckedStaleReference();
    caseAcceptedWithoutReference();
    caseDevices();
    caseCompletion();
    caseCompletionKeepsItsDevices();
    caseThrowingSubscriber();
    caseInjection();
    caseLegacyNeverCompletes();
    caseBackendReplacement();
    caseInjectionWithoutUploadFunctions();
    caseNoBackendAndNull();
    caseMipAndLegacySetters();
    caseShapeRefusedBeforeTheBackend();
    std::cout << (g_failedCases == 0 ? "ALL PASS" : "SOME FAILED") << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
