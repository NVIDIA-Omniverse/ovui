/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#ifdef _WIN32
#    define OMNIUI_EXPORT __declspec(dllexport)
#    define OMNIUI_IMPORT __declspec(dllimport)
#    define OMNIUI_CLASS_EXPORT
#else
#    define OMNIUI_EXPORT __attribute__((visibility("default")))
#    define OMNIUI_IMPORT
#    define OMNIUI_CLASS_EXPORT __attribute__((visibility("default")))
#endif

#if defined(OMNIUI_STATIC)
#    define OMNIUI_API
#    define OMNIUI_CLASS_API
#else
#    if defined(OMNIUI_EXPORTS)
#        define OMNIUI_API OMNIUI_EXPORT
#        define OMNIUI_CLASS_API OMNIUI_CLASS_EXPORT
#    else
#        define OMNIUI_API OMNIUI_IMPORT
#        define OMNIUI_CLASS_API
#    endif
#endif

#define OMNIUI_NS omni::ui
#define OMNIUI_NAMESPACE_USING_DIRECTIVE using namespace OMNIUI_NS;
#define OMNIUI_NAMESPACE_OPEN_SCOPE                                                                                    \
    namespace omni                                                                                                     \
    {                                                                                                                  \
    namespace ui                                                                                                       \
    {
#define OMNIUI_NAMESPACE_CLOSE_SCOPE                                                                                   \
    }                                                                                                                  \
    }
