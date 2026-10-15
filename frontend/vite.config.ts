import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The build goes to board/static/, which FastAPI serves at /. It's generated: edit frontend/ instead.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: {
    outDir: "../board/static",
    emptyOutDir: true,
    rollupOptions: { input: { main: "index.html", doc: "doc.html" } }, // the app, and the printable document page
  },
  server: {
    port: 5173,
    // `npm run dev` talks to a test server: INTERN_BOARD_NO_REFRESH=1 uvicorn ... --port 8766
    proxy: { "/api": "http://127.0.0.1:8766" },
  },
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.ts"],
  },
});
