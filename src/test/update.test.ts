import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { checkForUpdate, isNewerVersion, UPDATE_CHECK_INTERVAL_MS } from "../core/update.js";

test("stable release versions compare numerically", () => {
  assert.equal(isNewerVersion("0.12.2", "0.12.1"), true);
  assert.equal(isNewerVersion("0.13.0", "0.12.9"), true);
  assert.equal(isNewerVersion("1.0.0", "0.99.99"), true);
  assert.equal(isNewerVersion("0.12.1", "0.12.1"), false);
  assert.equal(isNewerVersion("0.12.0", "0.12.1"), false);
  assert.equal(isNewerVersion("0.13.0-beta.1", "0.12.1"), false);
});

test("automatic checks reuse the npm result for 24 hours", async () => {
  const configDirectory = mkdtempSync(join(process.cwd(), ".tmp-sustech-cli-update-"));
  let requests = 0;
  const fetchImpl = async () => {
    requests += 1;
    return new Response(JSON.stringify({ version: "0.13.0" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const first = await checkForUpdate({
      currentVersion: "0.12.1",
      configDirectory,
      now: new Date("2026-09-14T00:00:00Z"),
      fetchImpl,
    });
    const cached = await checkForUpdate({
      currentVersion: "0.12.1",
      configDirectory,
      now: new Date("2026-09-14T12:00:00Z"),
      fetchImpl,
    });
    const refreshed = await checkForUpdate({
      currentVersion: "0.12.1",
      configDirectory,
      now: new Date(Date.parse("2026-09-14T00:00:00Z") + UPDATE_CHECK_INTERVAL_MS),
      fetchImpl,
    });

    assert.equal(first.updateAvailable, true);
    assert.equal(first.cached, false);
    assert.equal(cached.cached, true);
    assert.equal(refreshed.cached, false);
    assert.equal(requests, 2);
  } finally {
    rmSync(configDirectory, { recursive: true, force: true });
  }
});

test("a registry failure is quiet and is cached to avoid delaying every command", async () => {
  const configDirectory = mkdtempSync(join(process.cwd(), ".tmp-sustech-cli-update-failure-"));
  let requests = 0;
  const fetchImpl = async () => {
    requests += 1;
    throw new Error("offline");
  };

  try {
    const first = await checkForUpdate({
      currentVersion: "0.12.1",
      configDirectory,
      now: new Date("2026-09-14T00:00:00Z"),
      fetchImpl,
    });
    const cached = await checkForUpdate({
      currentVersion: "0.12.1",
      configDirectory,
      now: new Date("2026-09-14T01:00:00Z"),
      fetchImpl,
    });
    assert.equal(first.latestVersion, undefined);
    assert.equal(cached.cached, true);
    assert.equal(requests, 1);
  } finally {
    rmSync(configDirectory, { recursive: true, force: true });
  }
});
