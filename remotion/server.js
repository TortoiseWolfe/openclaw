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
import { timingSafeEqual } from "crypto";
import {
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
} from "fs";
import { basename, dirname, extname, resolve as pathResolve, sep } from "path";

const PUBLIC_DIR = pathResolve(import.meta.dirname ?? "/app", "public");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".ogg": "audio/ogg",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};

const PORT = process.env.PORT || 3100;
const MAX_BODY_BYTES = 1024 * 1024; // 1 MB
const RENDERS_DIR = "/renders";
const RENDER_TIMEOUT_MS =
  Number.parseInt(process.env.RENDER_TIMEOUT_MS ?? "", 10) > 0
    ? Number.parseInt(process.env.RENDER_TIMEOUT_MS, 10)
    : 20 * 60 * 1000;
const KILL_GRACE_MS = 10_000;
const MAX_WAITING = 3;
const STDERR_TAIL_BYTES = 64 * 1024;

const ALLOWED_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "remotion-renderer",
  "host.docker.internal",
]);

const OUTPUT_NAME_RE = /^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,120}\.(mp4|png|jpg|jpeg|webm|mov)$/;

// The overlay and crawl pages load nothing from other origins. They use inline
// <script>/<style> blocks and inline style="" attributes, so those two need
// 'unsafe-inline'. Everything else is locked to same-origin.
const HTML_CSP = [
  "default-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "media-src 'self'",
  "font-src 'self'",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");

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
  "HighlightTitle",
  "SH-HighlightTitle",
]);

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/** Hostname from a Host header: lowercase, port stripped, [::1] unwrapped. */
function hostnameOf(hostHeader) {
  if (typeof hostHeader !== "string" || hostHeader === "") return "";
  const h = hostHeader.trim().toLowerCase();
  if (h.startsWith("[")) {
    const end = h.indexOf("]");
    return end === -1 ? "" : h.slice(1, end);
  }
  const colon = h.lastIndexOf(":");
  return colon === -1 ? h : h.slice(0, colon);
}

function isInside(child, parent) {
  return child === parent || child.startsWith(parent + sep);
}

/**
 * Validate the output path and make sure its parent really lives under
 * RENDERS_DIR (symlinks resolved). Returns the resolved output path.
 */
function validateOutputPath(outputPath) {
  if (typeof outputPath !== "string" || outputPath.includes("\0")) {
    throw new HttpError(400, `outputPath must be under ${RENDERS_DIR}/`);
  }
  const resolved = pathResolve(outputPath);
  if (!resolved.startsWith(RENDERS_DIR + "/")) {
    throw new HttpError(400, `outputPath must be under ${RENDERS_DIR}/`);
  }
  if (!OUTPUT_NAME_RE.test(basename(resolved))) {
    throw new HttpError(400, "outputPath has an invalid file name or extension");
  }
  const outDir = dirname(resolved);
  try {
    mkdirSync(outDir, { recursive: true });
    const realDir = realpathSync(outDir);
    const realRoot = realpathSync(RENDERS_DIR);
    if (!isInside(realDir, realRoot)) {
      throw new HttpError(400, `outputPath must be under ${RENDERS_DIR}/`);
    }
  } catch (err) {
    if (err instanceof HttpError) throw err;
    throw new HttpError(400, `outputPath must be under ${RENDERS_DIR}/`);
  }
  return resolved;
}

function validateProps(props) {
  if (props === undefined || props === null) return {};
  if (typeof props !== "object" || Array.isArray(props)) {
    throw new HttpError(400, "props must be an object");
  }
  if (props.durationInFrames !== undefined) {
    const d = props.durationInFrames;
    if (!Number.isInteger(d) || d < 1 || d > 18000) {
      throw new HttpError(400, "props.durationInFrames must be an integer 1..18000");
    }
  }
  return props;
}

// -- Render queue: one at a time, at most MAX_WAITING queued -----------
let renderRunning = false;
const renderWaiting = [];

function enqueueRender(job) {
  return new Promise((resolve, reject) => {
    if (renderRunning && renderWaiting.length >= MAX_WAITING) {
      return reject(new HttpError(429, "render queue full"));
    }
    renderWaiting.push({ job, resolve, reject });
    drainQueue();
  });
}

function drainQueue() {
  if (renderRunning) return;
  const next = renderWaiting.shift();
  if (!next) return;
  renderRunning = true;
  next
    .job()
    .then(next.resolve, next.reject)
    .finally(() => {
      renderRunning = false;
      drainQueue();
    });
}

/**
 * Run a Remotion render command (inputs already validated).
 */
function runRender(compositionId, props, resolved) {
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

  console.log(`Rendering: ${compositionId} -> ${resolved}`);
  console.log(
    `Props: ${Object.keys(props).length} keys [${Object.keys(props).join(",")}], ${Buffer.byteLength(propsJson)} bytes`,
  );

  return new Promise((resolve, reject) => {
    const proc = spawn(args[0], args.slice(1), {
      cwd: "/app",
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, FORCE_COLOR: "0" },
      detached: true, // own process group so the whole npx tree can be signalled
    });

    let stderrTail = Buffer.alloc(0);
    let settled = false;
    let killTimer = null;

    const signalTree = (sig) => {
      try {
        process.kill(-proc.pid, sig);
      } catch {
        try {
          proc.kill(sig);
        } catch {
          /* already gone */
        }
      }
    };

    const timeoutTimer = setTimeout(() => {
      if (settled) return;
      settled = true;
      console.error(`Render timed out after ${RENDER_TIMEOUT_MS} ms; sending SIGTERM`);
      signalTree("SIGTERM");
      killTimer = setTimeout(() => signalTree("SIGKILL"), KILL_GRACE_MS);
      reject(new Error("render timed out"));
    }, RENDER_TIMEOUT_MS);

    proc.stdout.on("data", (data) => {
      process.stdout.write(data);
    });

    proc.stderr.on("data", (data) => {
      stderrTail = Buffer.concat([stderrTail, data]);
      if (stderrTail.length > STDERR_TAIL_BYTES) {
        stderrTail = stderrTail.subarray(stderrTail.length - STDERR_TAIL_BYTES);
      }
      process.stderr.write(data);
    });

    proc.on("close", (code) => {
      clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      if (settled) return;
      settled = true;
      if (code === 0) {
        resolve({ success: true, outputPath: resolved });
      } else {
        console.error(
          `Render failed (exit ${code}); stderr tail (${stderrTail.length} bytes):\n${stderrTail.toString("utf-8")}`,
        );
        reject(new Error(`render failed (exit ${code})`));
      }
    });

    proc.on("error", (err) => {
      clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      if (settled) return;
      settled = true;
      console.error("Render spawn error:", err);
      reject(new Error("render failed (spawn error)"));
    });
  });
}

/** Bearer-token check against RENDERER_TOKEN (constant-time). */
function checkAuth(req) {
  const expected = process.env.RENDERER_TOKEN;
  if (!expected) throw new HttpError(503, "render auth not configured");
  const header = req.headers["authorization"];
  const m = typeof header === "string" ? /^Bearer (.+)$/.exec(header) : null;
  if (!m) throw new HttpError(401, "unauthorized");
  const given = Buffer.from(m[1]);
  const want = Buffer.from(expected);
  if (given.length !== want.length || !timingSafeEqual(given, want)) {
    throw new HttpError(401, "unauthorized");
  }
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
  res.writeHead(status, {
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
  });
  res.end(JSON.stringify(data));
}

/** Resolve a request pathname to a real file inside PUBLIC_DIR, or null. */
function resolveStaticFile(pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    throw new HttpError(400, "Bad URL encoding");
  }
  if (decoded.includes("\0")) return null;
  try {
    const realPublic = realpathSync(PUBLIC_DIR);
    const real = realpathSync(pathResolve(PUBLIC_DIR, "." + decoded));
    if (!real.startsWith(realPublic + sep)) return null;
    if (!statSync(real).isFile()) return null;
    return real;
  } catch {
    return null;
  }
}

/**
 * HTTP request handler.
 */
async function handleRequest(req, res) {
  // DNS-rebinding defence: only answer for known host names.
  if (!ALLOWED_HOSTS.has(hostnameOf(req.headers.host))) {
    return sendJson(res, 403, { error: "Forbidden host" });
  }

  let url;
  try {
    url = new URL(req.url, `http://localhost:${PORT}`);
  } catch {
    return sendJson(res, 400, { error: "Bad request" });
  }

  // Health check
  if (req.method === "GET" && url.pathname === "/health") {
    return sendJson(res, 200, { status: "ok" });
  }

  // Render endpoint
  if (req.method === "POST" && url.pathname === "/render") {
    try {
      checkAuth(req);
      if (!String(req.headers["content-type"] ?? "").toLowerCase().startsWith("application/json")) {
        throw new HttpError(415, "Content-Type must be application/json");
      }
      const body = await parseBody(req);
      const { compositionId, props, outputPath } = body ?? {};

      if (!compositionId || !outputPath) {
        throw new HttpError(400, "Missing compositionId or outputPath");
      }
      if (typeof compositionId !== "string" || !VALID_COMPOSITIONS.has(compositionId)) {
        throw new HttpError(400, "Unknown compositionId");
      }
      const safeProps = validateProps(props);
      const resolved = validateOutputPath(outputPath);

      const result = await enqueueRender(() =>
        runRender(compositionId, safeProps, resolved),
      );
      return sendJson(res, 200, { ...result, outputPath });
    } catch (err) {
      if (err instanceof HttpError) {
        return sendJson(res, err.status, { success: false, error: err.message });
      }
      if (err.message === "Request body too large" || err.message === "Invalid JSON") {
        return sendJson(res, 400, { success: false, error: err.message });
      }
      console.error("Render error:", err.message);
      // Only fixed messages produced by runRender reach the client.
      const safe = err.message === "render timed out" || /^render failed \(/.test(err.message)
        ? err.message
        : "render failed";
      return sendJson(res, 500, { success: false, error: safe });
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
    const statePath = process.env.RPG_STATE_FILE || "/home/node/.openclaw/rpg/state/game-state.json";
    try {
      const data = readFileSync(statePath, "utf-8");
      res.writeHead(200, {
        "Content-Type": "application/json",
        "X-Content-Type-Options": "nosniff",
      });
      return res.end(data);
    } catch {
      return sendJson(res, 404, { error: "No active game state" });
    }
  }

  // Serve static files from public/ (includes game/maps/, game/crawl.html, etc.)
  if (req.method === "GET") {
    try {
      const file = resolveStaticFile(url.pathname);
      if (file) {
        const ext = extname(file).toLowerCase();
        const mime = MIME_TYPES[ext] || "application/octet-stream";
        const headers = {
          "Content-Type": mime,
          "X-Content-Type-Options": "nosniff",
        };
        if (ext === ".html") headers["Content-Security-Policy"] = HTML_CSP;
        const content = readFileSync(file);
        res.writeHead(200, headers);
        return res.end(content);
      }
    } catch (err) {
      if (err instanceof HttpError) {
        return sendJson(res, err.status, { error: err.message });
      }
      // fall through to 404
    }
  }

  // 404 for everything else
  sendJson(res, 404, { error: "Not found" });
}

// Start server
const server = createServer((req, res) => {
  handleRequest(req, res).catch((err) => {
    console.error("Unhandled request error:", err.message);
    if (!res.headersSent) sendJson(res, 500, { error: "Internal error" });
    else res.end();
  });
});
server.listen(PORT, () => {
  console.log(`Remotion render server listening on port ${PORT}`);
});
