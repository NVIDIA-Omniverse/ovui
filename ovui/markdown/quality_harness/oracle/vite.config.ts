// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Serve the corpus directory as static files so the React app can
// fetch `/atoms/01_paragraph.md` etc. directly from the browser.
export default defineConfig({
  plugins: [react()],
  publicDir: path.resolve(__dirname, "../corpus"),
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
});
