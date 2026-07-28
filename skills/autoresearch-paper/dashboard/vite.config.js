import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: resolve(import.meta.dirname, "../references/dashboard"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
});
