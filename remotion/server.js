/**
 * Remotion Render Server
 * HTTP API for triggering video renders from other services.
 *
 * POST /render
 *   Body: { compositionId, props, outputPath }
 *   Returns: { success, outputPath, error? }
 *
 * GET /health
 *   Returns: { status: "ok" }
 */

import { spawn } from "child_process";
import { createServer } from "http";
import { existsSync, mkdirSync, readFileSync } from "fs";
import { dirname, extname, resolve as pathResolve, join } from "path";

const PUBLIC_DIR = pathResolve(import.meta.dirname ?? "/app", "public");

const MIME_TYPES = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg",
  ".mp4": "video/mp4",
};

const PORT = process.env.PORT || 3100;
const MAX_BODY_BYTES = 1024 * 1024; // 1 MB
const RENDERS_DIR = "/renders";

const VALID_COMPOSITIONS = new Set([
  "StreamIntro",
  "SH-StreamIntro",
  "EpisodeCard",
  "SH-EpisodeCard",
  "EpisodeOutro",
  "SH-EpisodeOutro",
  "HoldingScreen",
  "SH-HoldingScreen",
  "NarratedSegment",
  "SH-NarratedSegment",
]);

/**
 * Run a Remotion render command.
 */
async function renderVideo(compositionId, props, outputPath) {
  // Validate compositionId against whitelist
  if (!VALID_COMPOSITIONS.has(compositionId)) {
    throw new Error(`Unknown compositionId: ${compositionId}`);
  }

  // Validate outputPath stays within /renders/
  const resolved = pathResolve(outputPath);
  if (!resolved.startsWith(RENDERS_DIR + "/")) {
    throw new Error(`outputPath must be under ${RENDERS_DIR}/`);
  }

  // Ensure output directory exists
  const outDir = dirname(resolved);
  if (!existsSync(outDir)) {
    mkdirSync(outDir, { recursive: true });
  }

  const propsJson = JSON.stringify(props);
  const args = [
    "npx",
    "remotion",
    "render",
    "src/index.ts",
    compositionId,
    resolved,
    `--props=${propsJson}`,
    "--log=verbose",
  ];

  console.log(`Rendering: ${compositionId} -> ${outputPath}`);
  console.log(`Props: ${propsJson}`);

  return new Promise((resolve, reject) => {
    const proc = spawn(args[0], args.slice(1), {
      cwd: "/app",
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, FORCE_COLOR: "0" },
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (data) => {
      stdout += data.toString();
      process.stdout.write(data);
    });

    proc.stderr.on("data", (data) => {
      stderr += data.toString();
      process.stderr.write(data);
    });

    proc.on("close", (code) => {
      if (code === 0) {
        resolve({ success: true, outputPath });
      } else {
        reject(new Error(`Render failed with code ${code}: ${stderr}`));
      }
    });

    proc.on("error", (err) => {
      reject(err);
    });
  });
}

/**
 * Parse JSON body from request.
 */
async function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    let bytes = 0;
    req.on("data", (chunk) => {
      bytes += chunk.length;
      if (bytes > MAX_BODY_BYTES) {
        req.destroy();
        return reject(new Error("Request body too large"));
      }
      body += chunk;
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(body));
      } catch (e) {
        reject(new Error("Invalid JSON"));
      }
    });
    req.on("error", reject);
  });
}

/**
 * Send JSON response.
 */
function sendJson(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

/**
 * HTTP request handler.
 */
async function handleRequest(req, res) {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  // Health check
  if (req.method === "GET" && url.pathname === "/health") {
    return sendJson(res, 200, { status: "ok" });
  }

  // Render endpoint
  if (req.method === "POST" && url.pathname === "/render") {
    try {
      const body = await parseBody(req);
      const { compositionId, props, outputPath } = body;

      if (!compositionId || !outputPath) {
        return sendJson(res, 400, {
          success: false,
          error: "Missing compositionId or outputPath",
        });
      }

      const result = await renderVideo(compositionId, props || {}, outputPath);
      return sendJson(res, 200, result);
    } catch (err) {
      console.error("Render error:", err);
      const status = err.message.startsWith("Unknown compositionId") ||
                     err.message.startsWith("outputPath must be") ||
                     err.message === "Request body too large" ? 400 : 500;
      return sendJson(res, status, { success: false, error: err.message });
    }
  }

  // List available compositions
  if (req.method === "GET" && url.pathname === "/compositions") {
    return sendJson(res, 200, {
      compositions: [...VALID_COMPOSITIONS],
    });
  }

  // Game state endpoint (reads from mounted clawd-twitch workspace)
  if (req.method === "GET" && url.pathname === "/game/state") {
    const statePath = process.env.RPG_STATE_FILE || "/home/node/.clawdbot/rpg/state/game-state.json";
    try {
      const data = readFileSync(statePath, "utf-8");
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(data);
    } catch {
      return sendJson(res, 404, { error: "No active game state" });
    }
  }

  // Serve static files from public/ (includes game/maps/, game/crawl.html, etc.)
  if (req.method === "GET") {
    const safePath = url.pathname.replace(/\.\./g, "");
    const filePath = join(PUBLIC_DIR, safePath);
    if (filePath.startsWith(PUBLIC_DIR) && existsSync(filePath)) {
      const ext = extname(filePath);
      const mime = MIME_TYPES[ext] || "application/octet-stream";
      try {
        const content = readFileSync(filePath);
        res.writeHead(200, { "Content-Type": mime });
        return res.end(content);
      } catch {
        // fall through to 404
      }
    }
  }

  // 404 for everything else
  sendJson(res, 404, { error: "Not found" });
}

// Start server
const server = createServer(handleRequest);
server.listen(PORT, () => {
  console.log(`Remotion render server listening on port ${PORT}`);
});
