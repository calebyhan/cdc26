import { readFile } from "node:fs/promises";
import path from "node:path";
import manifest from "@/sample_documents/manifest.json";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Public, fictional assets only. Private uploads are never persisted or served. */
export async function GET(request: Request) {
  const filename = new URL(request.url).searchParams.get("file");
  if (!filename || !Object.hasOwn(manifest.files, filename)) {
    return new Response("Demo document not found.", { status: 404 });
  }
  try {
    const bytes = await readFile(
      path.join(process.cwd(), "sample_documents", filename),
    );
    return new Response(new Uint8Array(bytes), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${path.basename(filename)}"`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new Response("Demo document unavailable.", { status: 404 });
  }
}
