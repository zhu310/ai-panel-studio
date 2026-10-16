import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "..");

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  retries: 0,
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
  webServer: [
    { command: "python -m backend.app.e2e_server", cwd: root,
      url: "http://127.0.0.1:8765/health", reuseExistingServer: false, timeout: 30_000 },
    { command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort", cwd: __dirname,
      env: { VITE_API_TARGET: "http://127.0.0.1:8765" },
      url: "http://127.0.0.1:4173", reuseExistingServer: false, timeout: 30_000 },
  ],
});
