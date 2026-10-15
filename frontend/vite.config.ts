import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The build goes to board/static/app/, which FastAPI serves at /next/ during the migration.
// base "./" keeps asset links relative, so the same build works at /next/ and later at /.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: { outDir: "../board/static/app", emptyOutDir: true },
  server: {
    port: 5173,
    // `npm run dev` talks to a test server: INTERN_BOARD_NO_REFRESH=1 uvicorn ... --port 8766
    proxy: { "/api": "http://127.0.0.1:8766" },
    fs: { allow: [".."] }, // the shared stylesheet lives in board/static
  },
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.ts"],
  },
});
