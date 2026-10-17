import { defineConfig, devices } from '@playwright/test'
import { config } from 'dotenv'
import path from 'path'
import { prepareIsolatedRun } from './helpers/isolation'

// Load .env from project root (parent of e2e/)
config({ path: path.resolve(__dirname, '..', '.env') })

const isCI = !!process.env.CI

// Fresh APP_DATA_DIR / IMAGE_LIBRARY_DIR per run, exported into process.env so
// the backend and everything the tests spawn use it (never the repo's ./data).
const run = prepareIsolatedRun()

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: isCI
    ? [['html', { open: 'never' }], ['github']]
    : [['html', { open: 'on-failure' }]],

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],

  webServer: [
    {
      command: 'uv run python -m backend.app.main',
      url: 'http://localhost:8000/health',
      name: 'Backend',
      timeout: 120_000,
      // Never reuse a running backend: it would be using someone's real library,
      // and the seed would import into it. Stop any dev backend on :8000 first.
      reuseExistingServer: false,
      env: {
        APP_DATA_DIR: run.appDataDir,
        IMAGE_LIBRARY_DIR: run.imageLibraryDir,
      },
      cwd: path.resolve(__dirname, '..'),
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      name: 'Frontend',
      timeout: 30_000,
      reuseExistingServer: !isCI,
      cwd: path.resolve(__dirname, '..', 'frontend'),
    },
  ],
})
