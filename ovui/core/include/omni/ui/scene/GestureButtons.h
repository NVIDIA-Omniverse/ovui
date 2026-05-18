/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/scene/Api.h>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief A class for getting and setting mouse button info for a gesture
 */
class OMNIUI_SCENE_CLASS_API GestureButtons
{
public:
    enum ButtonFlags : uint32_t {
        // Max out at 16 possible buttons, to avoid checking 16->28
        //
        kMaxNumButtons = 16,

        kMultiButtonFlag = (1 << 29),
        // Bit reserved for state tracking (currently used by DragGesture)
        // to help in multi-button drag events
        kStateBit = (1 << 30),
        kButtonsOnlyMask = 0x0000ffff,
    };

    OMNIUI_SCENE_API GestureButtons(uint32_t buttons)
        : m_mouseButtons(buttons)
    {
    }

    OMNIUI_SCENE_API std::vector<uint32_t> getMouseButtons() const
    {
        if (!isMultiButton())
        {
            return { m_mouseButtons };
        }
        std::vector<uint32_t> buttons;
        for (uint32_t butonIndex = 0; butonIndex < kMaxNumButtons; ++butonIndex)
        {
            if (m_mouseButtons & (1 << butonIndex))
            {
                buttons.emplace_back(butonIndex);
            }
        }
        return buttons;
    }

    OMNIUI_SCENE_API bool checkMouseButtons(uint32_t buttons, bool isRelease = false) const
    {
        // Make ourMouseButtons holds only interesting buttons
        //
        uint32_t ourMouseButtons = m_mouseButtons & kButtonsOnlyMask;
        if (!isMultiButton())
        {
            // If it is not a multi-button, then bit shift the single button
            //
            ourMouseButtons = (1 << ourMouseButtons);
        }
        // Bit patterns should match otherwise different buttons are down/up than what is needed
        //
        return buttons == ourMouseButtons;
    }

    OMNIUI_SCENE_API bool checkAnyMouseButtons(uint32_t buttons) const
    {
        uint32_t ourMouseButtons = m_mouseButtons & kButtonsOnlyMask;
        if (!isMultiButton())
        {
            // If it is not a multi-button, then bit shift the single button
            //
            ourMouseButtons = (1 << ourMouseButtons);
        }
        // Bit patterns should overlap otherwise different buttons are down than what is needed
        //
        return (buttons & ourMouseButtons) != 0;
    }

    OMNIUI_SCENE_API bool isMultiButton() const
    {
        return m_mouseButtons & kMultiButtonFlag;
    }

    OMNIUI_SCENE_API bool empty() const
    {
        if (!isMultiButton())
        {
            // Not empty as 0 is button-0.
            return false;
        }
        return (m_mouseButtons & kButtonsOnlyMask) == 0;
    }

    OMNIUI_SCENE_API bool contains(const GestureButtons& rhs) const
    {
        // If right hand side is not a multi-button, then only need to check the single buttong
        //
        if (!rhs.isMultiButton())
        {
            return checkAnyMouseButtons(rhs.m_mouseButtons);
        }
        // Iterate all the buttons and confirm any button in first drag is also present in second drag
        //
        for (uint32_t butonIndex = 0; butonIndex < GestureButtons::kMaxNumButtons; ++butonIndex)
        {
            const uint32_t buttonMask = (1 << butonIndex);
            if (rhs.m_mouseButtons & buttonMask)
            {
                if (!(m_mouseButtons & buttonMask))
                {
                    return false;
                }
            }
        }
        // All buttons in rhs are in this object too
        return true;
    }

    OMNIUI_SCENE_API bool getStateBit() const
    {
        return m_mouseButtons & kStateBit;
    }

    OMNIUI_SCENE_API bool operator == (const GestureButtons& rhs) const
    {
        return (m_mouseButtons & ~kStateBit) == (rhs.m_mouseButtons & ~kStateBit);
    }

private:
    const uint32_t m_mouseButtons;
};

class OMNIUI_SCENE_CLASS_API GestureButtonEditor
{
public:
    OMNIUI_SCENE_API GestureButtonEditor(uint32_t& mouseButtons)
        : m_mouseButtons(mouseButtons)
    {
    }

    OMNIUI_SCENE_API bool getStateBit() const
    {
        return GestureButtons(m_mouseButtons).getStateBit();
    }

    OMNIUI_SCENE_API bool checkMouseButtons(uint32_t buttons, bool isRelease = false) const
    {
        return GestureButtons(m_mouseButtons).checkMouseButtons(buttons, isRelease);
    }

    OMNIUI_SCENE_API bool checkAnyMouseButtons(uint32_t buttons) const
    {
        return GestureButtons(m_mouseButtons).checkAnyMouseButtons(buttons);
    }

    OMNIUI_SCENE_API bool isMultiButton() const
    {
        return GestureButtons(m_mouseButtons).isMultiButton();
    }

    OMNIUI_SCENE_API void setMouseButtons(const std::vector<uint32_t>& buttons)
    {
        if (buttons.size() <= 1)
        {
            m_mouseButtons = buttons.empty() ? GestureButtons::kMultiButtonFlag : buttons.front();
            return;
        }

        m_mouseButtons = GestureButtons::kMultiButtonFlag;
        for (uint32_t button : buttons)
        {
            m_mouseButtons |= (1 << button);
        }
    }

    OMNIUI_SCENE_API void setStateBit(bool value)
    {
        m_mouseButtons = value ?
            (m_mouseButtons | GestureButtons::kStateBit) :
            (m_mouseButtons & ~GestureButtons::kStateBit);
    }

    OMNIUI_SCENE_API void operator = (uint32_t singleButton)
    {
        m_mouseButtons = singleButton | (m_mouseButtons & GestureButtons::kStateBit);
    }
private:
    uint32_t& m_mouseButtons;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
