"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CircleAlert,
  FileText,
  FolderOpen,
  Loader2,
  Plus,
  RotateCcw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  api,
  type Bootstrap,
  type Document,
  type ExtractionMethod,
} from "@/lib/types";

export type UploadedRecord = { document: Document; file: File };

type QueueItem = {
  id: string;
  file: File;
  kind: string;
  status: "queued" | "reading" | "done" | "error";
  document?: Document;
  error?: string;
  validationError?: string;
};

const MAX_FILES = 16;
const MAX_BYTES = 8 * 1024 * 1024;

function suggestKind(filename: string) {
  const name = filename.toLowerCase().replace(/[^a-z0-9]+/g, " ");
  if (/\b(collection|collections|collector|notice|dunning)\b/.test(name))
    return "collection";
  if (/\b(eob|insurance|benefits)\b/.test(name)) return "eob";
  if (/\b(receipt|payment|paid)\b/.test(name)) return "receipt";
  if (/\b(bill|billing|invoice|statement)\b/.test(name)) return "bill";
  return "";
}

function fileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileError(file: File) {
  if (!/\.(pdf|txt|md)$/i.test(file.name))
    return "Choose a PDF, TXT, or MD file.";
  if (file.size === 0)
    return "This file is empty. Choose a file with document text.";
  if (file.size > MAX_BYTES)
    return "This file exceeds 8 MB. Choose a smaller copy.";
  return undefined;
}

function readBase64(file: File, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const cleanup = () => signal.removeEventListener("abort", cancel);
    const cancel = () => {
      reader.abort();
      cleanup();
      reject(new DOMException("Document reading cancelled", "AbortError"));
    };
    reader.onload = () => {
      cleanup();
      if (signal.aborted) {
        reject(new DOMException("Document reading cancelled", "AbortError"));
        return;
      }
      const contents = String(reader.result || "");
      const comma = contents.indexOf(",");
      if (comma < 0)
        reject(new Error("This file could not be read. Choose it again."));
      else resolve(contents.slice(comma + 1));
    };
    reader.onerror = () => {
      cleanup();
      reject(new Error("This file could not be read. Choose it again."));
    };
    reader.onabort = () => {
      cleanup();
      reject(new DOMException("Document reading cancelled", "AbortError"));
    };
    if (signal.aborted) {
      cancel();
      return;
    }
    signal.addEventListener("abort", cancel, { once: true });
    reader.readAsDataURL(file);
  });
}

export function UploadCase({
  boot,
  onComplete,
  onExample,
}: {
  boot: Bootstrap;
  onComplete: (records: UploadedRecord[]) => void;
  onExample: () => void;
}) {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [method, setMethod] = useState<ExtractionMethod>(
    boot.codex_available ? "codex" : boot.ai_available ? "openai" : "local",
  );
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState("");
  const [attempted, setAttempted] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const batch = useRef({
    sequence: 0,
    controller: null as AbortController | null,
    running: false,
  });

  useEffect(() => {
    const active = batch.current;
    return () => {
      active.sequence += 1;
      active.controller?.abort();
      active.controller = null;
      active.running = false;
    };
  }, []);

  const availability: Record<ExtractionMethod, boolean> = {
    local: true,
    codex: boot.codex_available,
    openai: boot.ai_available,
  };
  const successes = queue.filter(
    (item) => item.status === "done" && item.document,
  );
  const errors = queue.filter((item) => item.status === "error");
  const remaining = queue.filter(
    (item) => item.status !== "done" && !item.validationError,
  );
  const missingKind = remaining.some((item) => !item.kind);
  const onlyRetries =
    remaining.length > 0 && remaining.every((item) => item.status === "error");
  const canRead =
    !busy && remaining.length > 0 && !missingKind && availability[method];

  function addFiles(files: File[]) {
    if (batch.current.running || files.length === 0) return;
    setMessage("");
    if (queue.length + files.length > MAX_FILES) {
      setMessage(
        `You can add up to ${MAX_FILES} documents. Remove a file or choose fewer to add.`,
      );
      return;
    }
    const additions = files.map((file): QueueItem => {
      const validationError = fileError(file);
      const suggestion = suggestKind(file.name);
      return {
        id: crypto.randomUUID(),
        file,
        kind: suggestion in boot.kinds ? suggestion : "",
        status: validationError ? "error" : "queued",
        validationError,
        error: validationError,
      };
    });
    setQueue((current) => [...current, ...additions]);
  }

  function changeKind(id: string, kind: string) {
    if (batch.current.running) return;
    setQueue((current) =>
      current.map((item) =>
        item.id === id
          ? {
              ...item,
              kind,
              status: item.validationError ? "error" : "queued",
              document: undefined,
              error: item.validationError,
            }
          : item,
      ),
    );
  }

  function removeFile(id: string) {
    if (batch.current.running) return;
    setQueue((current) => current.filter((item) => item.id !== id));
    setMessage("");
  }

  function completedRecords(items: QueueItem[]): UploadedRecord[] {
    return items.flatMap((item) =>
      item.status === "done" && item.document
        ? [{ document: item.document, file: item.file }]
        : [],
    );
  }

  async function readDocuments() {
    const active = batch.current;
    if (active.running || !canRead) return;
    const selectedMethod = method;
    const controller = new AbortController();
    const sequence = ++active.sequence;
    active.controller = controller;
    active.running = true;
    setBusy(true);
    setAttempted(true);
    setMessage("");
    let nextQueue = queue.map((item) => ({ ...item }));
    const current = () =>
      !controller.signal.aborted && active.sequence === sequence;
    const update = (id: string, patch: Partial<QueueItem>) => {
      nextQueue = nextQueue.map((item) =>
        item.id === id ? { ...item, ...patch } : item,
      );
      if (current()) setQueue(nextQueue);
    };
    try {
      // Completed records remain untouched. A retry only sends the failed records;
      // records newly added by the user are read on their next explicit click.
      for (const item of remaining) {
        if (!current()) return;
        update(item.id, { status: "reading", error: undefined });
        try {
          const encoded = await readBase64(item.file, controller.signal);
          if (!current()) return;
          const response = await api<{ document: Document }>(
            {
              operation: "extract",
              kind: item.kind,
              title:
                item.file.name.replace(/\.[^.]+$/, "").slice(0, 180) ||
                "Uploaded document",
              method: selectedMethod,
              file: encoded,
              filename: item.file.name,
            },
            controller.signal,
          );
          if (!current()) return;
          const document: Document = {
            ...response.document,
            id: `${response.document.id}-${item.id.slice(0, 8)}`,
            fields: Object.fromEntries(
              Object.entries(response.document.fields).map(([key, fact]) => [
                key,
                { ...fact, confirmed: false },
              ]),
            ),
          };
          update(item.id, { status: "done", document, error: undefined });
        } catch (cause) {
          if (!current()) return;
          update(item.id, {
            status: "error",
            document: undefined,
            error:
              cause instanceof Error
                ? cause.message
                : "Could not read this file. Try again.",
          });
        }
      }
      if (
        current() &&
        nextQueue.length > 0 &&
        nextQueue.every((item) => item.status === "done")
      ) {
        onComplete(completedRecords(nextQueue));
      }
    } finally {
      if (current()) {
        active.running = false;
        active.controller = null;
        setBusy(false);
      }
    }
  }

  return (
    <section className="nmd-upload-case" aria-labelledby="upload-case-title">
      <div className="nmd-upload-heading">
        <span className="nmd-upload-eyebrow">YOUR MEDICAL BILLS</span>
        <h1 id="upload-case-title">Start with your documents</h1>
        <p>
          Add your bill, insurance explanation, payment receipt, and collection
          notice. We’ll read the details for you to review.
        </p>
      </div>
      <div className="nmd-upload-steps" aria-label="Case workflow">
        <span className="active">
          <i>1</i> Upload documents
        </span>
        <ArrowRight size={13} aria-hidden="true" />
        <span>
          <i>2</i> Review the details
        </span>
        <ArrowRight size={13} aria-hidden="true" />
        <span>
          <i>3</i> See what happened
        </span>
      </div>

      <div
        className={`nmd-upload-dropzone ${dragging ? "nmd-upload-dragging" : ""} ${busy ? "nmd-upload-disabled" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!busy) addFiles(Array.from(event.dataTransfer.files));
        }}
      >
        <div className="nmd-upload-drop-icon">
          <Upload size={25} aria-hidden="true" />
        </div>
        <h2>Bring the records together</h2>
        <p>Drop files here, or choose them from your computer.</p>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          <Plus size={16} aria-hidden="true" /> Choose documents
        </button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept=".pdf,.txt,.md"
          disabled={busy}
          aria-label="Choose medical billing documents"
          onChange={(event) => {
            addFiles(Array.from(event.target.files || []));
            event.target.value = "";
          }}
        />
        <small>PDF, TXT, or MD · Up to 16 files · 8 MB each</small>
        <span className="nmd-upload-scan-note">
          PDFs need selectable text. For scans or photos, upload a
          transcription.
        </span>
      </div>
      {message && (
        <p className="nmd-upload-error" role="alert">
          {message}
        </p>
      )}

      {queue.length > 0 && (
        <div className="nmd-upload-queue" aria-label="Document queue">
          <div className="nmd-upload-queue-heading">
            <h2>
              {queue.length} {queue.length === 1 ? "document" : "documents"}
            </h2>
            <span>
              {busy ? `${successes.length} read` : "Check each document type"}
            </span>
          </div>
          <ol>
            {queue.map((item) => (
              <li
                className={`nmd-upload-item nmd-upload-item-${item.status}`}
                key={item.id}
              >
                <div className="nmd-upload-file-icon">
                  {item.status === "reading" ? (
                    <Loader2 size={19} className="spin" aria-hidden="true" />
                  ) : item.status === "done" ? (
                    <Check size={19} aria-hidden="true" />
                  ) : item.status === "error" ? (
                    <CircleAlert size={19} aria-hidden="true" />
                  ) : (
                    <FileText size={19} aria-hidden="true" />
                  )}
                </div>
                <div className="nmd-upload-file-info">
                  <strong title={item.file.name}>{item.file.name}</strong>
                  <small>
                    {fileSize(item.file.size)} ·{" "}
                    {item.status === "reading"
                      ? "Reading…"
                      : item.status === "done"
                        ? "Ready for review"
                        : item.status === "error"
                          ? "Couldn’t read"
                          : "Waiting to read"}
                  </small>
                  {item.status === "done" && item.document && (
                    <span className="nmd-upload-field-count">
                      {Object.keys(item.document.fields).length > 0
                        ? `${Object.keys(item.document.fields).length} values to review`
                        : "No labeled values found. Add them during review."}
                    </span>
                  )}
                  {item.error && (
                    <p className="nmd-upload-file-error">{item.error}</p>
                  )}
                </div>
                <div className="nmd-upload-role">
                  <label htmlFor={`upload-role-${item.id}`}>
                    Document type
                  </label>
                  <select
                    id={`upload-role-${item.id}`}
                    value={item.kind}
                    disabled={busy || !!item.validationError}
                    onChange={(event) =>
                      changeKind(item.id, event.target.value)
                    }
                    aria-required={!item.validationError}
                  >
                    <option value="">Choose a type</option>
                    {Object.entries(boot.kinds).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  className="nmd-upload-remove"
                  disabled={busy}
                  onClick={() => removeFile(item.id)}
                  aria-label={`Remove ${item.file.name}`}
                  title="Remove document"
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="nmd-upload-read-panel">
        <div className="nmd-upload-method">
          <label htmlFor="upload-extraction-method">Read with</label>
          <select
            id="upload-extraction-method"
            value={method}
            disabled={busy}
            onChange={(event) =>
              setMethod(event.target.value as ExtractionMethod)
            }
            aria-describedby="upload-extraction-disclosure"
          >
            <option value="codex" disabled={!availability.codex}>
              Codex (ChatGPT sign-in)
            </option>
            <option value="openai" disabled={!availability.openai}>
              OpenAI API
            </option>
            <option value="local">Local parser</option>
          </select>
        </div>
        <div className="nmd-upload-read-copy">
          <p id="upload-extraction-disclosure">
            {method === "codex"
              ? "Sends document text to OpenAI using your ChatGPT sign-in and usage allowance."
              : method === "openai"
                ? "Sends document text to OpenAI. API usage is billed separately."
                : "Reads fields in “Label: value” format, such as “Balance: 150.00.”"}
          </p>
          <small>You’ll check the values before creating your timeline.</small>
        </div>
        <button
          type="button"
          className="button primary"
          disabled={!canRead}
          onClick={readDocuments}
        >
          {busy ? (
            <Loader2 className="spin" size={16} aria-hidden="true" />
          ) : onlyRetries ? (
            <RotateCcw size={16} aria-hidden="true" />
          ) : (
            <FileText size={16} aria-hidden="true" />
          )}
          {busy
            ? "Reading documents…"
            : onlyRetries
              ? "Retry failed documents"
              : successes.length
                ? "Read remaining documents"
                : "Read documents"}
        </button>
      </div>
      {!availability[method] && (
        <p className="nmd-upload-guidance" role="alert">
          This method is unavailable. Choose another method or check its setup.
        </p>
      )}
      {missingKind && !busy && (
        <p className="nmd-upload-guidance">
          Choose a type for each document before reading.
        </p>
      )}
      {busy && (
        <p className="nmd-upload-progress" role="status">
          Reading one document at a time. You can review the details when the
          files are ready.
        </p>
      )}
      {!busy && attempted && errors.length > 0 && (
        <p className="nmd-upload-guidance" role="status">
          {successes.length > 0
            ? `${successes.length} ${successes.length === 1 ? "document is" : "documents are"} ready for review. `
            : ""}
          {errors.length} {errors.length === 1 ? "file needs" : "files need"}{" "}
          another look. Retry or remove the files above.
        </p>
      )}
      {!busy && attempted && successes.length > 0 && (
        <div className="nmd-upload-partial">
          <div>
            <strong>Continue with the files that are ready</strong>
            <p>
              {queue.length > successes.length
                ? "The remaining files won’t be added to this case."
                : "Review the details before creating your timeline."}
            </p>
          </div>
          <button
            type="button"
            className="button secondary"
            onClick={() => onComplete(completedRecords(queue))}
          >
            Continue with {successes.length}{" "}
            {successes.length === 1 ? "document" : "documents"}{" "}
            <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
      )}
      <div className="nmd-upload-example">
        <FolderOpen size={16} aria-hidden="true" />
        <span>Want to see how it works first?</span>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={onExample}
        >
          Open an example <ArrowRight size={13} aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
