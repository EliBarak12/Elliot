#!/usr/bin/env node
/**
 * Build the single-file Elliot app view and sync it into elliot_core's
 * package data (packages/core/src/elliot_core/apps/assets/), where the
 * Python side serves it at ui:// URIs. The asset is COMMITTED so installing
 * elliot-core never needs Node; `--check` rebuilds to a temp dir and
 * byte-compares, which CI runs to catch source/asset drift.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");
const assetsDir = resolve(pkgRoot, "../core/src/elliot_core/apps/assets");
const assetName = "elliot-app.html";
const checkMode = process.argv.includes("--check");

const distDir = join(pkgRoot, "dist");
rmSync(distDir, { recursive: true, force: true });
execFileSync("pnpm", ["exec", "vite", "build"], { cwd: pkgRoot, stdio: "inherit" });

const builtPath = join(distDir, "index.html");
if (!existsSync(builtPath)) {
  console.error(`[ui-kit] build produced no ${builtPath}`);
  process.exit(1);
}
const built = readFileSync(builtPath);
const hash = createHash("sha256").update(built).digest("hex");
const kb = Math.round(built.length / 1024);
console.log(`[ui-kit] built ${assetName}: ${kb} KiB, sha256 ${hash.slice(0, 16)}…`);

// React + the official ext-apps SDK (which bundles zod schema validation)
// land around ~475 KiB raw / ~120 KiB gzipped on the wire; hosts fetch the
// template once per URI and cache it. Budget guards against runaway growth,
// not against the baseline.
const SIZE_BUDGET_KB = 600;
if (kb > SIZE_BUDGET_KB) {
  console.error(
    `[ui-kit] ${assetName} is ${kb} KiB — over the ${SIZE_BUDGET_KB} KiB budget. ` +
      "Views are inlined into agent-host iframes; keep the bundle lean."
  );
  process.exit(1);
}

const committedPath = join(assetsDir, assetName);
if (checkMode) {
  if (!existsSync(committedPath)) {
    console.error(`[ui-kit] --check: committed asset missing at ${committedPath}`);
    process.exit(1);
  }
  const committed = readFileSync(committedPath);
  if (!committed.equals(built)) {
    console.error(
      "[ui-kit] --check: committed asset differs from a fresh build. " +
        "Run `pnpm --filter @elliot/ui-kit run build` and commit the result."
    );
    process.exit(1);
  }
  console.log("[ui-kit] --check: committed asset matches the source. OK.");
} else {
  mkdirSync(assetsDir, { recursive: true });
  cpSync(builtPath, committedPath);
  writeFileSync(
    join(assetsDir, "BUILD_INFO.json"),
    JSON.stringify({ asset: assetName, sha256: hash, size_bytes: built.length }, null, 2) + "\n"
  );
  console.log(`[ui-kit] synced → ${committedPath}`);
}
