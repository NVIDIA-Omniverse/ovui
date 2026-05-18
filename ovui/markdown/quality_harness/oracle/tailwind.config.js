/** @type {import('tailwindcss').Config} */
export default {
  // Toggle dark variants via the `.dark` class on <html>, not via the
  // prefers-color-scheme media query. The render_oracle driver sets the
  // class per requested theme so Shiki's `dark:` token variants fire.
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    // streamdown + its plugins ship Tailwind classes in their dist files;
    // scan them so Tailwind emits the utility CSS they rely on.
    "./node_modules/streamdown/dist/**/*.{js,mjs}",
    "./node_modules/@streamdown/code/dist/**/*.{js,mjs}",
    "./node_modules/@streamdown/math/dist/**/*.{js,mjs}",
  ],
  theme: {
    extend: {
      typography: {
        DEFAULT: {
          css: {
            maxWidth: "72ch",
            color: "#0f172a",
            a: { color: "#2563eb" },
          },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
