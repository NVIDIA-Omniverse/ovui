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

#include "Api.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

enum class UnitType
{
    ePixel,
    ePercent,
    eFraction
};

/**
 * @brief OMNI.UI has several different units for expressing a length.
 *
 * Many widget properties take "Length" values, such as width, height, minWidth, minHeight, etc. Pixel is the absolute
 * length unit. Percent and Fraction are relative length units, and they specify a length relative to the parent length.
 * Relative length units are scaled with the parent.
 */
struct Length
{
    /**
     * @brief Construct Length
     */
    Length(float v, UnitType u) : value{ v }, unit{ u }
    {
    }

    ~Length() = default;

    bool operator==(const Length& b) const
    {
        return value == b.value && unit == b.unit;
    }

    bool operator!=(const Length& b) const
    {
        return !(b == *this);
    }

    /** Resolves the length value to a absolute value
     * @param absoluteFactor the unit multiplier if the value is Pixel
     * @param relativeFactor the unit multiplier if the value is Percent or Fraction
     * @param totalFractions the number of total fractions of the parent value if the value is Fraction.
     * @return the computed absolute value
     */
    float resolve(float absoluteFactor, float relativeFactor, float totalFractions) const;

    float value;
    UnitType unit;
};

/**
 * @brief Percent is the length in percents from the parent widget.
 */
struct Percent : public Length
{
    /**
     * @brief Construct Percent
     */
    explicit Percent(float v) : Length{ v, UnitType::ePercent }
    {
    }
    float resolve(float relativeFactor) const
    {
        return relativeFactor * (value / 100.0f);
    }
};

/**
 * @brief Pixel length is exact length in pixels.
 */
struct Pixel : public Length
{
    /**
     * @brief Construct Pixel
     */
    explicit Pixel(float v) : Length{ v, UnitType::ePixel }
    {
    }
    /** Resolves the length value to a absolute value
     * @param absoluteFactor the unit multiplier
     * @return the computed absolute value
     */
    float resolve(float absoluteFactor) const
    {
        return value * absoluteFactor;
    }
};

/**
 * @brief Fraction length is made to take the space of the parent widget, divides it up into a row of boxes, and makes
 * each child widget fill one box.
 */
struct Fraction : public Length
{
    /**
     * @brief Construct Fraction
     */
    explicit Fraction(float v) : Length{ v, UnitType::eFraction }
    {
    }
    /** Resolves the length value to a absolute value
     * @param relativeFactor the unit multiplier
     * @param totalFractions the number of total fractions of the parent value
     * @return the computed absolute value
     */
    float resolve(float relativeFactor, float totalFractions) const
    {
        return relativeFactor * (value / totalFractions);
    }
};

inline float Length::resolve(float absoluteFactor, float relativeFactor, float totalFractions) const
{
    if (unit == UnitType::ePixel)
        return Pixel(value).resolve(absoluteFactor);
    if (unit == UnitType::ePercent)
        return Percent(value).resolve(relativeFactor);
    return Fraction(value).resolve(relativeFactor, totalFractions);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
