import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  timeout: 30_000,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: { baseURL: "http://127.0.0.1:8785", trace: "retain-on-failure" },
  webServer: {
    command: "python tests/browser/server.py",
    url: "http://127.0.0.1:8785/healthz",
    reuseExistingServer: false,
    timeout: 30_000,
    env: { PYTHONPATH: "src", OPTIONS_COLLECTOR_ENABLED: "false" },
  },
});
