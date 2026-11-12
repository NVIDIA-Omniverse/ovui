/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "../Object.h"
#include "../Property.h"

#include <omni/ui/platform/Types.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <utility>

// Forward declaration for opaque GPU resource type used only by pointer/reference.
namespace omni { namespace core { template <class T> class Api; } }
namespace carb { namespace imaging { class IMetadata_abi; using IMetadata = omni::core::Api<IMetadata_abi>; } }
namespace rtx { namespace resourcemanager { class RpResource; } }

namespace omni
{
namespace ui
{

constexpr const size_t kAutoCalculateStride = (size_t)-1;

/// Texture creation options for ImageProvider.
/// Layout matches omni::kit::renderer::IRendererTextureOptions.
struct ImageProviderTextureOptions
{
    uint32_t gpuDeviceMask = 0;
    uint32_t textureUsageFlags = 0;
    uint32_t resourceUsageFlags = 0;
    union
    {
        bool pooled;
        uint32_t unusedExtPadding = 0;
    };
};

/**
 * @brief Gives an image to the widgets that draw it (ImageWithProvider and the scene image).
 *
 * Threads. The UI thread is the thread that draws the UI frame, the owner of the ImGui context. The
 * draw reads the texture reference, the size, the format, the display window, the mip count, the managed
 * resource and the presentation key on that thread, with no lock, and keeps the reference in the draw
 * data until the frame is rendered. So these values and the GPU objects behind them are one unit: change
 * them only on the UI thread.
 *  - Call setImageData(), clearPresentationKey(), the setBytesData* and uploadBytesData* functions of
 *    ByteImageProvider and the Python functions that call them only on the UI thread. On another thread
 *    such a call races with the draw: the draw can use a reference with the size of another image, or a
 *    reference whose texture the call releases or replaces.
 *  - Read the image values (getImGuiReference(), getSize(), getFormat(), getManagedResource() and the
 *    others) only on the UI thread.
 *  - A thread that makes images, for example a render thread, gives them with publishOnUiThread(). The
 *    UI thread then makes the change before it draws. This is the only supported change from another
 *    thread.
 *  - These functions can be called on any thread: publishOnUiThread(), getAppliedPublicationId(),
 *    getOffUiThreadCallCount(), retirePresentationKey(), setPresentationKeyLeaseMs(), and on a
 *    ByteImageProvider getLastUploadResult(), getUploadFailureCount(), subscribeUploadEvents(),
 *    unsubscribeUploadEvents(), injectUploadFailures() and hasUploadBackend().
 *  - Before the first UI frame (applyPublishedUpdates() was never called) the UI thread is not known and
 *    nothing is checked.
 *
 * A change on another thread is reported: getOffUiThreadCallCount() counts it, the first one of each
 * provider writes an error line, and a debug build stops with an assert. In a release build the change
 * is still made, as before, but the back end can refuse it: the OpenGL back end uploads only on the
 * thread of its GL context, so it refuses an upload from another thread, keeps the previous image and
 * reports the refusal in ByteImageProvider::getLastUploadResult().
 */
class OMNIUI_CLASS_API ImageProvider
{
protected:
    using GpuResource = rtx::resourcemanager::RpResource;
    using TextureOptions = ImageProviderTextureOptions;

public:
    /// A change of a provider that the UI thread makes. See publishOnUiThread().
    using PublishedUpdate = std::function<void(ImageProvider&)>;

    OMNIUI_API
    ImageProvider();

    OMNIUI_API
    virtual ~ImageProvider();

    /**
     * @brief Returns reference which could be used to draw ImGui images with.
     *
     * In presentation-key mode the stored key is returned, but only while
     * presentation is enabled, the key is not retired and the renderer does not
     * report it as unmapped. In all other cases
     * the texture reference is returned. When the provider changes from the key to the texture
     * reference because the key is retired, unmapped or expired, it writes one log line with the key
     * and the reason (not one line for each frame). While presentation is off, the texture reference
     * is the normal reference, so no line is written.
     * A client can keep the returned reference. The draw guard
     * (dropUnmappedPresentationKeys) checks a kept key again in every later frame while a provider
     * holds the key, and for one more frame after the last provider lets it go.
     */
    OMNIUI_API
    virtual void* getImGuiReference();

    /**
     * @brief Leaves presentation-key mode. The provider goes back to its texture reference.
     *
     * It does not change the texture reference or the managed resource.
     * It is safe to call when the provider is not in key mode. Call it on the UI thread.
     */
    OMNIUI_API
    void clearPresentationKey();

    /**
     * @brief Retires a presentation key for every provider that holds it.
     *
     * The feed of the key calls it when the feed ends or sends an invalid frame. A provider does
     * not return a retired key, so a live feed of another provider cannot keep it in use. The
     * provider leaves key mode with clearPresentationKey() or a byte upload. A new successful
     * setImageData() with the same key makes it live again.
     */
    OMNIUI_API
    static void retirePresentationKey(uint64_t key);

    /**
     * @brief Opt in to a lease: how long a presentation key stays in use without a new
     * setImageData() call.
     *
     * The default is 0: there is no lease. A key stays in use until it is retired, the provider
     * leaves key mode, or the renderer reports it unmapped. So a feed that is bound once, paused
     * or slow keeps its key, as before.
     * A host whose renderer reports no key state can set a lease. Every successful
     * setImageData(resource, key) arms the key again. After the lease without a new call, the
     * provider uses its texture reference (the last frame) instead of the key. A key that the
     * renderer reports as mapped never expires. The setting is for the whole process, but each
     * provider is armed by its own calls. Only use it when the feed calls setImageData
     * more often than the lease.
     */
    OMNIUI_API
    static void setPresentationKeyLeaseMs(uint32_t ms);

    /**
     * @brief Returns the stored presentation key, or 0 when the provider is not in key mode.
     */
    OMNIUI_API
    uint64_t getPresentationKey() const
    {
        return m_presentationKey;
    }

    /**
     * @brief Returns true if ImGui reference is valid, false otherwise.
     */
    OMNIUI_API
    virtual bool isReferenceValid()
    {
        return m_imGuiReference != nullptr;
    }

    /**
     * @brief Gets image width.
     */
    OMNIUI_API
    size_t getWidth()
    {
        return m_imageSize.x;
    }

    /**
     * @brief Gets image height.
     */
    OMNIUI_API
    size_t getHeight()
    {
        return m_imageSize.y;
    }

    /**
     * @brief Gets tuple (width, height).
     */
    OMNIUI_API
    UInt2 getSize()
    {
        return m_imageSize;
    }

    /**
     * @brief Gets display window w.r.t to the image (data window). The display size is same as the viewport size.
     */
    OMNIUI_API
    DisplayWindowRect getDisplayWindow()
    {
        return m_imageDisplayWindow;
    }

    /**
     * @brief Gets image format.
     */
    OMNIUI_API
    PixelFormat getFormat()
    {
        return m_imageFormat;
    }

    /**
     * @brief Function that should be called when the widget is being prepared to be drawn. Lazy load of image
     * contents may happen there, depending on the image provider logic.
     * @param widgetWidth Computed width of the widget.
     * @param widgetHeight Computed height of the widget.
     */
    OMNIUI_API
    virtual void prepareDraw(float widgetWidth, float widgetHeight);

    /**
     * @brief Sets non-managed image data directly. Call it on the UI thread.
     * @param imGuiReference Opaque pointer to the data used in the ImGuiRenderer.
     * @param size Size tuple (width, height) of the image data.
     * @param format Pixel format of the image data.
     * @param gpuRsrc The GpuResource to be associated with the image data. Can be nullptr.
     */
    OMNIUI_API
    void setImageData(void* imGuiReference, UInt2 size, PixelFormat format, GpuResource* gpuRsrc = nullptr);

    /**
     * @brief Sets image data directly from a GpuResource. Call it on the UI thread.
     * @param rpRsrc The GpuResource to be used for data.
     * @return A boolean value whether the image-data was set.
     *         On success the GpuResource will have been retained, otherwise not.
     */
    OMNIUI_API
    bool setImageData(GpuResource& gpuRsrc);

    /**
     * Sets image data directly from a GpuResource. Call it on the UI thread.
     *
     * @param gpuRsrc The GpuResource to be used for data.
     * @param presentationKey The presentation key associated with the GpuResource. Used by the present thread to get the ImGui reference.
     *                        The key is stored only when the call succeeds, also when the same resource is set again.
     *                        A failed call does not change the key or the mode. A key of 0 means texture mode.
     *
     * @return A boolean value indicating whether the image-data was set.
     *         On success, the GpuResource will have been retained, otherwise not.
     */
    OMNIUI_API
    bool setImageData(GpuResource& gpuRsrc, uint64_t presentationKey);

    // Native metadata interop is implemented by the renderer bridge. Call it on the UI thread.
    OMNIUI_API
    bool setImageData(GpuResource& gpuRsrc, uint64_t presentationKey, carb::imaging::IMetadata* metadata);

    /**
     * @brief Shuts down the image provider system
     */
    OMNIUI_API
    static void shutdown();

    /**
     * @brief Returns the managed GPU resource. Call it on the UI thread: the next change can release it.
     */
    OMNIUI_API
    GpuResource* getManagedResource();

    /**
     * @brief Gives a change of this provider to the UI thread. It can be called on any thread.
     *
     * Use it to give images from another thread, for example a render thread. The UI thread runs
     * ``update`` with this provider once per frame, before it draws: the standalone platforms run the
     * waiting changes before any window is drawn, and a host that does not gets them before the first
     * ImageWithProvider of the frame (applyPublishedUpdates()). ``update`` calls the
     * usual functions, for example setImageData() or uploadBytesDataFromGPU(), so the reference, the
     * size, the format, the display window, the mip count, the managed resource and the presentation
     * key change together, between two draws, and a texture is released only on the UI thread.
     *
     * ``update`` must own what it uses: capture the pixels, the GPU memory or the GPU resource (for
     * example in a std::shared_ptr) so that they stay valid until it has run. It is destroyed on the UI
     * thread after it ran. A change that is replaced is destroyed on the thread that replaced it, in
     * publishOnUiThread(); a change of a provider that is destroyed before it ran, on the thread that
     * destroys the provider. So when what it owns must be released on the UI thread (for example a
     * reference to a GPU resource), its destructor gives it back to the UI thread instead of releasing it.
     *
     * The changes of one provider run in the order of the calls. No change is dropped, except when
     * ``replacePending`` is true: then this change replaces the last waiting change of this provider if
     * that change was also given with ``replacePending`` (a mailbox: a render thread that is faster than
     * the UI does not queue frames that nobody would see). A change given while the changes run, also one
     * that replaces a waiting change, runs in the next frame. A change that throws is reported in the
     * log; the next changes still run.
     *
     * A provider that is destroyed on another thread while the UI thread runs one of its changes waits
     * until that change has ended, with no time limit: the change can still use the provider. So a change
     * must not wait for the thread that destroys its provider.
     *
     * @return The number of this change for this provider, 1 or more, or 0 when ``update`` is empty.
     *         Compare it with getAppliedPublicationId().
     */
    OMNIUI_API
    uint64_t publishOnUiThread(PublishedUpdate update, bool replacePending = false);

    /**
     * @brief The highest number given by publishOnUiThread() whose change has run, or was replaced by a
     * later change that has run. 0 before the first one. It can be called on any thread.
     *
     * A producer can free what a change used when this number reaches the number of that change.
     */
    OMNIUI_API
    uint64_t getAppliedPublicationId() const;

    /**
     * @brief Runs the changes given with publishOnUiThread() to all providers. Call it on the UI thread.
     *
     * The standalone platforms call it once per frame, after ImGui::NewFrame() and before they draw the
     * windows; then ImageWithProvider does not call it again in that frame. A host that does not call it
     * gets one call at the first ImageWithProvider of the frame. A host that draws providers in another
     * way calls it once per frame before the draw. Changes given while it runs wait for the next call.
     *
     * The calling thread becomes the UI thread of the thread checks. Call it only on the UI thread: a call
     * on another thread moves the checks to that thread, so they then report the calls of the real UI
     * thread and miss the calls of that thread.
     *
     * @return The number of changes that ran.
     */
    OMNIUI_API
    static size_t applyPublishedUpdates();

    /**
     * @brief How many changing calls ran on a thread that is not the UI thread, in this process.
     * It can be called on any thread. A test of a host can check that it stays 0.
     */
    OMNIUI_API
    static uint64_t getOffUiThreadCallCount();

protected:
    /**
     * @brief Release the managed image data, called from setImageData
     */
    OMNIUI_API
    virtual void _releaseImage()
    {
    }

    void _shutdown();

    OMNIUI_API
    virtual bool _setManagedResource(GpuResource* rpRsrc);

    /** Stores the key and keeps the hold count of the key state. 0 means texture mode. */
    OMNIUI_API
    void _setPresentationKey(uint64_t key);

    bool _isPresentationKeyLeased() const;

    OMNIUI_API
    virtual bool mergeTextureOptions(TextureOptions& textureOptions) const;

    OMNIUI_API
    virtual bool setTextureOptions(TextureOptions textureOptions);

    void* m_imGuiReference = nullptr;
    UInt2 m_imageSize = {};
    DisplayWindowRect m_imageDisplayWindow = { 0.0f, 0.0f, 1.0f, 1.0f };
    PixelFormat m_imageFormat = PixelFormat::eRGBA8_UNORM;
    size_t m_imageMipCount = 1;
    bool m_isShutdown = false;

    void* m_kitRenderer = nullptr;
    GpuResource* m_managedRsrc = nullptr;
    uint64_t m_presentationKey = 0;
    uint64_t m_presentationKeyArmedNs = 0; // last successful setImageData with the key
    uint8_t m_presentationKeyFallback = 0; // reason of the last fallback that was logged, 0: the key is in use
    bool m_hasFuture = false;
    uint32_t m_id = 0;

public:
    template <typename T, typename... Args>
    static std::shared_ptr<T> create(Args&&... args)
    {
        std::shared_ptr<T> ptr{ new T{ std::forward<Args>(args)... } };
        return ptr;
    }

    template <typename T, typename Deleter, typename... Args>
    static std::shared_ptr<T> createWithDeleter(Deleter&& deleter, Args&&... args)
    {
        return std::shared_ptr<T>{ new T{ std::forward<Args>(args)... }, std::forward<Deleter>(deleter) };
    }
};

}
}
