/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// OpenGLByteImageGpu reports what it can prove (issue 230).
//
// An OpenGL upload is queued. Big textures take real GPU time, so the backend
// must report eEnqueued, and an upload id may count as completed only after a
// GL fence behind it has signaled. A request for a second device must fail
// before it uploads. The test starts ovui in headless EGL mode, as the other
// EGL tests do, and uses the backend that ovui registers. A start that fails
// fails the test with its cause: this test is built only with EGL, and EGL
// also works without a GPU (Mesa surfaceless), so there is no hardware reason
// to skip it.

#include "StandaloneInit.h"

#include <glad/glad.h>

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

using namespace omni::ui;
namespace standalone = omni::ui::standalone;

namespace
{
int g_failures = 0;
void check(bool ok, const char* what)
{
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf("  %s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok)
        ++g_failures;
}
} // namespace

int main()
{
#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "1");
    _putenv_s("OMNIUI_HEADLESS_GL", "1");
#else
    setenv("OMNIUI_HEADLESS", "1", 1);
    setenv("OMNIUI_HEADLESS_GL", "1", 1);
#endif
    if (!standalone::init("egl_upload_completion", 64, 64))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::fprintf(stderr, "FAIL: standalone::init() could not start headless EGL; see the messages above\n");
        return 1;
    }
    IByteImageGpu* plain = PlatformRegistry::instance().byteImageGpu();
    IByteImageGpuChecked* checked = PlatformRegistry::instance().byteImageGpuChecked();
    if (!plain || !checked)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::fprintf(stderr, "FAIL: headless EGL registered no %s\n",
                     plain ? "checked upload interface (IByteImageGpuChecked)" : "byte image backend");
        standalone::shutdown();
        return 1;
    }
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf("GL renderer: %s\n", glGetString(GL_RENDERER));

    IByteImageGpuChecked& gpu = *checked;
    auto h = plain->createState();
    constexpr uint32_t N = 2048;
    std::vector<unsigned char> px((size_t)N * N * 4, 127);
    const uint8_t* buffers[] = { px.data() };
    size_t stride = (size_t)N * 4;

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf("[1] five large uploads\n");
    bool allEnqueued = true, idsGrow = true, neverAhead = true;
    uint64_t last = 0;
    for (int i = 0; i < 5; ++i)
    {
        UploadResult r = gpu.updateImageChecked(h, buffers, &stride, 1, { N, N }, PixelFormat::eRGBA8_UNORM, false,
                                                1, 0, 0);
        allEnqueued = allEnqueued && r.status == UploadStatus::eEnqueued;
        idsGrow = idsGrow && r.uploadId > last && r.uploadedDeviceMask == 1u && r.requestedDeviceMask == 1u;
        last = r.uploadId;
        neverAhead = neverAhead && gpu.getCompletedUploadId(h) <= r.uploadId;
    }
    check(allEnqueued, "every upload is eEnqueued, never eComplete on submission");
    check(idsGrow, "ids grow, device mask 1 is reported as uploaded 1");
    check(neverAhead, "the completed id is never ahead of the upload ids");

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf("[2] completion needs a signaled fence\n");
    glFinish();
    uint64_t done = 0;
    const auto start = std::chrono::steady_clock::now();
    while (done != last && std::chrono::steady_clock::now() - start < std::chrono::seconds(5))
        done = gpu.getCompletedUploadId(h);
    check(done == last, "after glFinish the completed id reaches the last upload");

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf("[3] a second device is refused before any upload\n");
    UploadResult two = gpu.updateImageChecked(h, buffers, &stride, 1, { N, N }, PixelFormat::eRGBA8_UNORM, false, 3,
                                              0, 0);
    check(two.status == UploadStatus::eFailed, "mask 3 fails");
    check(two.requestedDeviceMask == 3u && two.uploadedDeviceMask == 0u, "requested 3, uploaded 0");
    check(gpu.getCompletedUploadId(h) == last, "no id was used");

    plain->destroyState(h);
    standalone::shutdown();
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    std::printf(g_failures == 0 ? "PASS\n" : "FAIL\n");
    return g_failures == 0 ? 0 : 1;
}
