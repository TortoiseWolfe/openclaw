/**
 * .env file read/update/write utility.
 *
 * Parses an existing .env file, updates specific keys (preserving comments,
 * ordering, and unmodified lines), and writes back atomically.
 *
 * Used by the Twitch onRefresh callback to persist refreshed tokens.
 */

import fs from "node:fs";
import path from "node:path";
import { resolveConfigDir } from "../utils.js";

export type DotEnvUpdateEntry = {
  key: string;
  value: string;
};

/**
 * Parse a .env file into lines, preserving comments and blanks.
 * Returns the raw lines and a map of key -> line index for fast lookup.
 */
function parseDotEnvLines(content: string): {
  lines: string[];
  keyIndex: Map<string, number>;
} {
  const lines = content.split("\n");
  const keyIndex = new Map<string, number>();

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith("#")) continue;
    const eqIndex = line.indexOf("=");
    if (eqIndex > 0) {
      const key = line.slice(0, eqIndex).trim();
      keyIndex.set(key, i);
    }
  }

  return { lines, keyIndex };
}

/**
 * Format a KEY=VALUE line for .env.
 * Values containing spaces, #, or quotes are wrapped in double quotes.
 */
function formatEnvLine(key: string, value: string): string {
  const needsQuoting = /[\s#"'\\]/.test(value);
  if (needsQuoting) {
    const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return `${key}="${escaped}"`;
  }
  return `${key}=${value}`;
}

/**
 * Update specific keys in a .env file. Creates the file if it does not exist.
 * Preserves all other content (comments, ordering, unmodified keys).
 *
 * Uses atomic write (write to tmp, then rename) for safety.
 */
export async function updateDotEnvFile(
  envPath: string,
  updates: DotEnvUpdateEntry[],
): Promise<void> {
  let content = "";
  try {
    content = await fs.promises.readFile(envPath, "utf-8");
  } catch (err) {
    const code = (err as { code?: string }).code;
    if (code !== "ENOENT") throw err;
  }

  const { lines, keyIndex } = parseDotEnvLines(content);

  for (const { key, value } of updates) {
    const existingIndex = keyIndex.get(key);
    const newLine = formatEnvLine(key, value);

    if (existingIndex !== undefined) {
      lines[existingIndex] = newLine;
    } else {
      lines.push(newLine);
    }
  }

  const output = lines.join("\n").replace(/\n*$/, "\n");

  const dir = path.dirname(envPath);
  await fs.promises.mkdir(dir, { recursive: true, mode: 0o700 });

  const tmp = `${envPath}.${process.pid}.tmp`;
  await fs.promises.writeFile(tmp, output, { encoding: "utf-8", mode: 0o600 });
  await fs.promises.rename(tmp, envPath);
}

/**
 * Resolve the global .env path: ~/.openclaw/.env
 */
export function resolveGlobalDotEnvPath(
  env: NodeJS.ProcessEnv = process.env,
): string {
  return path.join(resolveConfigDir(env), ".env");
}
