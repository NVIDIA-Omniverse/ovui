// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// The first-interaction callback of Workspace can unregister or replace itself while it runs.
// The callback and its captures must stay alive until it returns; the change applies to the next call.

#include <omni/ui/Workspace.h>

#include <iostream>
#include <memory>
#include <string>

using namespace omni::ui;

namespace
{
int g_failures = 0;

void check(bool ok, const char* what)
{
    std::cout << (ok ? "PASS " : "FAIL ") << what << std::endl;
    if (!ok)
    {
        ++g_failures;
    }
}

void caseUnregisterInsideTheCallback()
{
    auto resource = std::make_shared<int>(7);
    std::weak_ptr<int> watch = resource;
    int calls = 0;
    bool aliveAfterUnregister = false;
    Workspace::setWindowFirstInteractionCallback(
        [resource, &watch, &calls, &aliveAfterUnregister](const std::string&, const std::string&)
        {
            ++calls;
            Workspace::setWindowFirstInteractionCallback(nullptr);
            aliveAfterUnregister = !watch.expired() && *resource == 7;
        });
    resource.reset();
    Workspace::onWindowFirstInteraction("Window", "owner");
    check(calls == 1, "unregister: the callback ran once");
    check(aliveAfterUnregister, "unregister: the captures stay alive until the callback returns");
    check(watch.expired(), "unregister: the captures are released after the callback returns");
    Workspace::onWindowFirstInteraction("Window", "owner");
    check(calls == 1, "unregister: the next interaction calls nothing");
}

void caseReplaceInsideTheCallback()
{
    auto resource = std::make_shared<int>(9);
    std::weak_ptr<int> watch = resource;
    int firstCalls = 0;
    int secondCalls = 0;
    bool aliveAfterReplace = false;
    Workspace::setWindowFirstInteractionCallback(
        [resource, &watch, &firstCalls, &secondCalls, &aliveAfterReplace](const std::string&, const std::string&)
        {
            ++firstCalls;
            Workspace::setWindowFirstInteractionCallback(
                [&secondCalls](const std::string&, const std::string&) { ++secondCalls; });
            aliveAfterReplace = !watch.expired() && *resource == 9;
        });
    resource.reset();
    Workspace::onWindowFirstInteraction("Window", "owner");
    check(firstCalls == 1 && secondCalls == 0, "replace: only the first callback ran");
    check(aliveAfterReplace, "replace: the captures stay alive until the callback returns");
    Workspace::onWindowFirstInteraction("Window", "owner");
    check(firstCalls == 1 && secondCalls == 1, "replace: the next interaction calls the new callback");
    Workspace::setWindowFirstInteractionCallback(nullptr);
}
} // namespace

int main()
{
    caseUnregisterInsideTheCallback();
    caseReplaceInsideTheCallback();
    std::cout << (g_failures == 0 ? "ALL PASS" : "SOME FAILED") << std::endl;
    return g_failures == 0 ? 0 : 1;
}
