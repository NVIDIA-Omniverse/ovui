# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Third-Party Notices

This is the consolidated third-party software inventory for `omni-ui`. It
covers vendored and fetched C/C++ source dependencies, bundled fonts and
image assets that ship inside the `omni-ui` Python wheel, and Python build /
runtime / optional dependencies declared in this repository.

NVIDIA's own license terms (see [README.md](README.md)) do **not** override
the upstream licenses of these components - your use of each component is
subject to its license. The full upstream license text for every
redistributable open-source component - including the C/C++ libraries
(sections 1-2), the inlined pybind11 headers (section 3), and the bundled font
and image assets (section 4) - is reproduced verbatim in this file so that
downstream consumers can satisfy
MIT/BSD/Apache/zlib/Boost/SIL-OFL/CC-BY/Unlicense attribution obligations
without consulting external sources. NVIDIA proprietary components are
governed by their own license terms, which are referenced rather than
reproduced here.

If you discover a missing or incorrect attribution, please open an issue
at <https://github.com/NVIDIA-Omniverse/ovui/issues>.

---


## 1. Vendored C/C++ source (in tree)

These third-party C/C++ sources are copied directly into this repository
under `ovui/third_party/` and built into the produced libraries / Python
extension modules. Their license obligations therefore attach to the
shipped binaries.

| Component | License | Distribution | Source |
|---|---|---|---|
| `glm` | MIT OR Happy Bunny License | In-tree at `ovui/third_party/` | (declared in `ovui/third_party/CMakeLists.txt`) |
| `imgui` | MIT | In-tree at `ovui/third_party/` | (declared in `ovui/third_party/CMakeLists.txt`) |
| `md4c` | MIT | In-tree at `ovui/third_party/` | (declared in `ovui/third_party/CMakeLists.txt`) |
| `stb` | MIT OR Unlicense | In-tree at `ovui/third_party/` | (declared in `ovui/third_party/CMakeLists.txt`) |

### License text

#### Dear ImGui - MIT License

```text
The MIT License (MIT)

Copyright (c) 2014-2026 Omar Cornut

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. Fetched at build time (CMake `FetchContent`)

These dependencies are downloaded from their upstream Git repositories by
CMake `FetchContent_Declare` when no satisfying system install is found.
When the fetch path is used, the resulting source is compiled into the
produced binaries.

| Component | Pinned ref | License | Upstream |
|---|---|---|---|
| `boost_preprocessor` | `c4ea7e40d365` (commit) | BSL-1.0 | <https://github.com/boostorg/preprocessor.git> |
| `freetype` | VER-2-13-2 | Other | <https://github.com/freetype/freetype.git> |
| `glad` | `1ecd45775d96` (commit) | MIT AND Apache-2.0 | <https://github.com/Dav1dde/glad.git> |
| `glfw` | 3.4 | Zlib | <https://github.com/glfw/glfw.git> |
| `glm` | `bf71a8349481` (commit) | MIT OR Happy Bunny License | <https://github.com/g-truc/glm.git> |
| `md4c` | `729e6b8b320c` (commit) | MIT | <https://github.com/mity/md4c.git> |
| `stb` | `31c1ad374564` (commit) | MIT OR Unlicense | <https://github.com/nothings/stb.git> |

Notes:
- **freetype** is dual-licensed under the FreeType License (FTL, a BSD-style
  license with a credit clause) or GPLv2. `omni-ui` builds against FreeType
  under the FTL option. A credit line is provided in section 5.
- **glm** is dual-licensed under "The Happy Bunny License" (Modified MIT)
  or the MIT License at the user's choice; `omni-ui` uses the MIT option.
  GLM additionally embeds `glm/gtc/ulp.inl` containing code derived from
  SunPro / Sun Microsystems (1993), distributed under a permissive
  notice-preservation license that requires the original notice be preserved.
- **stb** is dual-licensed under MIT or the Unlicense (Public Domain).
- The GLAD generator output and bundled `KHR/khrplatform.h` are MIT /
  Apache-2.0 dual-licensed (Khronos).

### License text

#### boost_preprocessor - Boost Software License 1.0

```text
Boost Software License - Version 1.0 - August 17th, 2003

Permission is hereby granted, free of charge, to any person or organization
obtaining a copy of the software and accompanying documentation covered by
this license (the "Software") to use, reproduce, display, distribute,
execute, and transmit the Software, and to prepare derivative works of the
Software, and to permit third-parties to whom the Software is furnished to
do so, all subject to the following:

The copyright notices in the Software and this entire statement, including
the above license grant, this restriction and the following disclaimer,
must be included in all copies of the Software, in whole or in part, and
all derivative works of the Software, unless such copies or derivative
works are solely in the form of machine-executable object code generated by
a source language processor.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, TITLE AND NON-INFRINGEMENT. IN NO EVENT
SHALL THE COPYRIGHT HOLDERS OR ANYONE DISTRIBUTING THE SOFTWARE BE LIABLE
FOR ANY DAMAGES OR OTHER LIABILITY, WHETHER IN CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

#### freetype - FreeType License (FTL)

```text
The FreeType Project LICENSE (FTL).

This software, dedicated to the development, modification and use of font
rendering technology, is copyright (c) 1996-present by The FreeType Project
(www.freetype.org). All rights reserved.

The FreeType License, similar to the original BSD license with an
advertising clause, applies to all software developed by the FreeType
project, including the FreeType font engine. It allows redistribution and
use in source and binary forms, with or without modification, subject to
the conditions reproduced in full in docs/FTL.TXT in the upstream FreeType
source distribution.

Credits. We acknowledge that the FreeType Project must be credited in any
product, project or document that uses the FreeType engine. A
FreeType-credit line is therefore provided in section 5 of this notice.

Full FTL text:
<https://gitlab.freedesktop.org/freetype/freetype/-/raw/master/docs/FTL.TXT>
```

#### glad - MIT License

```text
GLAD is licensed as follows:

The MIT License (MIT)

Copyright (c) 2013-2022 David Herberth

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

#### glad - bundled KHR/khrplatform.h (Khronos)

```text
KHR/khrplatform.h:

Copyright (c) 2008-2018 The Khronos Group Inc.

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and/or associated documentation files (the
"Materials"), to deal in the Materials without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Materials, and to
permit persons to whom the Materials are furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Materials.

THE MATERIALS ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
MATERIALS OR THE USE OR OTHER DEALINGS IN THE MATERIALS.
```

#### glfw - zlib/libpng License

```text
Copyright (c) 2002-2006 Marcus Geelnard
Copyright (c) 2006-2019 Camilla Loewy

This software is provided 'as-is', without any express or implied
warranty. In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would
   be appreciated but is not required.

2. Altered source versions must be plainly marked as such, and must not
   be misrepresented as being the original software.

3. This notice may not be removed or altered from any source
   distribution.
```

#### glm - MIT License (option chosen by omni-ui)

```text
The MIT License

Copyright (c) 2005 - G-Truc Creation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

Restrictions: By making use of the Software for military purposes, you
choose to make a Bunny unhappy.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

#### glm - SunPro / Sun Microsystems sub-component (glm/gtc/ulp.inl)

```text
GLM additionally bundles glm/gtc/ulp.inl which contains code derived from
SunPro / Sun Microsystems (1993), distributed under a permissive notice-
preservation license:

Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
Developed at SunPro, a Sun Microsystems, Inc. business.
Permission to use, copy, modify, and distribute this software is freely
granted, provided that this notice is preserved.
```

#### md4c - MIT License

```text
The MIT License (MIT)

Copyright (c) 2016-2024 Martin Mitas

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

#### stb - MIT License or Public Domain (Unlicense)

```text
ALTERNATIVE A - MIT License

Copyright (c) 2017 Sean Barrett

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.

ALTERNATIVE B - Public Domain (www.unlicense.org)

This is free and unencumbered software released into the public domain.
Anyone is free to copy, modify, publish, use, compile, sell, or distribute
this software, either in source code form or as a compiled binary, for any
purpose, commercial or non-commercial, and by any means.
In jurisdictions that recognize copyright laws, the author or authors of
this software dedicate any and all copyright interest in the software to
the public domain. We make this dedication for the benefit of the public
at large and to the detriment of our heirs and successors. We intend this
dedication to be an overt act of relinquishment in perpetuity of all
present and future rights to this software under copyright law.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

---

## 3. External system prerequisites (`find_package` / runtime)

These libraries and toolchain components are resolved from the host system
at build or run time. They are not vendored in this repository. Apart from the
CUDA runtime library described in the notes below, they are not redistributed
by `omni-ui`. They are listed here because they affect what downstream users
must have installed to build or run `omni-ui`.

| Prerequisite | Pinned ref | License |
|---|---|---|
| `CUDAToolkit` | (unpinned) | NVIDIA proprietary (CUDA Toolkit EULA) |
| `Freetype` | (unpinned) | FTL OR GPL-2.0-or-later |
| `glfw3` | 3.3 | Zlib |
| `OpenGL` | (unpinned) | MIT (Khronos headers); vendor-licensed runtime ICD |
| `PkgConfig` | (unpinned) | GPL-2.0-or-later (build-time tool, not redistributed) |
| `pybind11` | 2.13.6 | BSD-3-Clause |
| `Python3` | (unpinned) | Python-2.0 (Python Software Foundation License v2) |
| `Vulkan` | (unpinned) | Apache-2.0 (Khronos headers + LunarG/Khronos loader) |

Notes:
- **CUDAToolkit** is governed by the NVIDIA CUDA Toolkit EULA; it is an
  NVIDIA proprietary prerequisite, not an OSS component. The Toolkit itself is
  a build-time prerequisite and is not redistributed. One file from it is: the
  CUDA runtime library (`cudart64_*.dll` / `libcudart.so.*`) ships inside the
  `omni.ui` package, because the native backend imports it and a supported
  machine has the NVIDIA driver without a Toolkit installation. Its terms are
  the EULA's, which is referenced here rather than reproduced. The CUDA
  *driver* library (`nvcuda.dll` / `libcuda.so.1`) is not redistributed; it
  comes from the installed driver.
- **Freetype** is dual-licensed under the FreeType License (FTL, a BSD-style
  license with a credit clause) or GPLv2. `omni-ui` builds against Freetype
  under the FTL option; the required credit line is in section 5. The
  prerequisite resolves to a dynamic link against the system `libfreetype`
  when one is available; the FetchContent fallback (see section 2) ships
  Freetype source built into the produced binaries otherwise.
- **glfw3** is licensed under the zlib/libpng license. The prerequisite
  resolves to a dynamic link against the system `libglfw3` when one is
  available; the FetchContent fallback (see section 2) applies otherwise.
  Full zlib/libpng license text is reproduced in section 2.
- **OpenGL** headers (`GL/gl.h`, `KHR/khrplatform.h`) are issued by The
  Khronos Group under MIT-style permissive terms. The runtime OpenGL
  implementation is provided by the host system's GPU vendor (NVIDIA, AMD,
  Intel, Mesa, etc.) under that vendor's own license; `omni-ui` does not
  redistribute any OpenGL runtime library.
- **Vulkan** headers and the Vulkan loader (`libvulkan.so` / `vulkan-1.dll`)
  are issued by The Khronos Group and LunarG under the Apache License,
  Version 2.0. The runtime ICD is provided by the host system's GPU vendor;
  `omni-ui` does not redistribute the Vulkan SDK or any ICD.
- **PkgConfig** finds the `pkg-config` tool, which is licensed under
  GPL-2.0-or-later. CMake invokes `pkg-config` as a build-time subprocess
  to discover library flags; the tool itself is not linked into or
  redistributed by `omni-ui`, so the tool's GPL obligations do not attach
  to the produced wheel.
- **Python3** is licensed under the Python Software Foundation License
  Version 2 (SPDX `Python-2.0`), a permissive GPL-compatible license.
  `omni-ui` links dynamically against the host Python interpreter via
  pybind11; the Python runtime itself is not redistributed by `omni-ui`.
- **pybind11** is licensed under BSD-3-Clause. It is header-only and
  contributes inline code to the produced extension modules, so a copy of
  pybind11's code is present in the shipped binary. Full pybind11 license
  text follows below.

### License text

#### pybind11 - BSD-3-Clause

```text
Copyright (c) 2016 Wenzel Jakob <wenzel.jakob@epfl.ch>, All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

You are under no obligation whatsoever to provide any bug fixes, patches, or
upgrades to the features, functionality or performance of the source code
("Enhancements") to anyone; however, if you choose to make your Enhancements
available either publicly, or directly to the author of this software, without
imposing a separate written license agreement for such Enhancements, then you
hereby grant the following license: a non-exclusive, royalty-free perpetual
license to install, use, modify, prepare derivative works, incorporate into
other computer software, distribute, and sublicense such enhancements or
derivative works thereof, in binary and source code form.
```

---

## 4. Bundled font and image assets

These resources ship inside the repository tree at `ovui/resources/`. They
are loaded at runtime by the rendering layer and are redistributed as part
of the `omni-ui` Python wheel.

| Asset | License | Files |
|---|---|---|
| Noto Sans (8 styles: Regular, Italic, Light, LightItalic, Medium, MediumItalic, Bold, BoldItalic) | SIL Open Font License 1.1 | `ovui/resources/fonts/NotoSans-*.ttf` (license: `ovui/resources/fonts/OFL.txt`) |
| Open Sans (SemiBold) | Apache License 2.0 | `ovui/resources/fonts/OpenSans-SemiBold.ttf` (license: `ovui/resources/fonts/LICENSE-Apache-2.0.txt`) |
| Roboto (Medium) | Apache License 2.0 | `ovui/resources/fonts/roboto_medium.ttf` (license: `ovui/resources/fonts/LICENSE-Apache-2.0.txt`) |
| Twemoji atlas (image + JSON metadata) | CC-BY 4.0 (graphics) | `ovui/resources/twemoji-atlas.png`, `ovui/resources/twemoji-atlas.json` |

Provenance information for the bundled fonts is recorded at
`ovui/resources/fonts/PROVENANCE.md`.

### License text

#### Noto Sans - SIL Open Font License 1.1

```text
Copyright 2012 Google Inc. All Rights Reserved.

This Font Software is licensed under the SIL Open Font License,
Version 1.1.

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply to any
document created using the fonts or their derivatives.

Full license text:
<https://openfontlicense.org/>

In-tree license file: `ovui/resources/fonts/OFL.txt`.
```

#### Open Sans - Apache License 2.0

```text
Digitized data copyright 2010-2011, Google Corporation.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

In-tree license file: `ovui/resources/fonts/LICENSE-Apache-2.0.txt`.
```

#### Roboto - Apache License 2.0

```text
Copyright 2011 Google Inc. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

In-tree license file: `ovui/resources/fonts/LICENSE-Apache-2.0.txt`.
```

#### Twemoji - CC-BY 4.0

```text
Copyright 2020 Twitter, Inc and other contributors
Graphics licensed under CC-BY 4.0:
<https://creativecommons.org/licenses/by/4.0/>

Attribution: emoji graphics adapted from Twemoji v15.1 by Twitter, Inc.
and other contributors. Twemoji code (not redistributed here) is
licensed under MIT.
```

---

## 5. FreeType credit line

The FreeType License (FTL) requires a credit acknowledgement when the
FreeType engine is used. Per section 2, builds that take the FetchContent
path link FreeType source code into the produced binaries.

> Portions of this software are copyright (c) The FreeType Project
> (www.freetype.org). All rights reserved.

Full FTL text: <https://gitlab.freedesktop.org/freetype/freetype/-/raw/master/docs/FTL.TXT>

---

## 6. Python build / runtime / optional dependencies

These dependencies are declared in `pyproject.toml` files in this repository
or referenced from README install instructions. They are resolved from PyPI
at install time and are not vendored.

### 6a. Build-system requires (PEP 517)

| Package | Required version | License |
|---|---|---|
| `cmake` | >=3.22 | Apache-2.0 AND BSD-3-Clause |
| `pybind11` | >=2.13.6,<3 | BSD-3-Clause |
| `setuptools` | >=84.0.0 (`ovui`), >=68 (all other packages) | MIT |
| `wheel` | (unpinned) | MIT |

### 6b. Runtime / optional dependencies (declared)

| Package | Version | License | Scope |
|---|---|---|---|
| `fastapi` | >=0.100.0 | MIT | runtime (inspector skill) |
| `httpx` | >=0.25.0 | BSD-3-Clause | runtime (inspector skill) |
| `pydantic` | >=2 | MIT | runtime (inspector skill) |
| `python-multipart` | ==0.0.33 | Apache-2.0 | runtime (inspector skill) |
| `uvicorn` | >=0.23.0 (`[standard]` extra) | BSD-3-Clause | runtime (inspector skill) |
| `numpy` | >=1.20 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime: `ovui-data-adapters-common`, `ovui-data-adapters-openusd`, `ovui-widgets-viewport` |
| `numpy` | >=1.21 | (as above) | optional: `ovui[examples]` |
| `numpy` | >=1.26 | (as above) | optional: `ovui-widgets-app[media]` |
| `numpy` | (unpinned) | (as above) | optional: `ovui-widgets-common[testing]` |
| `cuda-python` | (unpinned) | LicenseRef-NVIDIA-SOFTWARE-LICENSE (up to 13.3); Apache-2.0 (13.4 and later) | optional: `ovui[examples]` |
| `usd-core` | ==25.11 | LicenseRef-TOST-1.0 | optional: `ovui-data-adapters-openusd[standalone]` |

Notes:
- `fastapi`, `httpx`, `pydantic`, `python-multipart`, `uvicorn` are declared
  by the `skills/omniverse-ui-inspector/` developer skill; they are not part
  of the shipped `omni-ui` Python wheel. The inspector command providers in
  `ovui-widgets` import `pydantic` only when the inspector is in use.
- `cuda-python` is unpinned, so its license depends on the installed release.
- `usd-core` reports `LicenseRef-TOST-1.0` (Tomorrow Open Source Technology
  License 1.0, the OpenUSD upstream license). It provides the OpenUSD Python
  bindings for the `standalone` extra.
- `numpy` is BSD-3-Clause with embedded files under 0BSD, MIT, Zlib, and
  CC0-1.0 (see numpy upstream LICENSE).

### 6c. Optional packages that users install separately

These packages are not bundled in any `ovui` wheel. They are installed from
PyPI (Python) or npm (JavaScript) only when the user installs them or asks
for the extra. Shipped `ovui` code uses them when they are present.

| Package | Version | License | How it is used |
|---|---|---|---|
| `CairoSVG` | (not declared) | LGPL-3.0-or-later | `omni.ui.markdown_providers` (`svg.py`, `math.py`) rasterizes SVG to PNG if it is installed |
| `imageio-ffmpeg` | >=0.6 | BSD-2-Clause | `ovui-widgets-app[media]` |
| `ovstream` | (unpinned) | LicenseRef-NvidiaProprietary (NVIDIA package) | `ovui-widgets-app[media]`, `ovui-data-adapters-openusd[livestream]` |
| `ovrtx` | (not declared) | LicenseRef-NvidiaProprietary (NVIDIA package) | renderer for `ovui-widgets` and `ovui-data-adapters` |
| `ovstage` | (not declared) | LicenseRef-NvidiaProprietary (NVIDIA package) | runtime for `ovui-data-adapters-ovstage` |
| `@mermaid-js/mermaid-cli` (npm) | (not declared) | MIT | `omni.ui.markdown_providers` (`mermaid.py`) runs its `mmdc` command if the user has installed it |
| `@mathjax/src` (npm) | (not declared) | Apache-2.0 | `omni.ui.markdown_providers` (`math.py`) runs it with Node.js if the user has installed it |

Note on Mermaid CLI: `ovui` does not distribute `@mermaid-js/mermaid-cli` or
any of its dependencies. When a user installs it, npm also installs its
dependencies, which include `elkjs` (EPL-2.0) and `DOMPurify`
(MPL-2.0 OR Apache-2.0). Section 7b lists the versions that the repository's
own test project locks.

Note on FFmpeg: `imageio-ffmpeg` installs or downloads an FFmpeg executable.
`ovui` does not distribute FFmpeg. Depending on where that FFmpeg build comes
from, it can be licensed under the LGPL or the GPL. Check its license before
you use or redistribute it.

Note on CairoSVG: `ovui` does not distribute CairoSVG. It is licensed under
the LGPL-3.0-or-later.

NOTICE AND DISCLAIMER: This software automatically retrieves, accesses or interacts with external materials.  Those retrieved materials are not distributed with this software and are governed solely by separate terms, conditions and licenses.  You are solely responsible for finding, reviewing and complying with all applicable terms, conditions, and licenses, and for verifying the security, integrity and suitability of any retrieved materials for your specific use case. This software is provided "AS IS", without warranty of any kind. The author makes no representations or warranties regarding any retrieved materials, and assumes no liability for any losses, damages, liabilities or legal consequences from your use or inability to use this software or any retrieved materials. Use this software and the retrieved materials at your own risk.

---

## 7. Build, test and development tools (not distributed)

The tools below are used only to build, test or develop `ovui`. They are
**not distributed**: no `ovui` wheel or release artifact contains their
code. Only direct dependencies are listed.

### 7a. Python

| Package | Version | License | Used by |
|---|---|---|---|
| `pip` | (unpinned) | MIT | CI workflows (`build-app-wheelhouse.yml`) |
| `build` | (unpinned) | MIT | CI workflows (`build-app-wheelhouse.yml`), Windows build recipe |
| `ninja` | (unpinned) | Apache-2.0 | Windows build recipe (`ovui-widgets/WINDOWS-BUILD*.md`) |
| `conan` | >=2.14 | MIT | `ovui/pyproject.toml` (build-system), SBOM |
| conan-extensions `sbom` command | (default branch) | MIT | `ovui/setup.py` fetches it from <https://github.com/conan-io/conan-extensions> to generate the SBOM |
| `cyclonedx-python-lib` | >=5.0.0,<6 | Apache-2.0 | `ovui/pyproject.toml` (build-system), SBOM |
| `pytest` | >=7.0 (`ovui/requirements-test.txt`), >=7,<10 (CI), unpinned (`ovui-widgets-app[dev]`) | MIT | tests |
| `pytest-forked` | >=1.4 | MIT | `ovui/requirements-test.txt` |
| `pytest-asyncio` | >=0.21 | Apache-2.0 | `ovui/requirements-test.txt` |
| `pytest-timeout` | >=2.1 | MIT | `ovui/requirements-test.txt` |
| `pytest-cov` | >=5.0 | MIT | `ovui/requirements-test.txt` |
| `numpy` | >=1.21 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `ovui/requirements-test.txt` |
| `Pillow` | >=9.0 | MIT-CMU | `ovui/requirements-test.txt`, Markdown quality harness |
| `PyOpenGL` | >=3.1 | BSD-3-Clause (the wheel also bundles freeglut, MIT-style, and GLE, Artistic / IBM example license, for Windows) | `ovui/requirements-test.txt` |
| `libcst` | (unpinned) | MIT AND PSF-2.0 AND Apache-2.0 | `ovui-widgets-app[dev]` |
| `tomli` | (unpinned) | MIT | `ovui-widgets-app[dev]` |
| `ruff` | (unpinned) | MIT | lint config in `ovui-widgets/pyproject.toml`, dev setup in `LIVESTREAM.md` |
| `mypy` | (unpinned) | MIT | type-check config in `ovui-widgets/pyproject.toml`, dev setup in `LIVESTREAM.md` |
| `scikit-image` | (unpinned) | BSD-3-Clause | Markdown quality harness (`compare.py`) |
| `PyMuPDF` | (unpinned) | AGPL-3.0 or Artifex commercial license | Markdown quality harness (`generate_qa_ground_truth.py`) |
| `Markdown` | (unpinned) | BSD-3-Clause | Markdown quality harness (`generate_qa_ground_truth.py`) |
| `WeasyPrint` | (unpinned) | BSD-3-Clause | Markdown quality harness (`generate_qa_ground_truth.py`) |
| `playwright` | (unpinned) | Apache-2.0 | Markdown quality harness (`render_oracle.py`) |
| `ovphysx` | (not declared) | LicenseRef-NVIDIA-Omniverse (NVIDIA package) | optional import in `ovui-data-adapters` tests |

CI workflows also install the current `ovrtx` and `ovstage` releases, and
pin `ovstream` (==0.4.5), for tests; see section 6c.

### 7b. JavaScript

Two private npm projects under `ovui/markdown/quality_harness/` are used
for Markdown tests and local showcases. Constraints are from their
`package.json` files; locked versions are from their `package-lock.json`
files. CI also runs one npm tool. Both projects constrain `katex` to ^0.18.2
with an npm override. `oracle` also overrides `postcss-selector-parser` to
^7.1.6 for `@tailwindcss/typography`. Both projects need Node.js 22.12 or
newer, as the `engines` field in each `package.json` states.

| Package | Constraint (locked) | License | Used by |
|---|---|---|---|
| `@streamdown/code` | ^1.1.1 (1.1.1) | Apache-2.0 | `oracle` |
| `@streamdown/math` | ^1.0.2 (1.0.3) | Apache-2.0 | `oracle` |
| `react` | ^18.3.1 (18.3.1) | MIT | `oracle` |
| `react-dom` | ^18.3.1 (18.3.1) | MIT | `oracle` |
| `remark-github-blockquote-alert` | ^2.1.0 (2.1.0) | MIT | `oracle` |
| `streamdown` | ^2.5.0 (2.7.1) | Apache-2.0 | `oracle` |
| `@tailwindcss/postcss` | ^4.3.3 (4.3.3) | MIT | `oracle` (dev) |
| `@tailwindcss/typography` | ^0.5.20 (0.5.20) | MIT | `oracle` (dev) |
| `@types/react` | ^18.3.12 (18.3.31) | MIT | `oracle` (dev) |
| `@types/react-dom` | ^18.3.1 (18.3.7) | MIT | `oracle` (dev) |
| `@vitejs/plugin-react` | ^5.2.0 (5.2.0) | MIT | `oracle` (dev) |
| `postcss` | ^8.5.23 (8.5.31) | MIT | `oracle` (dev) |
| `tailwindcss` | ^4.3.3 (4.3.3) | MIT | `oracle` (dev) |
| `typescript` | ^5.6.3 (5.9.3) | Apache-2.0 | `oracle` (dev) |
| `vite` | ^7.3.7 (7.3.7) | MIT | `oracle` (dev) |
| `@mathjax/src` | ^4.0.0 (4.1.3) | Apache-2.0 | `providers` |
| `@mermaid-js/mermaid-cli` | ^11.17.0 (11.17.0) | MIT | `providers` |
| `puppeteer` | ^25.16.0 (25.16.0) | Apache-2.0 | `providers` |

Some packages in the lock files have licenses that need a license check and
are not in the table above. None of them is distributed. The wheels hold only
the Python packages and the package data that each `setup.py` or
`pyproject.toml` lists, and no wheel contains a file of `quality_harness`. The
release source archives (`git archive` of the release commit) contain the
`package.json` and `package-lock.json` files of the two npm projects. Those
files list package names and versions only. No `node_modules` folder, npm
package code or JavaScript bundle is in any wheel or release archive.

| Package | Locked | License | Pulled in by |
|---|---|---|---|
| `lightningcss` | 1.32.0 | MPL-2.0 | `oracle` (dev): `@tailwindcss/postcss` and `vite` |
| `elkjs` | 0.9.3 | EPL-2.0 | `providers`: `@mermaid-js/layout-elk` of `@mermaid-js/mermaid-cli` |
| `dompurify` | 3.4.17 | MPL-2.0 OR Apache-2.0 (Apache-2.0 elected) | `providers`: `mermaid` of `@mermaid-js/mermaid-cli` |
| `@fortawesome/fontawesome-free` | 7.3.1 | CC-BY-4.0 AND OFL-1.1 AND MIT | `providers`: `@mermaid-js/mermaid-cli` |
| `khroma` | 2.1.0 | MIT (from the package's `license` file; its `package.json` has no `license` field) | `providers`: `mermaid` of `@mermaid-js/mermaid-cli` |

Note on DOMPurify: DOMPurify is dual-licensed under the Mozilla Public
License 2.0 and the Apache License 2.0. NVIDIA elects the Apache License 2.0.
Attribution: DOMPurify, (c) Cure53 and other contributors,
<https://github.com/cure53/DOMPurify>. The upstream package has no NOTICE
file. The full Apache License 2.0 text is in this repository's `LICENSE` file
and in `ovui/resources/fonts/LICENSE-Apache-2.0.txt`.

---


