#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const url = process.env.OVUI_WASM_URL || process.argv[2] || "http://127.0.0.1:8765/index.html";
const outDir = process.env.OVUI_WASM_QA_OUT || "/tmp/ovui_hidpi_qa";
const dprs = [1, 1.75, 2.5];

const fillScript = `import omni.ui as ui

print(ui._web_dpi_info())

window = ui.Window("Fill-app high-DPI pybind11 window", fill_app_window=True)
with window.frame:
    with ui.VStack(spacing=12, style={
        "Window": {"background_color": 0xFF161B1F, "padding": 18, "border_width": 1, "border_color": 0xFF3A4650},
        "Label": {"color": 0xFFEAF2F4, "font_size": 16},
        "Button": {"background_color": 0xFF2D6673, "padding": 8, "color": 0xFFF4FBFC},
        "Field": {"background_color": 0xFF11161A, "border_color": 0xFF42515B, "border_width": 1, "padding": 6},
    }):
        ui.Label("fill_app_window=True uses logical CSS pixels while the canvas backing store uses DPR pixels.", word_wrap=True, height=0)
        ui.StringField(ui.SimpleStringModel("High DPI input"), width=420, height=32)
        ui.Button("Wide pybind button", width=220, height=34)
`;

const fixedScript = `import omni.ui as ui

print(ui._web_dpi_info())

window = ui.Window(
    "Fixed reset check",
    width=420,
    height=190,
    position_x=40,
    position_y=34,
    fill_app_window=False,
    flags=ui.WINDOW_FLAGS_NO_RESIZE,
)
with window.frame:
    with ui.VStack(spacing=10):
        ui.Label("This fixed window replaced the previous fill window.", height=0)
        ui.StringField(ui.SimpleStringModel("Reset kept one window"), width=260, height=30)
        ui.Label(f"callbacks={ui._web_window_callback_count()}", height=0)

print(f"callbacks={ui._web_window_callback_count()}")
`;

const diagnosticScript = `import omni.ui as ui

print(ui._web_dpi_info())

window = ui.Window(
    "DPR diagnostic",
    width=380,
    height=140,
    position_x=32,
    position_y=18,
    fill_app_window=False,
    flags=ui.WINDOW_FLAGS_NO_RESIZE,
)
with window.frame:
    with ui.VStack(spacing=8):
        ui.Label("DPR diagnostic rendered by compiled pybind11 _ui.", height=0)
        ui.StringField(ui.SimpleStringModel("font density follows DPR"), width=300, height=30)
`;

function assertCondition(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function screenshotPath(name) {
  return path.join(outDir, `${name}.png`);
}

async function waitReady(page) {
  await page.waitForFunction(
    () => document.querySelector("#status")?.textContent?.includes("backing @ DPR"),
    null,
    { timeout: 120000 }
  );
  await page.waitForFunction(
    () => document.querySelector("#console")?.textContent?.trim().length > 0,
    null,
    { timeout: 120000 }
  );
  await page.waitForTimeout(800);
}

async function measure(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector("#canvas");
    const frame = document.querySelector(".canvas-frame");
    const canvasRect = canvas.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    return {
      dpr: window.devicePixelRatio,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      documentScrollWidth: document.documentElement.scrollWidth,
      canvasRectWidth: canvasRect.width,
      canvasRectHeight: canvasRect.height,
      frameRectWidth: frameRect.width,
      frameRectHeight: frameRect.height,
      clientWidth: canvas.clientWidth,
      clientHeight: canvas.clientHeight,
      backingWidth: canvas.width,
      backingHeight: canvas.height,
      expectedWidth: Math.round(canvas.clientWidth * window.devicePixelRatio),
      expectedHeight: Math.round(canvas.clientHeight * window.devicePixelRatio),
      status: document.querySelector("#status").textContent.trim(),
      consoleText: document.querySelector("#console").textContent.trim(),
    };
  });
}

function assertCanvasBacking(metrics) {
  assertCondition(
    metrics.backingWidth === Math.round(metrics.clientWidth * metrics.dpr),
    `backing width ${metrics.backingWidth} != round(client ${metrics.clientWidth} * DPR ${metrics.dpr})`
  );
  assertCondition(
    metrics.backingHeight === Math.round(metrics.clientHeight * metrics.dpr),
    `backing height ${metrics.backingHeight} != round(client ${metrics.clientHeight} * DPR ${metrics.dpr})`
  );
  assertCondition(
    metrics.documentScrollWidth === metrics.viewportWidth,
    `horizontal overflow: document ${metrics.documentScrollWidth}, viewport ${metrics.viewportWidth}`
  );
}

function assertCanvasFitsViewport(metrics) {
  assertCondition(
    metrics.canvasRectWidth <= metrics.viewportWidth,
    `canvas width ${metrics.canvasRectWidth} exceeds viewport ${metrics.viewportWidth}`
  );
}

async function replaceEditorScript(page, script) {
  const editor = page.locator("#python-editor");
  await editor.click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.insertText(script);
}

async function runEditor(page) {
  await page.locator("#run-button").click();
  await page.waitForFunction(
    () => !document.querySelector("#run-button").disabled && document.querySelector("#console")?.textContent?.trim().length > 0,
    null,
    { timeout: 30000 }
  );
  await page.waitForTimeout(700);
}

async function runScriptThroughEditor(page, script, name) {
  await page.screenshot({ path: screenshotPath(`${name}_before_editor`) });
  await replaceEditorScript(page, script);
  await page.screenshot({ path: screenshotPath(`${name}_after_type_editor`) });
  await runEditor(page);
  await page.screenshot({ path: screenshotPath(`${name}_after_run`) });
}

function assertDpiInfo(metrics, expectedDpr) {
  const expected = `font_rasterizer_density=${expectedDpr.toFixed(3)}`;
  assertCondition(
    metrics.consoleText.includes(expected),
    `console did not report ${expected}; console was: ${metrics.consoleText}`
  );
  assertCondition(
    metrics.consoleText.includes(`device_pixel_ratio=${expectedDpr.toFixed(3)}`),
    `console did not report device_pixel_ratio=${expectedDpr.toFixed(3)}`
  );
}

async function withPage(dpr, viewport, callback) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport, deviceScaleFactor: dpr });
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 120000 });
    await waitReady(page);
    await callback(page);
  } finally {
    await browser.close();
  }
}

async function runDprMeasurements() {
  const results = [];
  for (const dpr of dprs) {
    await withPage(dpr, { width: 1280, height: 900 }, async (page) => {
      await page.screenshot({ path: screenshotPath(`dpr${String(dpr).replace(".", "_")}_ready`) });
      const readyMetrics = await measure(page);
      assertCanvasBacking(readyMetrics);

      await runScriptThroughEditor(page, diagnosticScript, `dpr${String(dpr).replace(".", "_")}_diagnostic`);
      const diagnosticMetrics = await measure(page);
      assertCanvasBacking(diagnosticMetrics);
      assertDpiInfo(diagnosticMetrics, dpr);
      results.push({ dpr, ready: readyMetrics, diagnostic: diagnosticMetrics });
    });
  }
  return results;
}

async function runInteractionScenario() {
  let result;
  await withPage(2.5, { width: 1280, height: 720 }, async (page) => {
    await page.screenshot({ path: screenshotPath("interaction_720_ready") });
    const initial = await measure(page);
    assertCanvasBacking(initial);
    assertCondition(initial.clientHeight >= 372, `720p canvas client height ${initial.clientHeight} clips the default 360px window`);

    await page.locator("#python-editor").click();
    await page.keyboard.press("End");
    await page.keyboard.insertText("\n# DOM editor typing verified by Playwright QA\n");
    await page.screenshot({ path: screenshotPath("interaction_720_dom_editor_typed") });

    const canvasBox = await page.locator("#canvas").boundingBox();
    assertCondition(!!canvasBox, "canvas bounding box unavailable");

    await page.mouse.click(canvasBox.x + 190, canvasBox.y + 155);
    await page.screenshot({ path: screenshotPath("interaction_720_canvas_field_focus") });
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.type("HiDpiQA");
    await page.screenshot({ path: screenshotPath("interaction_720_canvas_field_typed") });

    await page.mouse.click(canvasBox.x + 106, canvasBox.y + 316);
    await page.screenshot({ path: screenshotPath("interaction_720_advanced_clicked") });
    await page.mouse.click(canvasBox.x + 236, canvasBox.y + 316);
    await page.waitForFunction(
      () => document.querySelector("#console")?.textContent?.includes("HiDpiQA"),
      null,
      { timeout: 10000 }
    );
    await page.screenshot({ path: screenshotPath("interaction_720_print_clicked") });

    await runScriptThroughEditor(page, fillScript, "interaction_720_fill");
    const fillMetrics = await measure(page);
    assertCanvasBacking(fillMetrics);
    assertDpiInfo(fillMetrics, 2.5);

    await runScriptThroughEditor(page, fixedScript, "interaction_720_fixed_after_fill");
    const fixedMetrics = await measure(page);
    assertCanvasBacking(fixedMetrics);
    assertDpiInfo(fixedMetrics, 2.5);
    assertCondition(fixedMetrics.consoleText.includes("callbacks=1"), `reset did not leave one callback: ${fixedMetrics.consoleText}`);
    result = { initial, fill: fillMetrics, fixed: fixedMetrics };
  });
  return result;
}

async function runMobileViewportScenario() {
  let result;
  await withPage(2, { width: 390, height: 844 }, async (page) => {
    await page.screenshot({ path: screenshotPath("mobile_390_ready"), fullPage: true });
    const metrics = await measure(page);
    assertCanvasBacking(metrics);
    assertCanvasFitsViewport(metrics);
    result = metrics;
  });
  return result;
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const measurementResults = await runDprMeasurements();
  const interactionResult = await runInteractionScenario();
  const mobileResult = await runMobileViewportScenario();
  console.log(JSON.stringify({ url, outDir, measurementResults, interactionResult, mobileResult }, null, 2));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
