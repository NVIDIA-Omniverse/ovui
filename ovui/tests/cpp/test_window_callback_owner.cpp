/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * A ui::Window and its window callback when an app window has no window set.
 *
 * A fake IWindowCallbackManager replaces the Kit window manager. Like the Kit
 * one, it can detach a window set from its app window: the set keeps its
 * callbacks, but a lookup by the app window finds no set. This is what happens
 * when Kit closes a detached OS window. No GPU, window or ImGui frame is used.
 * There is no IUiPlatform, so the main app window is the null handle.
 *
 * What is checked:
 *   - moveToAppWindow() to an app window without a set leaves the callback in
 *     its set, and the Window keeps the app window of that set;
 *   - moveToMainOSWindow() (through setVisible(false)) when the main app window
 *     has no set does the same;
 *   - removeAppWindowCallback() removes a callback from its set after the set
 *     lost its app window, directly and through Window::setActive(false);
 *   - a draw of a Window whose app window has no set gives the Window back the
 *     app window of its callback;
 *   - with a manager like the standalone one (callbacks report no app window,
 *     every lookup finds the one set) and a non-null main app window, a move
 *     through the null app window back to main, a hide and a show, and a draw
 *     keep the Window in the main app window.
 *
 * Each case runs to the end and reports alone.
 */

#include <omni/ui/Window.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>
#include <omni/ui/platform/IUiPlatform.h>
#include <imgui/imgui.h>

#include <algorithm>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

using namespace omni::ui;
namespace wm = omni::ui::windowmanager;

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
    for (const auto& f : g_caseFailures)
        std::cout << "     - " << f << std::endl;
}

std::string name(AppWindowHandle handle)
{
    if (!handle)
        return "main (null)";
    std::ostringstream s;
    s << handle;
    return s.str();
}

struct FakeSet
{
    AppWindowHandle appWindow = nullptr;
    bool attached = false; // false: a lookup by appWindow does not find this set
    std::vector<wm::IWindowCallback*> callbacks;
};

wm::WindowSet* asSet(FakeSet* set)
{
    return reinterpret_cast<wm::WindowSet*>(set);
}

FakeSet* asFake(wm::WindowSet* set)
{
    return reinterpret_cast<FakeSet*>(set);
}

struct FakeCallback : wm::IWindowCallback
{
    std::string title;
    wm::IEventListener* listener = nullptr;
    FakeSet* owner = nullptr;

    FakeCallback(const char* t, wm::IEventListener* l) : title(t ? t : ""), listener(l)
    {
        if (listener)
            listener->addRef();
    }
    ~FakeCallback() override
    {
        if (listener)
            listener->release();
    }

    const char* getTitle() override { return title.c_str(); }
    uint32_t getWidth() override { return 0; }
    uint32_t getHeight() override { return 0; }
    wm::DockPreference getDockPreference() override { return wm::DockPreference::eDisabled; }
    wm::WindowSet* getWindowSet() override { return asSet(owner); }
    // As in Kit: the app window of the set that owns the callback.
    AppWindowHandle getAppWindow() override { return owner && owner->attached ? owner->appWindow : nullptr; }
    void draw(float elapsedTime) override
    {
        if (listener)
            listener->onDraw(elapsedTime);
    }
};

struct FakeManager : wm::IWindowCallbackManager
{
    std::vector<std::unique_ptr<FakeSet>> sets;

    FakeManager()
    {
        sets.push_back(std::make_unique<FakeSet>());
        sets.back()->attached = true; // the default set belongs to the main app window
    }

    ~FakeManager()
    {
        while (!sets.empty())
            destroyWindowSet(asSet(sets.back().get()));
    }

    FakeSet* defaultSet() { return sets.front().get(); }

    // What Kit does when it closes a detached OS window: the lookup association goes away and
    // the set keeps its callbacks until they are removed.
    void detach(wm::WindowSet* set) { asFake(set)->attached = false; }

    wm::IWindowCallback* createWindowCallbackPtr(
        const char* title, uint32_t width, uint32_t height, wm::DockPreference dock, wm::IEventListener* listener) override
    {
        return createWindowSetCallbackPtr(getDefaultWindowSet(), title, width, height, dock, listener);
    }

    void removeWindowCallback(wm::IWindowCallback* callback) override
    {
        if (callback && callback->getWindowSet())
            removeWindowSetCallback(callback->getWindowSet(), callback);
    }

    size_t getWindowCallbackCount() override
    {
        size_t count = 0;
        for (auto& set : sets)
            count += set->callbacks.size();
        return count;
    }

    wm::IWindowCallback* getWindowCallbackAt(size_t index) override
    {
        for (auto& set : sets)
        {
            if (index < set->callbacks.size())
                return set->callbacks[index];
            index -= set->callbacks.size();
        }
        return nullptr;
    }

    wm::WindowSet* createWindowSet() override
    {
        sets.push_back(std::make_unique<FakeSet>());
        return asSet(sets.back().get());
    }

    void destroyWindowSet(wm::WindowSet* windowSet) override
    {
        FakeSet* set = asFake(windowSet);
        while (!set->callbacks.empty())
            removeWindowSetCallback(windowSet, set->callbacks.back());
        sets.erase(std::remove_if(sets.begin(), sets.end(), [set](auto& s) { return s.get() == set; }), sets.end());
    }

    wm::WindowSet* getDefaultWindowSet() override { return asSet(defaultSet()); }

    void attachWindowSetToAppWindow(wm::WindowSet* windowSet, AppWindowHandle appWindow) override
    {
        asFake(windowSet)->appWindow = appWindow;
        asFake(windowSet)->attached = true;
    }

    wm::WindowSet* getWindowSetByAppWindow(AppWindowHandle appWindow) override
    {
        for (auto& set : sets)
        {
            if (set->attached && set->appWindow == appWindow)
                return asSet(set.get());
        }
        return nullptr;
    }

    AppWindowHandle getAppWindowFromWindowSet(wm::WindowSet* windowSet) override
    {
        FakeSet* set = asFake(windowSet);
        return set && set->attached ? set->appWindow : nullptr;
    }

    size_t getWindowSetCount() override { return sets.size(); }
    wm::WindowSet* getWindowSetAt(size_t index) override
    {
        return index < sets.size() ? asSet(sets[index].get()) : nullptr;
    }

    wm::IWindowCallback* createWindowSetCallbackPtr(wm::WindowSet* windowSet,
                                                    const char* title,
                                                    uint32_t,
                                                    uint32_t,
                                                    wm::DockPreference,
                                                    wm::IEventListener* listener) override
    {
        if (!windowSet)
            return nullptr;
        auto* callback = new FakeCallback(title, listener); // the caller owns this reference
        addWindowSetCallback(windowSet, callback);
        return callback;
    }

    void addWindowSetCallback(wm::WindowSet* windowSet, wm::IWindowCallback* callback) override
    {
        if (!windowSet || !callback)
            return;
        callback->addRef(); // the set's reference
        asFake(windowSet)->callbacks.push_back(callback);
        static_cast<FakeCallback*>(callback)->owner = asFake(windowSet);
    }

    void removeWindowSetCallback(wm::WindowSet* windowSet, wm::IWindowCallback* callback) override
    {
        if (!windowSet || !callback)
            return;
        auto& list = asFake(windowSet)->callbacks;
        auto it = std::find(list.begin(), list.end(), callback);
        if (it == list.end())
            return;
        list.erase(it);
        auto* fake = static_cast<FakeCallback*>(callback);
        if (fake->owner == asFake(windowSet))
            fake->owner = nullptr;
        callback->release();
    }

    size_t getWindowSetCallbackCount(wm::WindowSet* windowSet) override
    {
        return windowSet ? asFake(windowSet)->callbacks.size() : 0;
    }

    wm::IWindowCallback* getWindowSetCallbackAt(wm::WindowSet* windowSet, size_t index) override
    {
        if (!windowSet || index >= asFake(windowSet)->callbacks.size())
            return nullptr;
        return asFake(windowSet)->callbacks[index];
    }
};

// Like the standalone callback: it reports no app window.
struct NullAppWindowCallback : FakeCallback
{
    using FakeCallback::FakeCallback;
    AppWindowHandle getAppWindow() override { return nullptr; }
};

// Like the standalone manager: one set, which a lookup by any app window finds.
struct StandaloneLikeManager : FakeManager
{
    wm::WindowSet* getWindowSetByAppWindow(AppWindowHandle) override { return getDefaultWindowSet(); }
    AppWindowHandle getAppWindowFromWindowSet(wm::WindowSet*) override { return nullptr; }

    wm::IWindowCallback* createWindowSetCallbackPtr(wm::WindowSet* windowSet,
                                                    const char* title,
                                                    uint32_t,
                                                    uint32_t,
                                                    wm::DockPreference,
                                                    wm::IEventListener* listener) override
    {
        if (!windowSet)
            return nullptr;
        auto* callback = new NullAppWindowCallback(title, listener); // the caller owns this reference
        addWindowSetCallback(windowSet, callback);
        return callback;
    }
};

// A platform with a non-null main app window and no other OS window, as standalone. It counts the
// requests for a new OS window.
struct MainWindowPlatform : IUiPlatform
{
    AppWindowHandle mainAppWindow;
    int newOsWindowRequests = 0;

    explicit MainWindowPlatform(AppWindowHandle main) : mainAppWindow(main) {}

    WindowId createWindow(const char*, int, int) override { return kInvalidWindowId; }
    void destroyWindow(WindowId) override {}
    WindowId createVirtualWindow(int, int) override { return kInvalidWindowId; }
    void destroyVirtualWindow(WindowId) override {}
    void resizeVirtualWindow(WindowId, int, int) override {}
    void getWindowSize(WindowId, int* width, int* height) override { *width = 1024; *height = 768; }
    void setWindowSize(WindowId, int, int) override {}
    void getWindowPosition(WindowId, int* x, int* y) override { *x = 0; *y = 0; }
    void setWindowPosition(WindowId, int, int) override {}
    std::string getWindowTitle(WindowId) override { return {}; }
    void setWindowTitle(WindowId, const char*) override {}
    bool isFullscreen(WindowId) override { return false; }
    void setFullscreen(WindowId, bool) override {}
    bool isMaximized(WindowId) override { return false; }
    void setMaximized(WindowId, bool) override {}
    bool isFocused(WindowId) override { return true; }
    void setFocused(WindowId) override {}
    bool isVisible(WindowId) override { return true; }
    void setVisible(WindowId, bool) override {}
    bool isFloating(WindowId) override { return false; }
    void setFloating(WindowId, bool) override {}
    void setWindowIcon(WindowId, const uint8_t*, int, int) override {}
    void requestClose(WindowId) override {}
    float getDpiScale(WindowId) override { return 1.0f; }
    float getContentScale(WindowId) override { return 1.0f; }
    void setCursorShape(int) override {}
    void setCursorVisible(bool) override {}
    int getMonitorCount() override { return 1; }
    void getMonitorWorkArea(int, int* x, int* y, int* width, int* height) override
    {
        *x = 0;
        *y = 0;
        *width = 1024;
        *height = 768;
    }
    std::string getClipboard() override { return {}; }
    void setClipboard(const char*) override {}
    void injectMouseMove(WindowId, float, float) override {}
    void injectMouseButton(WindowId, MouseButton, bool) override {}
    void injectMouseScroll(WindowId, float, float) override {}
    void injectKeyEvent(WindowId, int, bool, KeyboardModifierFlags) override {}
    void injectCharEvent(WindowId, uint32_t) override {}
    void setInputBlocking(bool) override {}
    DeferHandle deferToEndOfFrame(std::function<void()>, int32_t) override { return nullptr; }
    DeferHandle observeEndOfFrame(std::function<void()>, int32_t) override { return nullptr; }
    bool tick() override { return true; }
    bool shouldClose() override { return false; }
    void setBusy(bool) override {}
    uint64_t getFramebufferTexture(WindowId) override { return 0; }
    AppWindowHandle getDefaultAppWindowHandle() override { return mainAppWindow; }
    AppWindowHandle createDetachedAppWindow(const char*, int, int, int, int) override
    {
        ++newOsWindowRequests;
        return nullptr;
    }
    bool isMultiWindowSupported() override { return false; }
    bool isAppRunning() override { return false; }
    bool isAppWindowVirtual(AppWindowHandle) override { return false; }
    Int2 getAppWindowCursorPosition(AppWindowHandle) override { return {}; }
    Int2 getAppWindowOsPosition(AppWindowHandle) override { return {}; }
    void setAppWindowOsPosition(AppWindowHandle, int, int) override {}
    void resizeAppWindow(AppWindowHandle, int, int) override {}
    void getAppWindowSize(AppWindowHandle, int* width, int* height) override
    {
        *width = 1024;
        *height = 768;
    }
    bool isMouseInputBlocked(AppWindowHandle) override { return false; }
    bool getAppWindowCursorBlink(AppWindowHandle) override { return false; }
    DeferHandle deferDestroyAppWindow(AppWindowHandle) override { return nullptr; }
    DeferHandle observeAppWindowClose(AppWindowHandle, std::function<void()>) override { return nullptr; }
    float getAppWindowDpiScale(AppWindowHandle) override { return 1.0f; }
    bool needsStrongWindowRefs() const override { return false; }
    int nativeKeyCode(int) const override { return 0; }
};

// Two app windows. kDetached gets a set in some cases; kNoSet never has one.
AppWindowHandle const kDetached = reinterpret_cast<AppWindowHandle>(uintptr_t(0x1000));
AppWindowHandle const kNoSet = reinterpret_cast<AppWindowHandle>(uintptr_t(0x2000));

void moveToAppWindowWithoutSetKeepsOwner()
{
    beginCase("moveToAppWindow to an app window without a set keeps the app window of the callback");
    FakeManager manager;
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    {
        auto window = Window::create("Window callback owner A");
        wm::IWindowCallback* callback = window->getWindowCallback();
        check(callback && callback->getWindowSet() == manager.getDefaultWindowSet(),
              "setup: the callback is in the default set");

        window->moveToAppWindow(kNoSet);

        check(callback && callback->getWindowSet() == manager.getDefaultWindowSet(),
              "the failed move leaves the callback in the default set");
        check(window->getAppWindow() == nullptr,
              "Window::getAppWindow() is " + name(window->getAppWindow()) +
                  ", expected the app window of the callback's set: " + name(nullptr));
        window->destroy();
    }
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

void moveToMainWithoutSetKeepsOwner()
{
    beginCase("moveToMainOSWindow when the main app window has no set keeps the app window of the callback");
    FakeManager manager;
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    wm::WindowSet* detachedSet = manager.createWindowSet();
    manager.attachWindowSetToAppWindow(detachedSet, kDetached);
    {
        auto window = Window::create("Window callback owner B");
        window->moveToAppWindow(kDetached);
        wm::IWindowCallback* callback = window->getWindowCallback();
        check(window->getAppWindow() == kDetached && callback && callback->getWindowSet() == detachedSet,
              "setup: the window and its callback are in the detached app window");

        manager.detach(manager.getDefaultWindowSet()); // the main app window has no set now
        window->setVisible(false);            // a hidden detached window goes back to the main app window

        check(callback && callback->getWindowSet() == detachedSet,
              "the failed move leaves the callback in the detached set");
        check(window->getAppWindow() == kDetached,
              "Window::getAppWindow() is " + name(window->getAppWindow()) +
                  ", expected the app window of the callback's set: " + name(kDetached));

        manager.attachWindowSetToAppWindow(manager.getDefaultWindowSet(), nullptr);
        window->destroy();
    }
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

void removeAppWindowCallbackAfterDetach()
{
    beginCase("removeAppWindowCallback removes a callback after its set lost the app window");
    FakeManager manager;
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    wm::WindowSet* set = manager.createWindowSet();
    manager.attachWindowSetToAppWindow(set, kDetached);
    wm::IWindowCallbackPtr callback = wm::createWindowSetCallback(
        set, &manager, "Retiring callback", 64, 64, wm::DockPreference::eDisabled, [](float) {});
    check(callback && manager.getWindowSetCallbackCount(set) == 1, "setup: the set has the callback");

    manager.detach(set);
    manager.removeAppWindowCallback(kDetached, callback.get());

    check(manager.getWindowSetCallbackCount(set) == 0,
          "the set still has " + std::to_string(manager.getWindowSetCallbackCount(set)) +
              " callback(s) after removeAppWindowCallback, expected 0");
    check(callback->getWindowSet() == nullptr, "the callback still has an owner set after removeAppWindowCallback");

    // A second call, and a call after the set is gone, change nothing.
    manager.removeAppWindowCallback(kDetached, callback.get());
    manager.destroyWindowSet(set);
    manager.removeAppWindowCallback(nullptr, callback.get());
    check(callback->getWindowSet() == nullptr, "repeated removal: the callback has no owner set");
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

void setActiveFalseAfterDetach()
{
    beginCase("Window::setActive(false) removes the callback after its set lost the app window");
    FakeManager manager;
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    wm::WindowSet* set = manager.createWindowSet();
    manager.attachWindowSetToAppWindow(set, kDetached);
    {
        auto window = Window::create("Window callback owner C");
        window->moveToAppWindow(kDetached);
        check(manager.getWindowSetCallbackCount(set) == 1, "setup: the detached set has the window's callback");

        manager.detach(set); // Kit closed the OS window
        window->setActive(false);

        check(manager.getWindowSetCallbackCount(set) == 0,
              "the detached set still has " + std::to_string(manager.getWindowSetCallbackCount(set)) +
                  " callback(s) after setActive(false), expected 0");

        // The Window has no callback now; take it back to the main app window so that its
        // destructor does not try to move a callback that it does not have.
        window->notifyAppWindowChange(nullptr);
        window->destroy();
    }
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

void drawRestoresOwner()
{
    beginCase("a draw of a Window whose app window has no set restores the app window of the callback");
    FakeManager manager;
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    {
        auto window = Window::create("Window callback owner D");
        wm::IWindowCallback* callback = window->getWindowCallback();
        window->notifyAppWindowChange(kNoSet); // public call that can disagree with the callback

        callback->draw(0.0f);

        check(window->getAppWindow() == nullptr,
              "Window::getAppWindow() is " + name(window->getAppWindow()) + " after a draw, expected " +
                  name(nullptr));
        window->destroy();
    }
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

void standaloneMainWindowKept()
{
    beginCase("with callbacks that report no app window, moves through the null app window keep the main app window");
    AppWindowHandle const kMain = reinterpret_cast<AppWindowHandle>(uintptr_t(0x3000));
    auto text = [](AppWindowHandle handle) { return handle ? name(handle) : std::string("null"); };
    StandaloneLikeManager manager;
    auto platform = std::make_shared<MainWindowPlatform>(kMain);
    PlatformRegistry::instance().setWindowCallbackManager(&manager);
    PlatformRegistry::instance().setPlatform(platform);
    ImGuiContext* ctx = ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1024.0f, 768.0f);
    io.DeltaTime = 1.0f / 60.0f;
    io.BackendFlags |= ImGuiBackendFlags_RendererHasTextures; // there is no back end to upload the font atlas
    {
        auto first = Window::create("Standalone first"); // its callback is first in the set
        auto window = Window::create("Standalone subject");
        check(window->getAppWindow() == kMain, "setup: the window starts in the main app window");

        window->moveToAppWindow(nullptr);
        window->moveToAppWindow(kMain);
        check(window->getAppWindow() == kMain,
              "Window::getAppWindow() is " + text(window->getAppWindow()) +
                  " after a move to the null app window and back, expected " + text(kMain));

        window->moveToAppWindow(nullptr);
        window->setVisible(false); // a hidden window goes back to the main app window
        check(window->getAppWindow() == kMain,
              "Window::getAppWindow() is " + text(window->getAppWindow()) + " after a hide, expected " + text(kMain));
        window->setVisible(true);
        check(window->getAppWindow() == kMain,
              "Window::getAppWindow() is " + text(window->getAppWindow()) + " after a show, expected " + text(kMain));

        ImGui::NewFrame();
        window->getWindowCallback()->draw(0.0f);
        ImGui::Render();
        check(platform->newOsWindowRequests == 0,
              "a draw in the main app window asked for " + std::to_string(platform->newOsWindowRequests) +
                  " new OS window(s), expected 0");
        check(window->getAppWindow() == kMain,
              "Window::getAppWindow() is " + text(window->getAppWindow()) + " after a draw, expected " + text(kMain));

        window->destroy();
        first->destroy();
    }
    ImGui::DestroyContext(ctx);
    PlatformRegistry::instance().setPlatform(nullptr);
    PlatformRegistry::instance().setWindowCallbackManager(nullptr);
    endCase();
}

} // namespace

int main()
{
    moveToAppWindowWithoutSetKeepsOwner();
    moveToMainWithoutSetKeepsOwner();
    removeAppWindowCallbackAfterDetach();
    setActiveFalseAfterDetach();
    drawRestoresOwner();
    standaloneMainWindowKept();
    std::cout << (g_failedCases == 0 ? "ALL PASS" : "SOME FAILED") << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
