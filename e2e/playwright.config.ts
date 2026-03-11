import { defineConfig, devices } from '@playwright/test'
import { config } from 'dotenv'
import path from 'path'

// Load .env from project root (parent of e2e/)
config({ path: path.resolve(__dirname, '..', '.env') })

const isCI = !!process.env.CI

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
      reuseExistingServer: !isCI,
      env: {
        DATA_DIR: path.resolve(__dirname, '.tmp-data'),
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
