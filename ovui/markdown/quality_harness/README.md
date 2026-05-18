# MarkdownWidget Quality Harness

Iterative visual-quality pipeline for the native `ui.MarkdownWidget`. The
harness renders the same markdown corpus through two reference paths and a
system-under-test (SUT), diffs the outputs, and drives the widget towards
visual parity with a chosen ground truth.

Two validation axes are maintained in parallel:

* **QA axis** — 12 themed full-document fixtures (`corpus/qa/`), rendered
  via a fast python-markdown + WeasyPrint ground truth. Used for
  coarse-grained per-feature regression checks and LLM-as-judge reports.
* **Quality axis** — 27 atomic + 4 composite + 4 document fixtures
  (`corpus/{atoms,composites,documents}/`), rendered via a fidelity-tuned
  React + Streamdown + Shiki + KaTeX oracle. Used for fine-grained
  per-marker pixel diffs against an aspirational reference.

Neither side blocks CI; both are driven on demand from a workstation with
a virtual X display.

## Layout

```
markdown/quality_harness/
├── corpus/
│   ├── qa/                QA-axis: themed complete documents
│   ├── atoms/             Quality-axis: one feature per file
│   ├── composites/        Quality-axis: mixed-structure interaction cases
│   └── documents/         Quality-axis: realistic AI-response shapes
├── oracle/                React + Vite + Streamdown reference renderer
├── providers/             Node runtime for MathJax / Mermaid plugins
├── scripts/
│   ├── generate_qa_ground_truth.py   corpus/qa → HTML → PDF → PNG
│   ├── generate_qa_ovui.py           corpus/qa → ovui widget → PNG
│   ├── fuse_qa_comparison.py         side-by-side panels
│   ├── llm_judge_qa.py               Claude-as-judge report
│   ├── render_oracle.py              corpus/* → streamdown → PNG
│   ├── render_sut.py                 corpus/* → ovui widget → PNG
│   ├── compare.py                    SSIM / pixel-diff metrics
│   ├── build_sidebyside.py           2-panel oracle|SUT composites
│   └── generate_showcase.py          per-feature hero renders
├── tracker/
│   ├── markers.yaml                  per-marker gate registry
│   └── results.json                  latest diff metrics
├── artifacts/                        output PNGs — gitignored
└── reports/                          judge reports — generated
```

## QA axis — quick loop

```bash
# Xvfb, if running headless
Xvfb :100 -screen 0 1024x2400x24 &

python3 markdown/quality_harness/scripts/generate_qa_ground_truth.py
DISPLAY=:100 PYTHONPATH=python:build/bindings \
    python3 markdown/quality_harness/scripts/generate_qa_ovui.py
python3 markdown/quality_harness/scripts/fuse_qa_comparison.py
python3 markdown/quality_harness/scripts/llm_judge_qa.py
```

Outputs land in `artifacts/qa_*/` and `reports/QA-JUDGE-RESULTS.md`.

## Quality axis — fine-grained loop

```bash
cd markdown/quality_harness/oracle
npm install             # once
cd ..

python3 scripts/render_oracle.py           # ground-truth renders
DISPLAY=:100 python3 scripts/render_sut.py # widget renders
python3 scripts/compare.py                 # diffs + metrics
```

Update `tracker/markers.yaml` to promote markers red → yellow → green as
gates pass.

## Providers runtime

`providers/` is a small Node package pulling MathJax and Mermaid so the
document provider plugin can rasterise inline math / diagrams before the
widget draws them. Install once with:

```bash
npm install --prefix markdown/quality_harness/providers
```

Both `render_sut.py` and the `markdown_provider_plugins_showcase.py`
example point at this directory.
