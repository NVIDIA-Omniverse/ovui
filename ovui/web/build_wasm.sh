#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_ROOT="$ROOT/ovui/web"
CACHE_DIR="${OVUI_WEB_CACHE_DIR:-$WEB_ROOT/.cache}"
BUILD_DIR="$WEB_ROOT/build-wasm"
DIST_DIR="$WEB_ROOT/dist"
PACKAGE_DIR="$BUILD_DIR/package"

CPYTHON_VERSION="${OVUI_CPYTHON_VERSION:-3.12.3}"
CPYTHON_TARBALL="Python-${CPYTHON_VERSION}.tgz"
CPYTHON_URL="${OVUI_CPYTHON_URL:-https://www.python.org/ftp/python/${CPYTHON_VERSION}/${CPYTHON_TARBALL}}"
CPYTHON_SHA256="${OVUI_CPYTHON_SHA256:-a6b9459f45a6ebbbc1af44f5762623fa355a0c87208ed417628b379d762dddb0}"
CPYTHON_SOURCE_DIR="$CACHE_DIR/cpython-${CPYTHON_VERSION}"
CPYTHON_BUILD_DIR="$CPYTHON_SOURCE_DIR/builddir/emscripten-browser-static"
PYBIND11_VENV="${OVUI_PYBIND11_VENV:-$CACHE_DIR/pybind11-venv}"
PYBIND11_VERSION="${OVUI_PYBIND11_VERSION:-2.13.6}"
EMSDK_ENV="${OVUI_EMSDK_ENV:-/tmp/ovui-emsdk/emsdk_env.sh}"

JOBS="${OVUI_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"

if [[ -f "$EMSDK_ENV" ]]; then
    # shellcheck source=/dev/null
    source "$EMSDK_ENV" >/dev/null
fi

if [[ -n "${EMSDK:-}" && -z "${EM_CONFIG:-}" && -f "$EMSDK/.emscripten" ]]; then
    export EM_CONFIG="$EMSDK/.emscripten"
fi

for tool in emcc emconfigure emmake emar; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool not found. Activate Emscripten or set OVUI_EMSDK_ENV." >&2
        exit 1
    fi
done

mkdir -p "$CACHE_DIR"

if [[ ! -x "$PYBIND11_VENV/bin/python" ]]; then
    python3 -m venv "$PYBIND11_VENV"
    "$PYBIND11_VENV/bin/python" -m pip install --upgrade pip >/dev/null
    "$PYBIND11_VENV/bin/python" -m pip install "pybind11==$PYBIND11_VERSION" >/dev/null
fi
PYBIND11_INCLUDE_DIR="$("$PYBIND11_VENV/bin/python" -c 'import pybind11; print(pybind11.get_include())')"

if [[ ! -d "$CPYTHON_SOURCE_DIR" ]]; then
    TARBALL_PATH="$CACHE_DIR/$CPYTHON_TARBALL"
    if [[ ! -f "$TARBALL_PATH" ]]; then
        curl -L --fail --retry 3 -o "$TARBALL_PATH" "$CPYTHON_URL"
    fi
    echo "${CPYTHON_SHA256}  ${TARBALL_PATH}" | sha256sum -c -
    TMP_EXTRACT="$CACHE_DIR/Python-${CPYTHON_VERSION}"
    rm -rf "$TMP_EXTRACT"
    tar -xzf "$TARBALL_PATH" -C "$CACHE_DIR"
    mv "$TMP_EXTRACT" "$CPYTHON_SOURCE_DIR"
fi

if [[ ! -x "$CPYTHON_SOURCE_DIR/builddir/build/python" ]]; then
    (
        cd "$CPYTHON_SOURCE_DIR"
        ./Tools/wasm/wasm_build.py build
    )
fi

if [[ ! -f "$CPYTHON_BUILD_DIR/libpython3.12.a" || ! -f "$CPYTHON_BUILD_DIR/usr/local/lib/python312.zip" ]]; then
    rm -rf "$CPYTHON_BUILD_DIR"
    mkdir -p "$CPYTHON_BUILD_DIR"
    (
        cd "$CPYTHON_BUILD_DIR"
        CONFIG_SITE=../../Tools/wasm/config.site-wasm32-emscripten \
        emconfigure ../../configure -C \
            --host=wasm32-unknown-emscripten \
            --build="$(../../config.guess)" \
            --with-emscripten-target=browser \
            --disable-wasm-dynamic-linking \
            --with-build-python="$(pwd)/../build/python"
        emmake make -j"$JOBS"
    )
fi

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$PACKAGE_DIR/usr" "$PACKAGE_DIR/home/ovui/python/omni" "$PACKAGE_DIR/assets/fonts" "$DIST_DIR"

cp -R "$CPYTHON_BUILD_DIR/usr/local" "$PACKAGE_DIR/usr/"
cp "$ROOT/ovui/resources/fonts/NotoSans-Regular.ttf" "$PACKAGE_DIR/assets/fonts/NotoSans-Regular.ttf"
cp "$ROOT/ovui/python/omni/__init__.py" "$PACKAGE_DIR/home/ovui/python/omni/__init__.py"
cp -R "$ROOT/ovui/python/omni/ui" "$PACKAGE_DIR/home/ovui/python/omni/ui"
rm -rf "$PACKAGE_DIR/home/ovui/python/omni/ui/standalone"
find "$PACKAGE_DIR/home/ovui/python" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PACKAGE_DIR/home/ovui/python" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.so' -o -name '*.so.*' \) -delete

cmake \
    -S "$ROOT/ovui" \
    -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="${EMSDK}/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake" \
    -DOMNI_UI_BUILD_WEB_RUNTIME=ON \
    -DOMNI_UI_BUILD_MARKDOWN_TESTS=OFF \
    -DPython_EXECUTABLE="$PYBIND11_VENV/bin/python" \
    -DPYTHON_EXECUTABLE="$PYBIND11_VENV/bin/python" \
    -DOVUI_PYBIND11_INCLUDE_DIR="$PYBIND11_INCLUDE_DIR" \
    -DOVUI_CPYTHON_SOURCE_DIR="$CPYTHON_SOURCE_DIR" \
    -DOVUI_CPYTHON_WASM_BUILD_DIR="$CPYTHON_BUILD_DIR" \
    -DOVUI_WEB_PACKAGE_DIR="$PACKAGE_DIR" \
    -DOVUI_WEB_OUTPUT_DIR="$DIST_DIR"

cmake --build "$BUILD_DIR" --target ovui_web --parallel "$JOBS"

cp "$WEB_ROOT/static/index.html" "$DIST_DIR/index.html"
cp "$WEB_ROOT/static/styles.css" "$DIST_DIR/styles.css"
mv "$DIST_DIR/ovui.js" "$DIST_DIR/app.js"

find "$DIST_DIR" -mindepth 1 -maxdepth 1 \
    ! -name index.html \
    ! -name app.js \
    ! -name styles.css \
    ! -name ovui.wasm \
    ! -name ovui.data \
    -exec rm -rf {} +

actual="$(find "$DIST_DIR" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | sort | tr '\n' ' ')"
expected="app.js index.html ovui.data ovui.wasm styles.css "
if [[ "$actual" != "$expected" ]]; then
    echo "Unexpected dist contents: $actual" >&2
    exit 1
fi

echo "$DIST_DIR/index.html"
