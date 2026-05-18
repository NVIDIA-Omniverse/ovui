/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_Length                                                                                       \
    "OMNI.UI has several different units for expressing a length.\n"                                                   \
    "Many widget properties take \"Length\" values, such as width, height, minWidth, minHeight, etc. Pixel is the absolute length unit. Percent and Fraction are relative length units, and they specify a length relative to the parent length. Relative length units are scaled with the parent.\n"


#define OMNIUI_PYBIND_DOC_Length_Length "Construct Length.\n"


#define OMNIUI_PYBIND_DOC_Length_resolve                                                                               \
    "Resolves the length value to a absolute value\n"                                                                  \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `absoluteFactor :`\n"                                                                                         \
    "        the unit multiplier if the value is Pixel\n"                                                              \
    "\n"                                                                                                               \
    "    `relativeFactor :`\n"                                                                                         \
    "        the unit multiplier if the value is Percent or Fraction\n"                                                \
    "\n"                                                                                                               \
    "    `totalFractions :`\n"                                                                                         \
    "        the number of total fractions of the parent value if the value is Fraction.\n"                            \
    "the computed absolute value\n"
