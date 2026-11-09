import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 45000,
  expect: { timeout: 15000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.DEMO_BASE_URL || 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: process.env.DEMO_BASE_URL
    ? undefined
    : [
        {
          command:
            '../backend/.venv/bin/python -m uvicorn fraud_api.main:app --app-dir ../backend/src --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log',
          url: 'http://localhost:8000/health',
          reuseExistingServer: !process.env.CI,
          env: { FRAUD_COOKIE_SECURE: 'false', FRAUD_FRONTEND_ORIGIN: 'http://localhost:5173' },
        },
        {
          command: 'npm run dev',
          url: 'http://localhost:5173',
          reuseExistingServer: !process.env.CI,
        },
      ],
});
