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

#define OMNIUI_PYBIND_DOC_MainWindow                                                                                   \
    "The MainWindow class represents Main Window for the Application, draw optional MainMenuBar and StatusBar.\n"      \
    "\n"


#define OMNIUI_PYBIND_DOC_MainWindow_mainMenuBar "The main MenuBar for the application.\n"


#define OMNIUI_PYBIND_DOC_MainWindow_mainFrame "This represents Styling opportunity for the Window background.\n"


#define OMNIUI_PYBIND_DOC_MainWindow_statusBarFrame                                                                    \
    "The StatusBar Frame is empty by default and is meant to be filled by other part of the system.\n"


#define OMNIUI_PYBIND_DOC_MainWindow_cppStatusBarEnabled "Workaround to reserve space for C++ status bar.\n"


#define OMNIUI_PYBIND_DOC_MainWindow_showForeground "When show_foreground is True, MainWindow prevents other windows from showing.\n"


#define OMNIUI_PYBIND_DOC_MainWindow_MainWindow                                                                        \
    "Construct the main window, add it to the underlying windowing system, and makes it appear.\n"
