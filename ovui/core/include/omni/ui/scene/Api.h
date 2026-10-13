/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#ifdef _WIN32
#    define OMNIUI_SCENE_EXPORT __declspec(dllexport)
#    define OMNIUI_SCENE_IMPORT __declspec(dllimport)
#    define OMNIUI_SCENE_CLASS_EXPORT
#else
#    define OMNIUI_SCENE_EXPORT __attribute__((visibility("default")))
#    define OMNIUI_SCENE_IMPORT
#    define OMNIUI_SCENE_CLASS_EXPORT __attribute__((visibility("default")))
#endif

#if defined(OMNIUI_SCENE_STATIC)
#    define OMNIUI_SCENE_API
#    define OMNIUI_SCENE_CLASS_API
#else
#    if defined(OMNIUI_SCENE_EXPORTS)
#        define OMNIUI_SCENE_API OMNIUI_SCENE_EXPORT
#        define OMNIUI_SCENE_CLASS_API OMNIUI_SCENE_CLASS_EXPORT
#    else
#        define OMNIUI_SCENE_API OMNIUI_SCENE_IMPORT
#        define OMNIUI_SCENE_CLASS_API
#    endif
#endif

#define OMNIUI_SCENE_NS omni::ui::scene
#define OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE using namespace OMNIUI_SCENE_NS;
#define OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE                                                                              \
    namespace omni                                                                                                     \
    {                                                                                                                  \
    namespace ui                                                                                                       \
    {                                                                                                                  \
    namespace scene                                                                                                    \
    {
#define OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE                                                                             \
    }                                                                                                                  \
    }                                                                                                                  \
    }
