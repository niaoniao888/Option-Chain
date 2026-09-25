"use strict";
// Classic scripts share a global lexical scope. Parsing each file separately
// misses duplicate declarations that prevent the page from ever loading data.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
for (const view of ["desktop", "mobile", "hub"]) {
  const directory = path.join(__dirname, "..", "web", view);
  const html = fs.readFileSync(path.join(directory, "index.html"), "utf8");
  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"[^>]*><\/script>/g)];
  const code = scripts.map(match => {
    const file = view === "hub" ? path.join(directory, path.basename(match[1])) : path.resolve(directory, match[1]);
    return fs.readFileSync(file, "utf8");
  }).join("\n;\n");
  new vm.Script(code, {filename: `${view}-combined-scripts.js`});
}
console.log("Page script scopes: PASS");
