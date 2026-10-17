import { defineConfig, devices } from "@playwright/test";
import { config } from "dotenv";
import fs from "fs";
import path from "path";
import { BACKEND_PORT, BACKEND_URL, FRONTEND_PORT } from "./helpers/config";

// Load .env from project root (parent of e2e/)
config({ path: path.resolve(__dirname, "..", ".env") });

const isCI = !!process.env.CI;
const dataDir = path.resolve(__dirname, ".tmp-data");
fs.mkdirSync(path.join(dataDir, "library"), { recursive: true });
// Models live in the project's data/models (scripts/models/setup_models.py
// puts them there); link them in rather than downloading a second copy.
const projectModels = path.resolve(__dirname, "..", "data", "models");
const testModels = path.join(dataDir, "models");
fs.mkdirSync(projectModels, { recursive: true });
if (!fs.existsSync(testModels)) {
  fs.symlinkSync(projectModels, testModels, "junction");
}

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: isCI
    ? [["html", { open: "never" }], ["github"]]
    : [["html", { open: "on-failure" }]],

  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],

  webServer: [
    {
      command: `uv run python -m backend.app.main --port ${BACKEND_PORT}`,
      url: `${BACKEND_URL}/health`,
      name: "Backend",
      timeout: 120_000,
      reuseExistingServer: !isCI,
      // An isolated data dir and library, so tests never touch a real library.
      env: {
        APP_DATA_DIR: dataDir,
        IMAGE_LIBRARY_DIR: path.join(dataDir, "library"),
        API_HOST: "127.0.0.1",
      },
      cwd: path.resolve(__dirname, ".."),
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      name: "Frontend",
      timeout: 30_000,
      reuseExistingServer: !isCI,
      env: { API_PROXY_TARGET: BACKEND_URL },
      cwd: path.resolve(__dirname, "..", "frontend"),
    },
  ],
});
