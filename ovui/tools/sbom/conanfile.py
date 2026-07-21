from conan import ConanFile


class OvuiConan(ConanFile):
    name = "ovui"
    version = "0.1.1"
    description = "GPU-accelerated Python UI toolkit"
    license = "LicenseRef-NVIDIA-Proprietary"
    url = "https://github.com/NVIDIA-Omniverse/ovui"
    homepage = "https://github.com/NVIDIA-Omniverse/ovui"
    topics = ("ui", "gpu", "vulkan", "opengl", "imgui")

    # C++ dependencies sourced via CMake FetchContent.
    # Versions mirror the GIT_TAG pins in ovui/CMakeLists.txt and
    # ovui/third_party/CMakeLists.txt.
    def requirements(self):
        # system-first; FetchContent fallback is VER-2-13-2
        self.requires("freetype/2.13.2")
        # system-first; FetchContent fallback is tag 3.4
        self.requires("glfw/3.4")
        # header-only; FetchContent pin: bf71a834 (0.9.9.8)
        self.requires("glm/0.9.9.8")
        # header-only; FetchContent pin: 31c1ad37
        self.requires("stb/cci.20230920")
        # header-only; FetchContent pin: c4ea7e40 (boost-1.85.0)
        self.requires("boost/1.85.0", options={"header_only": True})
        # OpenGL loader; FetchContent pin: 1ecd4577 (v0.1.36)
        self.requires("glad/0.1.36")
        # CommonMark parser; FetchContent pin: 729e6b8b (release-0.5.2)
        self.requires("md4c/0.5.2")

    def build_requirements(self):
        # Python binding generator; version requirement from pyproject.toml: >=2.11
        self.tool_requires("pybind11/2.13.6")

    def configure(self):
        # Mirror the FT_DISABLE_* flags set in ovui/CMakeLists.txt so Conan
        # does not pull in freetype's optional deps (zlib, libpng, brotli,
        # bzip2) that are absent from the actual build.
        self.options["freetype"].with_zlib = False
        self.options["freetype"].with_bzip2 = False
        self.options["freetype"].with_png = False
        self.options["freetype"].with_harfbuzz = False
        self.options["freetype"].with_brotli = False

    # imgui 1.92.7 is vendored in ovui/third_party/imgui/ with NVIDIA
    # patches applied; it is not managed by Conan and appears in the SBOM
    # as a manually-declared component (see generate_sbom.py).
