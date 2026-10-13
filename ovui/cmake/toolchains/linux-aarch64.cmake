# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Cross-compiles for Linux ARM64 (aarch64) from a Linux x86_64 host with the
# distribution's aarch64-linux-gnu GCC. Libraries and headers come only from
# the ARM64 sysroot named by OVUI_AARCH64_SYSROOT (an Ubuntu root with the
# same -dev packages the native ARM64 build installs); programs such as
# wayland-scanner come from the host. CUDA is found through CUDAToolkit_ROOT:
# a host toolkit with the targets/sbsa-linux cross runtime installed.
# .github/scripts/setup_linux_aarch64_cross.sh prepares all of this.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_LIBRARY_ARCHITECTURE aarch64-linux-gnu)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

if(NOT CMAKE_SYSROOT)
    set(CMAKE_SYSROOT "$ENV{OVUI_AARCH64_SYSROOT}")
endif()
if(NOT IS_DIRECTORY "${CMAKE_SYSROOT}/usr/include/aarch64-linux-gnu")
    message(FATAL_ERROR "Set OVUI_AARCH64_SYSROOT to an ARM64 sysroot (got '${CMAKE_SYSROOT}')")
endif()

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# Executables linked against ovui's libraries need those libraries' CUDA runtime
# at link time; a native link finds it through ld.so.conf. Not recorded in binaries.
if(CUDAToolkit_ROOT)
    set(CMAKE_EXE_LINKER_FLAGS_INIT "-Wl,-rpath-link,${CUDAToolkit_ROOT}/targets/sbsa-linux/lib")
endif()

# pkg-config (GLFW's Wayland and xkbcommon lookups) must read the sysroot's .pc files.
set(ENV{PKG_CONFIG_SYSROOT_DIR} "${CMAKE_SYSROOT}")
set(ENV{PKG_CONFIG_LIBDIR} "${CMAKE_SYSROOT}/usr/lib/aarch64-linux-gnu/pkgconfig:${CMAKE_SYSROOT}/usr/share/pkgconfig")
