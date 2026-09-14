import { execFile, spawn } from "node:child_process";
import { lstat, readFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { defaultConfigDirectory, writeJsonAtomically } from "./local-store.js";

const execFileAsync = promisify(execFile);
const REGISTRY_URL = "https://registry.npmjs.org/sustech-cli/latest";
export const UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1_000;

interface UpdateCache {
  schemaVersion: "1";
  checkedAt: string;
  latestVersion?: string;
}

export interface UpdateStatus {
  currentVersion: string;
  latestVersion?: string;
  updateAvailable: boolean;
  checkedAt: string;
  cached: boolean;
}

export interface CheckUpdateOptions {
  currentVersion: string;
  force?: boolean;
  now?: Date;
  configDirectory?: string;
  fetchImpl?: typeof fetch;
}

export function isNewerVersion(candidate: string, current: string): boolean {
  const candidateParts = parseStableVersion(candidate);
  const currentParts = parseStableVersion(current);
  if (!candidateParts || !currentParts) return false;
  for (let index = 0; index < 3; index += 1) {
    if (candidateParts[index] !== currentParts[index]) return candidateParts[index] > currentParts[index];
  }
  return false;
}

export function shouldAutomaticallyCheck(argv: string[], env: NodeJS.ProcessEnv = process.env): boolean {
  if (!process.stdin.isTTY || !process.stderr.isTTY) return false;
  if (env.CI || env.SUSTECH_DISABLE_UPDATE_CHECK === "1") return false;
  if (argv.some((argument) => argument === "--json" || argument === "--jsonl" || /^--output=(json|jsonl)$/.test(argument))) return false;
  const outputIndex = argv.indexOf("--output");
  if (outputIndex >= 0 && ["json", "jsonl"].includes(argv[outputIndex + 1] ?? "")) return false;
  const command = argv.find((argument) => !argument.startsWith("-"));
  return command !== "update" && command !== "version" && !argv.includes("--help") && !argv.includes("-h");
}

export async function checkForUpdate(options: CheckUpdateOptions): Promise<UpdateStatus> {
  const now = options.now ?? new Date();
  const cachePath = join(options.configDirectory ?? defaultConfigDirectory(), "update-check.json");
  if (!options.force) {
    const cached = await readCache(cachePath);
    if (cached && now.getTime() - Date.parse(cached.checkedAt) < UPDATE_CHECK_INTERVAL_MS) {
      return statusFromCache(options.currentVersion, cached, true);
    }
  }

  let latestVersion: string | undefined;
  try {
    const response = await (options.fetchImpl ?? fetch)(REGISTRY_URL, {
      headers: { accept: "application/json", "user-agent": `sustech-cli/${options.currentVersion}` },
      signal: AbortSignal.timeout(3_000),
    });
    if (!response.ok) throw new Error(`Registry returned HTTP ${response.status}.`);
    const body = await response.json() as { version?: unknown };
    if (typeof body.version === "string" && parseStableVersion(body.version)) latestVersion = body.version;
  } catch {
    // Update checks must never make the requested CLI command fail.
  }
  const cache: UpdateCache = { schemaVersion: "1", checkedAt: now.toISOString(), ...(latestVersion ? { latestVersion } : {}) };
  await writeJsonAtomically(cachePath, cache).catch(() => undefined);
  return statusFromCache(options.currentVersion, cache, false);
}

export async function installLatest(packageRoot: string, showInstallerOutput = true): Promise<"source" | "npm"> {
  if (await exists(join(packageRoot, ".git"))) {
    const branch = (await runCaptured("git", ["-C", packageRoot, "branch", "--show-current"])).trim();
    const dirty = (await runCaptured("git", ["-C", packageRoot, "status", "--porcelain"])).trim();
    if (branch !== "main" || dirty) {
      throw new Error("Source checkout must be on a clean main branch before it can update itself.");
    }
    await runCommand("git", ["-C", packageRoot, "pull", "--ff-only"], showInstallerOutput);
    await runCommand(npmExecutable(), ["--prefix", packageRoot, "ci"], showInstallerOutput);
    return "source";
  }
  await runCommand(npmExecutable(), ["install", "--global", "sustech-cli@latest"], showInstallerOutput);
  return "npm";
}

function parseStableVersion(value: string): [number, number, number] | undefined {
  const match = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(value.trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : undefined;
}

function statusFromCache(currentVersion: string, cache: UpdateCache, cached: boolean): UpdateStatus {
  return {
    currentVersion,
    ...(cache.latestVersion ? { latestVersion: cache.latestVersion } : {}),
    updateAvailable: cache.latestVersion ? isNewerVersion(cache.latestVersion, currentVersion) : false,
    checkedAt: cache.checkedAt,
    cached,
  };
}

async function readCache(path: string): Promise<UpdateCache | undefined> {
  try {
    const value = JSON.parse(await readFile(path, "utf8")) as Partial<UpdateCache>;
    if (value.schemaVersion === "1" && typeof value.checkedAt === "string" && Number.isFinite(Date.parse(value.checkedAt))) {
      return { schemaVersion: "1", checkedAt: value.checkedAt, ...(typeof value.latestVersion === "string" ? { latestVersion: value.latestVersion } : {}) };
    }
  } catch {
    // A missing or invalid cache simply causes a fresh check.
  }
  return undefined;
}

async function exists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch {
    return false;
  }
}

async function runCaptured(command: string, args: string[]): Promise<string> {
  const result = await execFileAsync(command, args, { encoding: "utf8" });
  return result.stdout;
}

async function runCommand(command: string, args: string[], showOutput: boolean): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(command, args, { stdio: showOutput ? "inherit" : "ignore", shell: false });
    child.once("error", reject);
    child.once("exit", (code, signal) => code === 0 ? resolve() : reject(new Error(`${command} failed${signal ? ` with ${signal}` : ` with exit code ${code ?? "unknown"}`}.`)));
  });
}

function npmExecutable(): string {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}
