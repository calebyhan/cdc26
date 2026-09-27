import "server-only";

/**
 * Gemini API transport for the in-app guide (server only).
 * Mirrors src/not_my_debt/gemini_adapter.py: a same-provider model chain that
 * skips models whose free-tier quota is exhausted. Errors never include
 * prompts, user messages, or the key.
 */

const API_URL =
  "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent";
const DEFAULT_MODELS = [
  "gemini-flash-latest",
  "gemini-3.8-flash",
  "gemini-3.7-flash",
  "gemini-flash-lite-latest",
  "gemini-3.1-flash-lite",
  "gemini-3.5-flash",
];
const BUSY = new Set([500, 502, 503, 504]);
// Process-local memory of models that returned 429 (public config, not user data).
const exhaustedUntil = new Map<string, number>();

export class GeminiError extends Error {}

export const geminiAvailable = () => Boolean(process.env.GEMINI_API_KEY);

function models() {
  const configured = (process.env.GEMINI_MODELS || "")
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean);
  return configured.length ? configured : DEFAULT_MODELS;
}

export type Part = Record<string, unknown>;
export type Content = { role: "user" | "model"; parts: Part[] };

export async function generate(
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<{ content: Content; model: string }> {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new GeminiError("Add GEMINI_API_KEY to use the guide.");
  let quotaHit = false;
  for (const model of models()) {
    if ((exhaustedUntil.get(model) ?? 0) > Date.now()) {
      quotaHit = true;
      continue;
    }
    for (let attempt = 0; attempt < 2; attempt++) {
      let status = 0;
      try {
        const response = await fetch(API_URL.replace("{model}", model), {
          method: "POST",
          headers: { "Content-Type": "application/json", "x-goog-api-key": key },
          body: JSON.stringify(body),
          cache: "no-store",
          signal: signal ?? AbortSignal.timeout(60_000),
        });
        status = response.status;
        if (response.ok) {
          const data = await response.json();
          const content = data?.candidates?.[0]?.content as Content | undefined;
          if (!content?.parts) throw new GeminiError("The guide returned no answer.");
          return { content: { role: "model", parts: content.parts }, model };
        }
      } catch (error) {
        if (error instanceof GeminiError) throw error;
        if (signal?.aborted) throw new GeminiError("Request cancelled.");
      }
      if (status === 429) {
        quotaHit = true;
        exhaustedUntil.set(model, Date.now() + 10 * 60_000);
        break;
      }
      if (status === 404) break;
      if (status && !BUSY.has(status))
        throw new GeminiError(`The guide request was rejected (${status}).`);
      await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
    }
  }
  throw new GeminiError(
    quotaHit
      ? "The Gemini usage limit for this API key was reached. Try again later or enable billing."
      : "Gemini is busy right now. Please try again in a moment.",
  );
}
