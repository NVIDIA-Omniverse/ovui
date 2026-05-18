# GL vs Vulkan Performance Benchmarks

Measures rendering performance of the OpenGL and Vulkan backends in omni.ui
standalone, giving hard numbers on frame time, CPU time, GPU time, memory
usage, and screenshot/readback latency.

## Building

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target vk_gl_benchmark -j$(nproc)
```

The binary is placed in `build/benchmarks/vk_gl_benchmark`.

## Running

```bash
# Run both backends (default), 1000 frames, multiple widget counts
./build/benchmarks/vk_gl_benchmark

# Single backend
./build/benchmarks/vk_gl_benchmark --backend gl
./build/benchmarks/vk_gl_benchmark --backend vk

# Custom parameters
./build/benchmarks/vk_gl_benchmark --frames 500 --widgets 100,500

# Offscreen-only mode (no visible window)
./build/benchmarks/vk_gl_benchmark --offscreen

# Export results as JSON
./build/benchmarks/vk_gl_benchmark --json results.json

# All options
./build/benchmarks/vk_gl_benchmark --backend both --frames 1000 \
    --widgets 10,100,500,1000 --offscreen --json results.json
```

## Command-Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `--backend <gl\|vk\|both>` | `both` | Which backend(s) to benchmark |
| `--frames <N>` | `1000` | Number of frames per test |
| `--widgets <N,N,...>` | `10,100,500,1000` | Comma-separated widget counts to test |
| `--offscreen` | off | Hide the window (GLFW_VISIBLE=false) |
| `--json <path>` | none | Write results to JSON file |
| `--warmup <N>` | `100` | Warmup frames before measurement |

## What Is Measured

### Per-frame metrics (over N frames, reports min/avg/max/p99)

| Metric | How |
|--------|-----|
| **Frame time** | Wall-clock `steady_clock` around full `tick()` |
| **CPU time** | Wall-clock around ImGui widget submission + render call (excludes swap/present) |
| **GPU time (GL)** | `GL_TIME_ELAPSED` query around `ImGui_ImplOpenGL3_RenderDrawData` |
| **GPU time (VK)** | Vulkan timestamp queries around render pass |
| **Memory (RSS)** | `/proc/self/statm` on Linux, `mach_task_info` on macOS |

### Readback/screenshot latency

Measures the time to read back the framebuffer to CPU memory:
- **GL**: `glReadPixels` (RGBA8, full framebuffer)
- **VK**: `VulkanBackend::readbackPixels` (staging buffer + copy + map)

## Interpreting Results

The terminal output prints a table like:

```
=== GL vs VK Benchmark Results ===
Backend  Widgets  FrameTime(ms)        CPU(ms)              GPU(ms)              Readback(ms)    RSS(MB)
                  min/avg/max/p99      min/avg/max/p99      min/avg/max/p99      avg
GL       10       0.42/0.51/1.20/0.98  0.30/0.38/0.95/0.82  0.18/0.22/0.45/0.38  1.23            45.2
GL       100      0.68/0.82/1.80/1.52  0.52/0.65/1.40/1.20  0.35/0.42/0.85/0.72  1.25            46.1
...
VK       10       0.38/0.45/0.92/0.78  0.28/0.34/0.72/0.65  0.15/0.19/0.38/0.32  2.10            52.3
```

Key things to look for:
- **GPU time** is the fairest comparison — measures actual rendering work
- **Readback** is expected to be slower for Vulkan (staging buffer overhead)
- **RSS** shows memory footprint differences
- **p99** reveals tail latency — important for UI responsiveness

## Notes

- When `--backend both` is used, the benchmark spawns itself as a child process
  for each backend (GL and VK cannot coexist in one GLFW window).
- If Vulkan is not available at runtime, the VK tests are skipped gracefully.
- V-Sync is disabled during benchmarks for accurate timing.
- A warmup phase runs before measurement to let caches and driver optimizations settle.
