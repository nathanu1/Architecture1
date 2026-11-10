import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run build` lands inside the Python package so `ga play` can serve it without Node.
// `npm run build:demo` makes a static page that plays a recording (`ga export-demo`), with
// relative asset paths so it can be hosted anywhere, even without a server path of its own.
// `npm run build:tab` makes a static page that RUNS a town: the engine (Python in WebAssembly)
// and the residents' model (WebGPU) both live in the visitor's tab (docs/tab.md).
export default defineConfig(({ mode }) => {
  const demo = mode === "demo";
  const tab = mode === "tab";
  return {
    base: demo || tab ? "./" : "/",
    define: { "import.meta.env.VITE_DEMO": JSON.stringify(demo ? "1" : ""), "import.meta.env.VITE_TAB": JSON.stringify(tab ? "1" : "") },
    plugins: [react(), tailwindcss()],
    worker: { format: "es" as const },
    build: {
      outDir: demo ? "dist-demo" : tab ? "dist-tab" : "../src/generative_agents/game/web",
      emptyOutDir: true,
      chunkSizeWarningLimit: 8000,
      rollupOptions: demo ? { input: "demo.html" } : tab ? { input: "tab.html" } : undefined,
    },
    server: {
      proxy: { "/api": "http://127.0.0.1:8080", "/research": "http://127.0.0.1:8080" },
    },
  };
});
