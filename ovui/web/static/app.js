const DEFAULT_SCRIPT = `import omni.ui as ui

style = {
    "Window": {
        "background_color": 0xFF1B1F22,
        "border_color": 0xFF3A4650,
        "border_width": 1,
        "padding": 16,
    },
    "Label": {
        "color": 0xFFEAF2F4,
        "font_size": 16,
    },
    "Button": {
        "background_color": 0xFF2D6673,
        "border_radius": 5,
        "padding": 8,
        "color": 0xFFF4FBFC,
    },
    "Button:hovered": {
        "background_color": 0xFF338091,
    },
    "Button:pressed": {
        "background_color": 0xFF27A596,
    },
    "FloatSlider": {
        "draw_mode": ui.SliderDrawMode.FILLED,
        "background_color": 0xFF26313A,
        "secondary_color": 0xFF4FC3AE,
        "border_radius": 4,
        "padding": 2,
    },
    "ProgressBar": {
        "background_color": 0xFF26313A,
        "color": 0xFFE1B64A,
        "secondary_color": 0xFF101417,
        "border_radius": 4,
    },
    "Field": {
        "background_color": 0xFF11161A,
        "border_color": 0xFF42515B,
        "border_width": 1,
        "border_radius": 4,
        "color": 0xFFEAF2F4,
        "padding": 6,
    },
}

window = ui.Window(
    "Fixed-size embedded CPython omni.ui window",
    width=620,
    height=360,
    position_x=24,
    position_y=12,
    fill_app_window=False,
    flags=ui.WINDOW_FLAGS_NO_RESIZE,
)

name_model = ui.SimpleStringModel("Omniverse")
progress_model = ui.SimpleFloatModel(0.35, min=0.0, max=1.0)

with window.frame:
    with ui.VStack(spacing=10, style=style):
        ui.Label("Browser Python is official CPython embedded in the ovui WebAssembly app.", height=0)
        ui.Label("The top panel is rendered by C++ ovui widgets on Dear ImGui/WebGL.", word_wrap=True, height=0)
        ui.Separator(height=0)

        ui.Label("Name", height=0, style={"color": 0xFF98ACB8})
        name = ui.StringField(name_model, width=360, height=30)

        ui.Label("Progress", height=0, style={"color": 0xFF98ACB8})
        progress = ui.ProgressBar(progress_model, width=520, height=22)
        slider = ui.FloatSlider(progress_model, min=0.0, max=1.0, width=520, height=28)
        status = ui.Label("Waiting for a button click", height=0, word_wrap=True)

        def advance():
            next_value = min(progress_model.get_value_as_float() + 0.2, 1.0)
            progress_model.set_value(next_value)
            status.text = f"Advanced for {name_model.get_value_as_string()}: {next_value:.0%}"

        def print_status():
            print(
                f"Print callback from embedded CPython omni.ui: "
                f"name={name_model.get_value_as_string()} "
                f"progress={progress_model.get_value_as_float():.0%}"
            )

        with ui.HStack(spacing=8, height=36):
            ui.Button("Advanced", clicked_fn=advance, width=132, height=32)
            ui.Button("Print", clicked_fn=print_status, width=104, height=32)
`;

const canvas = document.querySelector("#canvas");
const editor = document.querySelector("#python-editor");
const consoleEl = document.querySelector("#console");
const runButton = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");

const state = {
  ready: false,
  running: false,
  ticking: false,
  canvasCssWidth: 1,
  canvasCssHeight: 1,
  canvasDpr: 1,
  canvasSizeDirty: false,
};

globalThis.ovuiAppendConsole = appendConsole;

editor.value = DEFAULT_SCRIPT;
runButton.addEventListener("click", () => runPythonScript());
window.addEventListener("resize", () => resizeCanvas());
window.visualViewport?.addEventListener("resize", () => resizeCanvas());
canvas.addEventListener("pointerdown", () => {
  canvas.focus({ preventScroll: true });
});

Module.onRuntimeInitialized = () => {
  boot().catch((error) => {
    setStatus("error", "Load failed");
    writeConsole(error?.stack || String(error));
  });
};

async function boot() {
  setStatus("loading", "Loading embedded CPython");
  resizeCanvas();

  const initialized = Module.ccall(
    "ovui_web_init",
    "number",
    ["string", "number", "number", "number"],
    ["#canvas", state.canvasCssWidth, state.canvasCssHeight, state.canvasDpr]
  );
  if (!initialized) {
    throw new Error("ovui WebAssembly runtime failed to initialize");
  }

  state.ready = true;
  runButton.disabled = false;
  state.canvasSizeDirty = false;
  setStatus("ready", backendStatus());
  await runPythonScript();
  requestAnimationFrame(renderLoop);
}

async function runPythonScript() {
  if (!state.ready || state.running) {
    return;
  }

  state.running = true;
  runButton.disabled = true;
  consoleEl.textContent = "";
  setStatus("loading", "Running Python");

  try {
    const resultJson = Module.ccall("ovui_web_run_python", "string", ["string"], [editor.value]);
    const result = JSON.parse(resultJson);
    writeConsole(formatRunOutput(result));
    setStatus(result.status === "ok" ? "ready" : "error", result.status === "ok" ? backendStatus() : "Python error");
  } catch (error) {
    setStatus("error", "Runtime error");
    writeConsole(error?.stack || String(error));
  } finally {
    state.running = false;
    runButton.disabled = false;
  }
}

function renderLoop() {
  resizeCanvas();
  if (state.ready && !state.running && !state.ticking) {
    state.ticking = true;
    try {
      Module.ccall("ovui_web_tick", "number", [], []);
    } catch (error) {
      setStatus("error", "Render error");
      appendConsole(error?.stack || String(error));
    } finally {
      state.ticking = false;
    }
  }
  requestAnimationFrame(renderLoop);
}

function resizeCanvas() {
  const cssWidth = Math.max(1, canvas.clientWidth);
  const cssHeight = Math.max(1, canvas.clientHeight);
  const dpr = getDevicePixelRatio();
  const framebufferWidth = Math.max(1, Math.round(cssWidth * dpr));
  const framebufferHeight = Math.max(1, Math.round(cssHeight * dpr));
  const changed =
    canvas.width !== framebufferWidth ||
    canvas.height !== framebufferHeight ||
    state.canvasCssWidth !== cssWidth ||
    state.canvasCssHeight !== cssHeight ||
    state.canvasDpr !== dpr;

  if (changed) {
    canvas.width = framebufferWidth;
    canvas.height = framebufferHeight;
    state.canvasCssWidth = cssWidth;
    state.canvasCssHeight = cssHeight;
    state.canvasDpr = dpr;
    state.canvasSizeDirty = true;
  }

  if (state.canvasSizeDirty && state.ready && !state.running) {
    Module.ccall(
      "ovui_web_resize",
      "number",
      ["number", "number", "number"],
      [state.canvasCssWidth, state.canvasCssHeight, state.canvasDpr]
    );
    state.canvasSizeDirty = false;
  }
}

function getDevicePixelRatio() {
  const dpr = Number(window.devicePixelRatio) || 1;
  return Math.max(1, dpr);
}

function formatRunOutput(result, emptyText = "ok") {
  const chunks = [];
  if (result.stdout) chunks.push(result.stdout.trimEnd());
  if (result.stderr) chunks.push(result.stderr.trimEnd());
  if (result.traceback) chunks.push(result.traceback.trimEnd());
  return chunks.join("\n") || emptyText;
}

function writeConsole(text) {
  consoleEl.textContent = text;
}

function appendConsole(text) {
  if (!text) {
    return;
  }
  if (consoleEl.textContent && !consoleEl.textContent.endsWith("\n")) {
    consoleEl.textContent += "\n";
  }
  consoleEl.textContent += `${text}\n`;
  console.log(`[ovui python] ${text}`);
}

function backendStatus() {
  const backend = Module.ccall("ovui_web_backend_info", "string", [], []);
  const font = Module.ccall("ovui_web_font_info", "string", [], []).includes("loaded")
    ? "Noto Sans loaded"
    : "font fallback";
  return `${backend} · ${font} · ${canvasStatus()}`;
}

function canvasStatus() {
  return `${canvas.width}x${canvas.height} backing @ DPR ${state.canvasDpr.toFixed(2)}`;
}

function setStatus(stateName, text) {
  statusEl.dataset.state = stateName;
  statusEl.textContent = text;
}
