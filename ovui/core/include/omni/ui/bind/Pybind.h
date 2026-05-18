/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#ifdef _MSC_VER
// WAR Pybind11 issue with VS2019+: https://github.com/pybind/pybind11/issues/3459
// Also: https://github.com/microsoft/onnxruntime/issues/9735
#include <corecrt.h>
#endif

#include <pybind11/functional.h>
#include <pybind11/pybind11.h>
