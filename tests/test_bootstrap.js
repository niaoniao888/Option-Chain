"use strict";
const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  path = require("node:path");
const root = path.resolve(__dirname, ".."),
  html = fs.readFileSync(path.join(root, "web/app/index.html"), "utf8"),
  source = html.match(/<script[^>]+type="module"[^>]+src="([^"?]+)/)?.[1];
assert(source);
assert(fs.existsSync(path.resolve(root, "web/app", source)));
for (const asset of [
  "core/state.js",
  "core/polling.js",
  "core/formats.js",
  "core/model.js",
  "components/dashboard.js",
  "components/menu.js",
  "markets/bitcoin.js",
  "markets/us-equities.js",
  "markets/registry.js",
])
  assert(fs.existsSync(path.join(root, "web/app", asset)), asset);
console.log("Unified module bootstrap: PASS");
