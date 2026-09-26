import { spawn } from "node:child_process";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store, private" };
const MAX_BYTES = 14 * 1024 * 1024;
// Allow the supported 300-second Codex call, its 10-second auth check, and cleanup.
const ENGINE_TIMEOUT_MS = 330_000;

function runEngine(body: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const python =
      process.env.NMD_PYTHON ||
      path.join(process.cwd(), ".venv", "bin", "python");
    const processGroup = process.platform !== "win32";
    const child = spawn(
      /* turbopackIgnore: true */ python,
      ["-m", "not_my_debt.web_bridge"],
      {
        cwd: process.cwd(),
        env: { ...process.env, PYTHONPATH: path.join(process.cwd(), "src") },
        stdio: ["pipe", "pipe", "ignore"],
        // On POSIX, keep Python and any Codex subprocess in one killable group.
        detached: processGroup,
      },
    );
    let output = "";
    let finished = false;
    const timer = setTimeout(() => fail("timeout", true), ENGINE_TIMEOUT_MS);

    function fail(message: string, terminate = false) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      output = "";
      if (terminate) {
        try {
          if (processGroup && child.pid) process.kill(-child.pid, "SIGKILL");
          else child.kill("SIGKILL");
        } catch {
          // The process may already have exited between the event and cleanup.
          child.kill("SIGKILL");
        }
      }
      reject(new Error(message));
    }

    child.on("error", () => {
      fail("engine unavailable", true);
    });
    child.stdin.on("error", () => {
      /* close/error handlers report a generic failure */
    });
    child.stdout.on("data", (chunk: Buffer) => {
      if (finished) return;
      output += chunk.toString();
      if (Buffer.byteLength(output) > MAX_BYTES) {
        fail("too much output", true);
      }
    });
    child.on("close", (code) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (code !== 0) return reject(new Error("engine failed"));
      try {
        resolve(JSON.parse(output));
      } catch {
        reject(new Error("invalid output"));
      }
    });
    child.stdin.end(body);
  });
}

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      if (new URL(origin).host !== request.headers.get("host"))
        throw new Error("origin mismatch");
    } catch {
      return Response.json(
        { error: "Use the app to submit this request." },
        { status: 403, headers },
      );
    }
  }
  if (Number(request.headers.get("content-length") || 0) > MAX_BYTES) {
    return Response.json(
      { error: "Use a file smaller than 8 MB." },
      { status: 413, headers },
    );
  }
  try {
    const body = await request.text();
    if (Buffer.byteLength(body) > MAX_BYTES)
      return Response.json(
        { error: "This case is too large." },
        { status: 413, headers },
      );
    const result = await runEngine(body);
    return Response.json(result, { status: result.error ? 400 : 200, headers });
  } catch (error) {
    const timedOut = error instanceof Error && error.message === "timeout";
    return Response.json(
      {
        error: timedOut
          ? "The evidence engine timed out. Retry or explicitly choose Local parser."
          : "The evidence engine is unavailable. Run uv sync and retry.",
      },
      { status: timedOut ? 504 : 503, headers },
    );
  }
}
