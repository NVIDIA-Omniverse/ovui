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

#include <omni/ui/Types.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace omni {
namespace ui {

/// RAII cancellation token for deferred operations and persistent observers.
/// Releasing (resetting) the handle cancels the associated operation.
using DeferHandle = std::shared_ptr<void>;

/// Unique identifier for an OS window or virtual window managed by the platform.
using WindowId = uint32_t;

/// Sentinel value for an invalid window.
constexpr WindowId kInvalidWindowId = 0;

/// Mouse button identifiers for input injection.
enum class MouseButton : uint32_t
{
    eLeft = 0,
    eRight = 1,
    eMiddle = 2,
};

/// Abstract platform interface absorbing IAppWindow, IAppWindowFactory,
/// IWindowCallbackManager, IEventDispatcher, and IInput.
///
/// In Kit mode, KitPlatformAdapter wraps the five underlying Kit interfaces.
/// In standalone mode, GLFW provides the implementation.
///
/// ~45 virtual methods covering: window lifecycle, window state, DPI/scaling,
/// cursor control, monitor info, clipboard, input injection, deferred operations,
/// run loop tick, busy state, and framebuffer texture access.
class IUiPlatform
{
public:
    virtual ~IUiPlatform() = default;

    // -- Window lifecycle ---------------------------------------------------

    /// Create the primary OS window. In V1 only one OS window is supported.
    /// Returns the window identifier.
    virtual WindowId createWindow(const char* title, int width, int height) = 0;

    /// Destroy an OS window and release all associated resources.
    virtual void destroyWindow(WindowId id) = 0;

    /// Create a virtual (off-screen) window backed by an FBO / render target.
    /// Used by SceneView for render-to-texture.
    virtual WindowId createVirtualWindow(int width, int height) = 0;

    /// Destroy a virtual window.
    virtual void destroyVirtualWindow(WindowId id) = 0;

    /// Resize a virtual window's backing framebuffer.
    virtual void resizeVirtualWindow(WindowId id, int width, int height) = 0;

    // -- Window state -------------------------------------------------------

    /// Get the content area size of the given window (excluding title bar / borders).
    virtual void getWindowSize(WindowId id, int* width, int* height) = 0;

    /// Set the content area size of the given window.
    virtual void setWindowSize(WindowId id, int width, int height) = 0;

    /// Get the window position in screen coordinates.
    virtual void getWindowPosition(WindowId id, int* x, int* y) = 0;

    /// Set the window position in screen coordinates.
    virtual void setWindowPosition(WindowId id, int x, int y) = 0;

    /// Get the window title.
    virtual std::string getWindowTitle(WindowId id) = 0;

    /// Set the window title.
    virtual void setWindowTitle(WindowId id, const char* title) = 0;

    /// Query whether the window is fullscreen.
    virtual bool isFullscreen(WindowId id) = 0;

    /// Enter or leave fullscreen mode.
    virtual void setFullscreen(WindowId id, bool fullscreen) = 0;

    /// Query whether the window is maximized.
    virtual bool isMaximized(WindowId id) = 0;

    /// Maximize or restore the window.
    virtual void setMaximized(WindowId id, bool maximized) = 0;

    /// Query whether the window currently has input focus.
    virtual bool isFocused(WindowId id) = 0;

    /// Request input focus for the window.
    virtual void setFocused(WindowId id) = 0;

    /// Query whether the window is visible (not hidden / minimized).
    virtual bool isVisible(WindowId id) = 0;

    /// Show or hide the window.
    virtual void setVisible(WindowId id, bool visible) = 0;

    /// Query whether the window has the "floating" (always-on-top) flag.
    virtual bool isFloating(WindowId id) = 0;

    /// Set the floating (always-on-top) flag.
    virtual void setFloating(WindowId id, bool floating) = 0;

    /// Set the window icon from RGBA pixel data.
    virtual void setWindowIcon(WindowId id, const uint8_t* pixels, int width, int height) = 0;

    /// Request the window to close (the close may be deferred or vetoed).
    virtual void requestClose(WindowId id) = 0;

    // -- DPI and scaling ----------------------------------------------------

    /// Return the effective DPI scale for the given window.
    /// This accounts for OS content scale and the DPI override setting,
    /// but does NOT include the user's UI scale multiplier.
    virtual float getDpiScale(WindowId id) = 0;

    /// Return the OS content scale factor (e.g. 2.0 on a Retina display).
    virtual float getContentScale(WindowId id) = 0;

    // -- Cursor control -----------------------------------------------------

    /// Set the mouse cursor shape. Uses ImGui cursor IDs.
    virtual void setCursorShape(int imguiCursorType) = 0;

    /// Show or hide the OS mouse cursor.
    virtual void setCursorVisible(bool visible) = 0;

    // -- Monitor info -------------------------------------------------------

    /// Return the number of connected monitors.
    virtual int getMonitorCount() = 0;

    /// Get the work area of a specific monitor (index 0-based).
    virtual void getMonitorWorkArea(int monitorIndex, int* x, int* y,
                                    int* width, int* height) = 0;

    // -- Clipboard ----------------------------------------------------------

    /// Get the current clipboard text content. Returns empty string if unavailable.
    virtual std::string getClipboard() = 0;

    /// Set the clipboard text content.
    virtual void setClipboard(const char* text) = 0;

    // -- Input injection (for virtual windows and testing) ------------------

    /// Inject a mouse position event into the specified window's input queue.
    virtual void injectMouseMove(WindowId id, float x, float y) = 0;

    /// Inject a mouse button event into the specified window's input queue.
    virtual void injectMouseButton(WindowId id, MouseButton button, bool pressed) = 0;

    /// Inject a mouse scroll event into the specified window's input queue.
    virtual void injectMouseScroll(WindowId id, float dx, float dy) = 0;

    /// Inject a key event into the specified window's input queue.
    /// @param imguiKey  ImGui key code (ImGuiKey_*).
    virtual void injectKeyEvent(WindowId id, int imguiKey, bool pressed,
                                KeyboardModifierFlags modifiers) = 0;

    /// Inject a character input event (for text entry).
    virtual void injectCharEvent(WindowId id, uint32_t codepoint) = 0;

    /// Block or unblock real OS input events. When blocked, only injected events
    /// are processed. Used by the test harness.
    virtual void setInputBlocking(bool blocked) = 0;

    // -- Deferred operations ------------------------------------------------

    /// Schedule a one-shot callback to execute after ImGui::Render() but before
    /// SwapBuffers in the current or next frame. Lower priority values execute first.
    /// The returned DeferHandle acts as an RAII cancellation token: releasing it
    /// cancels the callback if it hasn't fired yet.
    virtual DeferHandle deferToEndOfFrame(std::function<void()> callback,
                                          int32_t priority = 0) = 0;

    /// Register a persistent observer that fires every frame at end-of-frame
    /// until the returned DeferHandle is released.
    virtual DeferHandle observeEndOfFrame(std::function<void()> callback,
                                          int32_t priority = 0) = 0;

    // -- Run loop -----------------------------------------------------------

    /// Perform one frame tick: poll events, run deferred queue, present.
    /// Returns false if the application should exit.
    virtual bool tick() = 0;

    /// Query whether the main window has received a close request.
    virtual bool shouldClose() = 0;

    // -- Busy state ---------------------------------------------------------

    /// Signal that the application is busy (e.g. long computation). The backend
    /// may display a wait cursor or suppress timeout warnings.
    virtual void setBusy(bool busy) = 0;

    // -- Framebuffer access (virtual windows) -------------------------------

    /// Get the texture handle for a virtual window's framebuffer.
    /// Returns kInvalidTexture (from IUiRenderer.h) for non-virtual windows.
    virtual uint64_t getFramebufferTexture(WindowId id) = 0;

    // -- App window management (multi-window support) -----------------------
    // These methods support the Kit multi-OS-window model where UI windows
    // can be detached into separate OS windows. In standalone mode, most of
    // these return no-op defaults (single window, no detach).

    /// Get the handle for the default (main) application window.
    virtual AppWindowHandle getDefaultAppWindowHandle() = 0;

    /// Create a new detached OS window (for window tear-off).
    /// Returns nullptr if multi-window is not supported.
    virtual AppWindowHandle createDetachedAppWindow(const char* title,
                                                     int x, int y,
                                                     int w, int h) = 0;

    /// Whether the platform supports multiple OS windows (window detach/reattach).
    virtual bool isMultiWindowSupported() = 0;

    /// Whether the application is still running (safe to do deferred operations).
    virtual bool isAppRunning() = 0;

    /// Check if an app window is virtual (off-screen render target) vs. OS window.
    virtual bool isAppWindowVirtual(AppWindowHandle window) = 0;

    /// Get the OS-level cursor position relative to the given app window.
    virtual Int2 getAppWindowCursorPosition(AppWindowHandle window) = 0;

    /// Get the OS-level position of the given app window.
    virtual Int2 getAppWindowOsPosition(AppWindowHandle window) = 0;

    /// Set the OS-level position of the given app window.
    virtual void setAppWindowOsPosition(AppWindowHandle window, int x, int y) = 0;

    /// Resize the given app window.
    virtual void resizeAppWindow(AppWindowHandle window, int w, int h) = 0;

    /// Get the size of the given app window's content area.
    virtual void getAppWindowSize(AppWindowHandle window, int* width, int* height) = 0;

    /// Check if mouse input is blocked for the given app window.
    virtual bool isMouseInputBlocked(AppWindowHandle window) = 0;

    /// Get the cursor blink setting for the given app window.
    virtual bool getAppWindowCursorBlink(AppWindowHandle window) = 0;

    /// Schedule deferred destruction of the given app window (next frame).
    /// The DeferHandle cancels destruction if released before it fires.
    virtual DeferHandle deferDestroyAppWindow(AppWindowHandle window) = 0;

    /// Observe the close event of an app window. The callback fires when
    /// the OS window receives a close request. The DeferHandle cancels the
    /// observer when released.
    virtual DeferHandle observeAppWindowClose(AppWindowHandle window,
                                               std::function<void()> callback) = 0;

    /// Get the DPI scale for the given app window (without UI scale multiplier).
    virtual float getAppWindowDpiScale(AppWindowHandle window) = 0;

    // -- Window lifetime policy ---------------------------------------------

    /// Whether the platform needs the Workspace to hold strong (shared_ptr)
    /// references to omni::ui::Window objects to prevent premature destruction.
    ///
    /// In Kit the framework keeps Window shared_ptrs alive externally.
    /// In standalone the only reference may be a Python temporary, so the
    /// Workspace must hold a strong ref until the window is explicitly closed.
    virtual bool needsStrongWindowRefs() const = 0;
};

} // namespace ui
} // namespace omni
