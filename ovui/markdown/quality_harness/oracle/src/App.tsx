import { useEffect, useState } from "react";
import { Streamdown, defaultRemarkPlugins } from "streamdown";
import { code } from "@streamdown/code";
import { createMathPlugin } from "@streamdown/math";
import { remarkAlert } from "remark-github-blockquote-alert";
import "katex/dist/katex.min.css";
import "remark-github-blockquote-alert/alert.css";

const mathPlugin = createMathPlugin({ singleDollarTextMath: true });

// streamdown's remarkPlugins prop replaces defaults wholesale, so we must
// re-include the defaults (remark-gfm etc.) alongside our GitHub alert
// plugin or tables, task lists, and strikethrough silently break.
const remarkPlugins = [...Object.values(defaultRemarkPlugins), remarkAlert];

const DEFAULT_FILE = "atoms/01_paragraph.md";

const THEMES = new Set(["white", "black", "dark_blue"]);

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; content: string }
  | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [file, setFile] = useState<string>("");
  const [theme, setTheme] = useState<string>("white");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("file") ?? DEFAULT_FILE;
    const requestedTheme = params.get("theme") ?? "white";
    const resolvedTheme = THEMES.has(requestedTheme) ? requestedTheme : "white";
    setFile(requested);
    setTheme(resolvedTheme);

    // Drive Tailwind `dark:` variants (Shiki tokens) via the root class.
    document.documentElement.classList.toggle(
      "dark",
      resolvedTheme !== "white",
    );
    document.documentElement.dataset.theme = resolvedTheme;

    const url = requested.startsWith("/") ? requested : `/${requested}`;
    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${url}`);
        }
        return res.text();
      })
      .then((text) => setState({ kind: "ready", content: text }))
      .catch((err) =>
        setState({ kind: "error", message: (err as Error).message }),
      );
  }, []);

  return (
    <div
      className={`oracle-surface theme-${theme.replace("_", "-")}`}
      data-file={file}
      data-theme={theme}
    >
      {state.kind === "loading" && (
        <div data-role="loading" style={{ color: "#64748b" }}>
          Loading {file}…
        </div>
      )}
      {state.kind === "error" && (
        <pre
          data-role="error"
          style={{ color: "#b91c1c", whiteSpace: "pre-wrap" }}
        >
          Failed to load {file}: {state.message}
        </pre>
      )}
      {state.kind === "ready" && (
        <article className="prose prose-slate max-w-none" data-role="rendered">
          <Streamdown
            mode="static"
            shikiTheme={["github-light", "github-dark"]}
            plugins={{ code, math: mathPlugin }}
            remarkPlugins={remarkPlugins}
            controls={{ code: { copy: true, download: false } }}
            allowedTags={{
              div: ["className", "dir"],
              p: ["className", "dir"],
              svg: ["className", "viewBox", "width", "height", "ariaHidden"],
              path: ["d", "fillRule", "clipRule"],
            }}
          >
            {state.content}
          </Streamdown>
        </article>
      )}
      {/* Sentinel the Playwright driver waits for to know rendering
          has committed (including any post-render KaTeX / Mermaid passes). */}
      {state.kind === "ready" && (
        <div data-testid="rendered-sentinel" style={{ display: "none" }} />
      )}
    </div>
  );
}
