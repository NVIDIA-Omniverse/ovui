/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include <omni/ui/Api.h>
#include <memory>

namespace omni {
namespace ui {

// Forward declarations for the abstract interfaces
class IUiSettings;
class IUiFileIO;
class IUiRenderer;
class IUiPlatform;
class IByteImageGpu;
class IGlyphManager;
class IImageBackend;
class IImageProviderRenderer;
class IDynamicTextureGpu;
class ISvgRasterizer;
class IUiLog;
class IRasterImageLoader;

namespace windowmanager
{
class IWindowCallbackManager;
} // namespace windowmanager

/// Singleton registry that holds the platform-specific implementations
/// of the four abstract interfaces. In Kit mode, the adapters are registered
/// during extension startup. In standalone mode, the standalone backend
/// registers its implementations.
class PlatformRegistry
{
public:
    OMNIUI_API static PlatformRegistry& instance();

    void setSettings(std::shared_ptr<IUiSettings> s) { m_settings = std::move(s); }
    void setFileIO(std::shared_ptr<IUiFileIO> f) { m_fileIO = std::move(f); }
    void setRenderer(std::shared_ptr<IUiRenderer> r) { m_renderer = std::move(r); }
    void setPlatform(std::shared_ptr<IUiPlatform> p) { m_platform = std::move(p); }
    void setWindowCallbackManager(windowmanager::IWindowCallbackManager* m) { m_windowCallbackManager = m; }
    void setGlyphManager(std::shared_ptr<IGlyphManager> g) { m_glyphManager = std::move(g); }
    void setByteImageGpu(std::shared_ptr<IByteImageGpu> g) { m_byteImageGpu = std::move(g); }
    void setImageBackend(std::shared_ptr<IImageBackend> b) { m_imageBackend = std::move(b); }
    void setImageProviderRenderer(std::shared_ptr<IImageProviderRenderer> r) { m_imageProviderRenderer = std::move(r); }
    void setSvgRasterizer(std::shared_ptr<ISvgRasterizer> r) { m_svgRasterizer = std::move(r); }
    void setDynamicTextureGpu(std::shared_ptr<IDynamicTextureGpu> d) { m_dynamicTextureGpu = std::move(d); }
    void setRasterImageLoader(std::shared_ptr<IRasterImageLoader> r) { m_rasterImageLoader = std::move(r); }
    void setLog(std::shared_ptr<IUiLog> l) { m_log = std::move(l); }

    IUiSettings* settings() const { return m_settings.get(); }
    IUiFileIO* fileIO() const { return m_fileIO.get(); }
    IUiRenderer* renderer() const { return m_renderer.get(); }
    IUiPlatform* platform() const { return m_platform.get(); }
    windowmanager::IWindowCallbackManager* windowCallbackManager() const { return m_windowCallbackManager; }
    IGlyphManager* glyphManager() const { return m_glyphManager.get(); }
    IByteImageGpu* byteImageGpu() const { return m_byteImageGpu.get(); }
    IImageBackend* imageBackend() const { return m_imageBackend.get(); }
    IImageProviderRenderer* imageProviderRenderer() const { return m_imageProviderRenderer.get(); }
    ISvgRasterizer* svgRasterizer() const { return m_svgRasterizer.get(); }
    IDynamicTextureGpu* dynamicTextureGpu() const { return m_dynamicTextureGpu.get(); }
    IRasterImageLoader* rasterImageLoader() const { return m_rasterImageLoader.get(); }
    IUiLog* log() const { return m_log.get(); }

    bool isInitialized() const
    {
        return m_settings && m_fileIO && m_renderer && m_platform;
    }

    void reset()
    {
        m_log.reset();
        m_rasterImageLoader.reset();
        m_dynamicTextureGpu.reset();
        m_svgRasterizer.reset();
        m_imageProviderRenderer.reset();
        m_imageBackend.reset();
        m_byteImageGpu.reset();
        m_glyphManager.reset();
        m_windowCallbackManager = nullptr;
        m_platform.reset();
        m_renderer.reset();
        m_fileIO.reset();
        m_settings.reset();
    }

private:
    PlatformRegistry() = default;
    ~PlatformRegistry() = default;
    PlatformRegistry(const PlatformRegistry&) = delete;
    PlatformRegistry& operator=(const PlatformRegistry&) = delete;

    std::shared_ptr<IUiSettings> m_settings;
    std::shared_ptr<IUiFileIO> m_fileIO;
    std::shared_ptr<IUiRenderer> m_renderer;
    std::shared_ptr<IUiPlatform> m_platform;
    windowmanager::IWindowCallbackManager* m_windowCallbackManager = nullptr;
    std::shared_ptr<IByteImageGpu> m_byteImageGpu;
    std::shared_ptr<IGlyphManager> m_glyphManager;
    std::shared_ptr<IImageBackend> m_imageBackend;
    std::shared_ptr<IImageProviderRenderer> m_imageProviderRenderer;
    std::shared_ptr<IDynamicTextureGpu> m_dynamicTextureGpu;
    std::shared_ptr<ISvgRasterizer> m_svgRasterizer;
    std::shared_ptr<IRasterImageLoader> m_rasterImageLoader;
    std::shared_ptr<IUiLog> m_log;
};

} // namespace ui
} // namespace omni
