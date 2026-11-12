/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Asynchronous reads of the standalone file IO.
 *
 *   - a read that is still running when the file IO is destroyed must finish
 *     before the destructor returns, so no read outlives the application;
 *   - a read that fails must report the file and the cause.
 *
 * The file IO source is compiled into this test. No platform is registered,
 * so the read delivers its callback on the reading thread.
 */

#include "../../standalone/src/StandaloneFileIO.h"

#include <omni/ui/platform/IUiLog.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <system_error>
#include <thread>
#ifndef _WIN32
#include <dlfcn.h>
#include <pthread.h>
#include <sys/wait.h>
#include <unistd.h>
#endif
#include <vector>

#ifndef _WIN32
namespace
{
// When set, let a newly created thread run before pthread_create returns to its
// caller, a legal scheduling order. This makes the reader start-race case
// deterministic: the callback can free the reader before the caller records it.
std::atomic<bool> g_delayThreadStart{ false };
}

extern "C" int pthread_create(pthread_t* id, const pthread_attr_t* attrs,
                              void* (*entry)(void*), void* arg)
{
    using Create = int (*)(pthread_t*, const pthread_attr_t*, void* (*)(void*), void*);
    static Create real = reinterpret_cast<Create>(dlsym(RTLD_NEXT, "pthread_create"));
    const int result = real(id, attrs, entry, arg);
    if (result == 0 && g_delayThreadStart.load())
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return result;
}
#endif

using namespace omni::ui;
using omni::ui::standalone::StandaloneFileIO;

namespace
{

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

// Collects every message so a case can check what a failure reported.
struct RecordingLog : IUiLog
{
    std::mutex mutex;
    std::vector<std::string> messages;

    void record(const char* fmt, va_list args)
    {
        char text[1024];
        vsnprintf(text, sizeof(text), fmt, args);
        std::lock_guard<std::mutex> lock(mutex);
        messages.emplace_back(text);
    }
    void logError(const char* fmt, va_list args) override { record(fmt, args); }
    void logWarn(const char* fmt, va_list args) override { record(fmt, args); }
    void logInfo(const char* fmt, va_list args) override { record(fmt, args); }
};

template <typename Condition>
bool waitFor(Condition condition)
{
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (!condition())
    {
        if (std::chrono::steady_clock::now() > deadline)
            return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return true;
}

void caseDestructionWaitsForARunningRead(const std::string& path)
{
    beginCase("destroying the file IO waits for a running read");

    struct State
    {
        std::atomic<bool> started{ false };
        std::atomic<bool> finished{ false };
        size_t size = 0;
    };
    auto state = std::make_shared<State>();
    {
        StandaloneFileIO fileIO;
        fileIO.readFileAsync(path.c_str(), [state](std::vector<uint8_t> data) {
            state->started = true;
            // Keep the read running while the file IO is destroyed.
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            state->size = data.size();
            state->finished = true;
        });
        check(waitFor([&]() { return state->started.load(); }), "the read never delivered its callback");
    }
    const bool finishedAtDestruction = state->finished.load();
    check(finishedAtDestruction, "the read was still running after the file IO was destroyed");

    waitFor([&]() { return state->finished.load(); });
    check(state->size == 4, "the read delivered " + std::to_string(state->size) + " bytes, expected 4");
    endCase();
}

void caseFailedReadReportsTheCause(const std::string& missingPath, RecordingLog& log)
{
    beginCase("a failed read reports the file and the cause");

    auto delivered = std::make_shared<std::atomic<bool>>(false);
    {
        StandaloneFileIO fileIO;
        fileIO.readFileAsync(missingPath.c_str(), [delivered](std::vector<uint8_t> data) {
            check(data.empty(), "a missing file delivered data");
            *delivered = true;
        });
        check(waitFor([&]() { return delivered->load(); }), "the read never delivered its callback");
    }

    // Filesystem errors use the platform's category: on Windows the missing
    // file message differs from the generic errno message.
    std::error_code missingError;
    check(!std::filesystem::is_regular_file(missingPath, missingError), "the missing path is a regular file");
    check(missingError == std::errc::no_such_file_or_directory, "the missing path did not report file-not-found");
    const std::string cause = missingError.message();
    bool reported = false;
    {
        std::lock_guard<std::mutex> lock(log.mutex);
        for (const std::string& message : log.messages)
        {
            if (message.find(missingPath) != std::string::npos && message.find(cause) != std::string::npos)
                reported = true;
        }
    }
    check(reported, "no message names '" + missingPath + "' and the cause '" + cause + "'");
    endCase();
}

void caseCallbackDestroyingTheFileIODoesNotDeadlock(const std::string& path)
{
    beginCase("a callback that destroys the file IO does not deadlock");

    // No platform is registered, so the callback runs on the read thread. It
    // destroys the file IO there, so the destructor runs on the read's own
    // thread. The destructor must not wait for that thread.
    auto destroyed = std::make_shared<std::atomic<bool>>(false);
    auto* fileIO = new StandaloneFileIO();
    fileIO->readFileAsync(path.c_str(), [fileIO, destroyed](std::vector<uint8_t>) {
        delete fileIO;
        *destroyed = true;
    });

    check(waitFor([&]() { return destroyed->load(); }),
          "the file IO was never destroyed; the destructor may have deadlocked");
    endCase();
}

#ifndef _WIN32
void caseUnfinishedReadReportsAndExitsNonZero(const std::string& path)
{
    beginCase("an unfinished read at shutdown reports it and exits non-zero");

    // The exit path ends the process, so run it in a child and read its exit
    // status and its message. A callback that does not return stands in for a
    // read that passes its shutdown time limit.
    const std::string report = std::filesystem::temp_directory_path() / "ovui_file_io_timeout_report.txt";
    std::remove(report.c_str());

    const pid_t pid = fork();
    if (pid == 0)
    {
        FILE* err = freopen(report.c_str(), "w", stderr);
        (void)err;
        auto fileIO = std::make_unique<StandaloneFileIO>();
        std::atomic<bool> entered{ false };
        fileIO->readFileAsync(path.c_str(), [&entered](std::vector<uint8_t>) {
            entered.store(true);
            while (true)
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
        });
        while (!entered.load())
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        fileIO.reset();  // destructor waits the limit, then should exit(70)
        _exit(0);  // reached only if the destructor wrongly returned
    }

    int status = 0;
    waitpid(pid, &status, 0);
    check(WIFEXITED(status), "the child did not exit normally");
    check(WIFEXITED(status) && WEXITSTATUS(status) == 70,
          "the child exit status was " + std::to_string(WEXITSTATUS(status)) + ", expected 70");

    std::ifstream reportFile(report);
    std::string text((std::istreambuf_iterator<char>(reportFile)), std::istreambuf_iterator<char>());
    check(text.find("shutdown") != std::string::npos && text.find("exiting") != std::string::npos,
          "the child did not report the unfinished read before exiting");
    check(text.find(path) != std::string::npos,
          "the shutdown report did not name the timed-out read '" + path + "'");
    std::remove(report.c_str());
    endCase();
}
#endif

void caseAThrowingCallbackDoesNotAbort(const std::string& path)
{
    beginCase("a result handler that raises does not crash the process");

    // The callback runs on the read thread. If it raises and the thread does
    // not catch it, the process aborts. The read must catch and report it.
    auto ran = std::make_shared<std::atomic<bool>>(false);
    {
        StandaloneFileIO fileIO;
        fileIO.readFileAsync(path.c_str(), [ran](std::vector<uint8_t>) {
            ran->store(true);
            throw std::runtime_error("the result handler failed");
        });
        check(waitFor([&]() { return ran->load(); }), "the callback never ran");
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    // Reaching here means the raising callback did not abort the process.
    check(true, "");
    endCase();
}

void caseManyCallbackDestructionsAreRaceFree(const std::string& path)
{
    beginCase("repeated callback destruction of the file IO is free of races");

    // Each read's callback destroys its file IO on the read thread. The read
    // must be recorded before its callback runs, so this does not race with the
    // list bookkeeping. The read thread is let run before readFileAsync returns
    // (a legal order), so without the fix the callback frees the object before
    // the caller records it; AddressSanitizer then reports a use after free.
#ifndef _WIN32
    g_delayThreadStart.store(true);
#endif
    for (int i = 0; i < 20; ++i)
    {
        auto destroyed = std::make_shared<std::atomic<bool>>(false);
        auto* fileIO = new StandaloneFileIO();
        fileIO->readFileAsync(path.c_str(), [fileIO, destroyed](std::vector<uint8_t>) {
            delete fileIO;
            destroyed->store(true);
        });
        check(waitFor([&]() { return destroyed->load(); }),
              "a callback never finished destroying the file IO");
    }
#ifndef _WIN32
    g_delayThreadStart.store(false);
#endif
    endCase();
}

void caseReadingADirectoryReportsAndReturnsEmpty(const std::string& dirPath, RecordingLog& log)
{
    beginCase("reading a directory reports the cause and returns no data");

    auto delivered = std::make_shared<std::atomic<bool>>(false);
    {
        StandaloneFileIO fileIO;
        fileIO.readFileAsync(dirPath.c_str(), [delivered](std::vector<uint8_t> data) {
            check(data.empty(), "a directory delivered data");
            *delivered = true;
        });
        check(waitFor([&]() { return delivered->load(); }), "the read never delivered its callback");
    }

    bool reported = false;
    {
        std::lock_guard<std::mutex> lock(log.mutex);
        for (const std::string& message : log.messages)
        {
            if (message.find(dirPath) != std::string::npos)
                reported = true;
        }
    }
    check(reported, "no message names the directory '" + dirPath + "'");
    endCase();
}

void caseAFailedReadStillDeliversAnEmptyResult(const std::string& path)
{
    beginCase("a read that fails still delivers an empty result");

    // Arm the test-only seam so the next read throws before it touches the file.
    // This drives the read-failure path deterministically, without changing the
    // product reader and without a huge allocation. A single try block would
    // drop the callback on this throw; the split try blocks must still deliver
    // the empty result.
    standalone::failNextReadForTest();

    auto delivered = std::make_shared<std::atomic<bool>>(false);
    auto size = std::make_shared<std::atomic<size_t>>(SIZE_MAX);
    {
        StandaloneFileIO fileIO;
        fileIO.readFileAsync(path.c_str(), [delivered, size](std::vector<uint8_t> data) {
            size->store(data.size());
            *delivered = true;
        });
        check(waitFor([&]() { return delivered->load(); }), "a failed read never delivered its callback");
    }
    check(delivered->load(), "a failed read did not deliver a result");
    check(size->load() == 0, "a failed read delivered " + std::to_string(size->load()) + " bytes, expected 0");
    endCase();
}

} // namespace

int main()
{
    const std::filesystem::path dir = std::filesystem::temp_directory_path() / "ovui_standalone_file_io_test";
    std::filesystem::create_directories(dir);
    const std::filesystem::path file = dir / "data.bin";
    {
        std::ofstream out(file, std::ios::binary);
        out.write("ovui", 4);
    }

    auto log = std::make_shared<RecordingLog>();
    PlatformRegistry::instance().setLog(log);

    caseDestructionWaitsForARunningRead(file.string());
    caseFailedReadReportsTheCause((dir / "missing.bin").string(), *log);
    caseCallbackDestroyingTheFileIODoesNotDeadlock(file.string());
    caseAThrowingCallbackDoesNotAbort(file.string());
    caseManyCallbackDestructionsAreRaceFree(file.string());
#ifndef _WIN32
    caseUnfinishedReadReportsAndExitsNonZero(file.string());
#endif
    caseReadingADirectoryReportsAndReturnsEmpty(dir.string(), *log);
    caseAFailedReadStillDeliversAnEmptyResult(file.string());

    PlatformRegistry::instance().setLog(nullptr);
    std::filesystem::remove_all(dir);

    std::cout << "\n" << (g_totalCases - g_failedCases) << "/" << g_totalCases << " cases passed" << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
