/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

namespace omni {
namespace ui {
namespace standalone {

// zlib compressor for stb_image_write (STBIW_ZLIB_COMPRESS). It is stb's own
// compressor with the same matches and the same bits, so PNG files stay
// byte-identical. Only the match length is measured eight bytes at a time.
// stb measures it one byte at a time; that loop takes most of the PNG time,
// and its speed changed by about 20% with the code layout of the library.
// The result is allocated with malloc, as stb_image_write frees it.
unsigned char* pngZlibCompress(unsigned char* data, int dataLen, int* outLen, int quality);

} // namespace standalone
} // namespace ui
} // namespace omni
