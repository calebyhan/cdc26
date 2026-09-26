"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
  FolderOpen,
  Layers,
  Loader2,
  Plus,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
  Upload,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  money,
  shortDate,
  type Analysis,
  type Bootstrap,
  type Document,
  type Fact,
} from "@/lib/types";

import { ChartTooltip } from "@/app/components/chart-tooltip";
import { MoneyWaterfall } from "@/app/components/money-waterfall";
import {
  PatternMatrix,
  ResponseOutcomes,
} from "@/app/components/research-evidence";

const demoPdfUrl = (file: string) =>
  `/api/demo-document?file=${encodeURIComponent(file)}`;

const steps = ["Your case", "Connect the records", "Prepare a response"];
const names: Record<string, string> = {
  eob: "Insurance explanation",
  bill: "Provider bill",
  receipt: "Payment receipt",
  collection: "Collection notice",
};
const amountFields: Record<string, string> = {
  eob: "patient_responsibility",
  bill: "balance",
  receipt: "payment_amount",
  collection: "balance",
};
const captions: Record<string, string> = {
  eob: "Your share, according to insurance",
  bill: "Balance on the provider’s bill",
  receipt: "Payment recorded on the receipt",
  collection: "Amount the collector requests",
};
const confirmedValue = (doc: Document | undefined, key: string) =>
  doc?.fields[key]?.confirmed ? doc.fields[key].value : undefined;
const dollarsFromFact = (doc: Document) => {
  const field = doc.fields[amountFields[doc.kind]];
  if (!field?.confirmed) return "Unknown";
  const raw = field.value.trim().replace(/^\$/, "").replace(/,/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(raw)) return "Unknown";
  const [whole, fraction = ""] = raw.split(".");
  return money(Number(whole) * 100 + Number(fraction.padEnd(2, "0")));
};
type Drawer = { docId?: string; refs?: string[]; edit?: boolean };

export default function Home() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [documentSources, setDocumentSources] = useState<
    Record<string, string>
  >({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [step, setStep] = useState(0);
  const [workspace, setWorkspace] = useState("demo");
  const [scenario, setScenario] = useState("paid");
  const [fictional, setFictional] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const [recipient, setRecipient] = useState<"provider" | "collector">(
    "provider",
  );
  const [letter, setLetter] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api<Bootstrap>({ operation: "bootstrap" }, controller.signal)
      .then((data) => {
        setBoot(data);
        setDocuments(data.examples.paid);
        setDocumentSources(data.document_sources.paid);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (documents === null) return;
    const controller = new AbortController();
    api<Analysis>({ operation: "reconcile", documents }, controller.signal)
      .then((data) => {
        setAnalysis(data);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [documents]);

  function replaceDocuments(docs: Document[]) {
    setDocuments(docs);
    setAnalysis(null);
    setLoading(true);
    setError(null);
    setLetter(null);
    setReviewed(false);
    setExported(false);
  }
  function loadCase(key = "paid") {
    if (!boot) return;
    replaceDocuments(structuredClone(boot.examples[key]));
    setScenario(key);
    setDocumentSources(boot.document_sources[key]);
    setFictional(true);
    setStep(0);
    setWorkspace("demo");
    setDrawer(null);
    setRecipient("provider");
  }
  function toggle(docId: string) {
    if (!documents) return;
    replaceDocuments(
      documents.map((doc) =>
        doc.id === docId ? { ...doc, included: !doc.included } : doc,
      ),
    );
  }
  function go(next: number) {
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  const result = analysis?.result;
  const pending =
    documents
      ?.filter((doc) => doc.included)
      .flatMap((doc) => Object.values(doc.fields))
      .filter((fact) => !fact.confirmed).length || 0;
  const finding = result?.findings.find(
    (item) => item.code === "possible_uncredited_payment",
  );
  const missing = result?.findings.some(
    (item) => item.code === "missing_payment_evidence",
  );
  const reconciled = result?.findings.some(
    (item) => item.code === "no_discrepancy_detected_in_supplied_records",
  );
  const draft = letter ?? analysis?.drafts[recipient] ?? "";
  const source = (refs: string[]) => setDrawer({ refs });
  const notice = documents?.find(
    (doc) => doc.kind === "collection" && doc.included,
  );
  const caseTitle =
    fictional && scenario === "paid"
      ? "She paid her bill.\nThen this arrived."
      : "Every record tells\npart of the story.";

  async function download() {
    if (!documents || !reviewed || loading || pending) return;
    setExporting(true);
    setError(null);
    try {
      const response = await api<{ html: string }>({
        operation: "packet",
        documents,
        recipient,
        letter: draft,
        reviewed,
      });
      const url = URL.createObjectURL(
        new Blob([response.html], { type: "text/html" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "not-my-debt-evidence-packet.html";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExported(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => {
            setWorkspace("demo");
            go(0);
          }}
          aria-label="Not My Debt home"
        >
          <span className="brand-mark">
            <Layers size={20} />
          </span>
          not my debt<span className="brand-dot">.</span>
        </button>
        <div className="sidebar-section">WORKSPACE</div>
        <nav aria-label="Workspace">
          {[
            { id: "demo", name: "Case overview", icon: FolderOpen },
            { id: "evidence", name: "Documents & review", icon: FileCheck2 },
            { id: "research", name: "Complaint research", icon: BarChart3 },
          ].map((item) => (
            <button
              key={item.id}
              className={`nav-item ${workspace === item.id ? "active" : ""}`}
              onClick={() => setWorkspace(item.id)}
            >
              <item.icon size={18} />
              {item.name}
              {workspace === item.id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-case">
          <div className="avatar">{fictional ? "ME" : "YC"}</div>
          <div>
            <strong>{fictional ? "Maya’s case" : "Your case"}</strong>
            <small>
              {fictional
                ? "Fictional presentation demo"
                : "This browser session"}
            </small>
          </div>
        </div>
        <div className="sidebar-bottom">
          <details className="scenario-picker">
            <summary>
              Explore another case <ChevronDown size={14} />
            </summary>
            <label htmlFor="scenario">Fictional scenario</label>
            <select
              id="scenario"
              value={scenario}
              onChange={(e) => loadCase(e.target.value)}
              disabled={!boot}
            >
              {Object.entries(boot?.scenarios || {}).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
            <button
              className="text-button"
              onClick={() => {
                replaceDocuments([]);
                setDocumentSources({});
                setFictional(false);
                setWorkspace("evidence");
              }}
            >
              Start an empty case <ArrowRight size={14} />
            </button>
          </details>
          <button
            className="reset-button"
            onClick={() => loadCase()}
            disabled={!boot}
          >
            <RotateCcw size={15} />
            Reset demo
          </button>
          <div className="privacy-note">
            <ShieldCheck size={16} />
            <span>
              Case records stay in memory.
              <br />
              Nothing is sent or filed.
            </span>
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>Medical billing evidence workspace</span>
          <span className="demo-badge">
            <span />
            {fictional ? "Fictional demo" : "Active session"}
          </span>
        </header>
        {error && (
          <div className="error" role="alert">
            {error}
            <button
              className="text-button"
              onClick={() => window.location.reload()}
            >
              Reload app
            </button>
          </div>
        )}
        {!boot ? (
          <div className="loading-screen">
            <Loader2 className="spin" />
            <h2>
              {error
                ? "The workspace couldn’t load"
                : "Opening the evidence workspace…"}
            </h2>
            <p>Make sure Python dependencies are installed with uv sync.</p>
          </div>
        ) : (
          <>
            {workspace === "demo" && (
              <>
                <nav className="stepper" aria-label="Case steps">
                  {steps.map((label, index) => (
                    <button
                      key={label}
                      onClick={() => go(index)}
                      aria-current={index === step ? "step" : undefined}
                      className={
                        index === step ? "current" : index < step ? "done" : ""
                      }
                    >
                      <span>
                        {index < step ? <Check size={13} /> : `0${index + 1}`}
                      </span>
                      {label}
                      {index < 2 && <i />}
                    </button>
                  ))}
                </nav>
                {step === 0 && (
                  <section className="fade-in">
                    <div className="case-hero">
                      <div>
                        <div className="eyebrow">
                          THE CASE / {fictional ? "MAYA ELLIS" : "YOUR RECORDS"}
                        </div>
                        <h1>{caseTitle}</h1>
                        <p>
                          {fictional && scenario === "paid"
                            ? "A $150 provider bill. A matching payment receipt. And a collection notice asking for the same amount."
                            : "Connect your bill, insurance explanation, payment evidence, and collection notice to understand what needs clarification."}
                        </p>
                        <button
                          className="button primary"
                          onClick={() => go(1)}
                        >
                          Connect the records <ArrowRight size={17} />
                        </button>
                      </div>
                      <div className="notice-preview">
                        <div className="paper-top">
                          <FileText size={18} />
                          <span>{names.collection.toUpperCase()}</span>
                        </div>
                        <div className="paper-issuer">
                          {confirmedValue(notice, "collector") ||
                            "Collection notice"}
                        </div>
                        <div className="paper-rule" />
                        <span className="paper-label">Amount requested</span>
                        <strong>{money(result?.collection_cents)}</strong>
                        <div className="paper-meta">
                          Account{" "}
                          {confirmedValue(notice, "account") || "unconfirmed"}
                          <br />
                          {shortDate(confirmedValue(notice, "statement_date"))}
                        </div>
                        <div className="paper-stamp">
                          {fictional ? "FICTIONAL DOCUMENT" : "SUPPLIED RECORD"}
                        </div>
                      </div>
                    </div>
                    <div className="section-heading">
                      <div>
                        <h2>Four records. One clearer picture.</h2>
                        <p>Open any document to see its original text.</p>
                      </div>
                      <span className="count-label">
                        {documents?.length || 0} documents
                      </span>
                    </div>
                    <div className="document-grid">
                      {documents?.map((doc, index) => (
                        <button
                          className={`document-card ${!doc.included ? "excluded" : ""}`}
                          key={doc.id}
                          onClick={() => setDrawer({ docId: doc.id })}
                        >
                          <div className="document-card-top">
                            <span className={`doc-icon ${doc.kind}`}>
                              <FileText size={20} />
                            </span>
                            <span className="doc-number">0{index + 1}</span>
                          </div>
                          <h3>{names[doc.kind]}</h3>
                          <p>{captions[doc.kind]}</p>
                          <strong>{dollarsFromFact(doc)}</strong>
                          <div className="document-card-footer">
                            <span>
                              {shortDate(confirmedValue(doc, "statement_date"))}
                            </span>
                            <span>
                              {doc.included ? "View source" : "Excluded"}
                              <ArrowRight size={13} />
                            </span>
                          </div>
                        </button>
                      ))}
                    </div>
                    {!documents?.length && (
                      <div className="empty-state">
                        <FolderOpen />
                        <h3>No documents yet</h3>
                        <p>Add documents or reset to Maya’s demo case.</p>
                        <button
                          className="button secondary"
                          onClick={() => setWorkspace("evidence")}
                        >
                          Add documents <Plus size={16} />
                        </button>
                      </div>
                    )}
                    <div className="context-note">
                      <CircleHelp size={17} />
                      <p>
                        The EOB describes patient responsibility. The receipt is
                        the evidence of payment. The app connects them; it does
                        not determine legal liability.
                      </p>
                    </div>
                  </section>
                )}
                {step === 1 && (
                  <section className="fade-in">
                    <div className="page-heading">
                      <div>
                        <div className="eyebrow">FOLLOW THE MONEY</div>
                        <h1>What do the records support?</h1>
                        <p>
                          Trace each amount back to its source. Change the
                          evidence to see the finding change.
                        </p>
                      </div>
                    </div>
                    <div className="receipt-controls">
                      {documents
                        ?.filter((doc) => doc.kind === "receipt")
                        .map((doc) => (
                          <label key={doc.id} className="switch-label">
                            <input
                              type="checkbox"
                              role="switch"
                              checked={doc.included}
                              onChange={() => toggle(doc.id)}
                              aria-label={
                                documents.filter((d) => d.kind === "receipt")
                                  .length === 1
                                  ? "Include payment receipt"
                                  : `Include ${doc.title}`
                              }
                            />
                            <span className="switch-track" />
                            <span>
                              Include payment receipt
                              {documents.filter((d) => d.kind === "receipt")
                                .length > 1
                                ? ` · ${doc.title}`
                                : ""}
                            </span>
                          </label>
                        ))}
                      <span className="muted small">
                        {loading
                          ? "Updating evidence…"
                          : "Findings update with your records"}
                      </span>
                    </div>
                    {loading ? (
                      <div className="finding-banner loading">
                        <Loader2 className="spin" />
                        Checking the supplied records…
                      </div>
                    ) : (
                      <div
                        className={`finding-banner ${finding ? "discrepancy" : reconciled ? "reconciled" : "pending"}`}
                        role="status"
                      >
                        <div className="finding-symbol">
                          {finding ? (
                            <TriangleAlert size={22} />
                          ) : reconciled ? (
                            <CheckCheck size={22} />
                          ) : (
                            <CircleHelp size={22} />
                          )}
                        </div>
                        <div>
                          <span className="eyebrow">
                            {finding
                              ? "POSSIBLE DISCREPANCY"
                              : "EVIDENCE STATUS"}
                          </span>
                          <h2>
                            {finding
                              ? `A ${money(result?.applied_payments_cents)} payment may not have been credited.`
                              : missing
                                ? "Payment evidence is missing."
                                : result?.supported_balance_cents == null
                                  ? "More evidence needs review."
                                  : "Here’s what your records support."}
                          </h2>
                          <p>
                            {finding
                              ? "A completed receipt matches the account and encounter, after the bill and before the notice. Confirm its allocation with the provider."
                              : missing
                                ? "We can’t confirm that this balance was paid. An insurance explanation is not proof of patient payment."
                                : "Review the findings below before drawing conclusions about the balance."}
                          </p>
                          {finding && (
                            <button
                              className="text-button"
                              onClick={() =>
                                source([
                                  ...finding.refs,
                                  ...(documents || [])
                                    .filter((d) =>
                                      result?.matched_document_ids.includes(
                                        d.id,
                                      ),
                                    )
                                    .flatMap((d) =>
                                      [
                                        "account",
                                        "patient",
                                        "provider",
                                        "service_date",
                                        "claim_id",
                                      ]
                                        .filter((k) => d.fields[k])
                                        .map((k) => `${d.id}.${k}`),
                                    ),
                                ])
                              }
                            >
                              Why this payment matches <ArrowRight size={14} />
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                    <div className="analysis-grid money-grid">
                      <div className="panel">
                        <div className="panel-heading">
                          <h2>The money trail</h2>
                          <span>USD</span>
                        </div>
                        <p className="muted small">
                          From the provider statement and matched receipts
                        </p>
                        <div className="ledger">
                          {result?.ledger
                            .filter(
                              (row) =>
                                row.label !==
                                "Balance supported by supplied records",
                            )
                            .map((row) => (
                              <button
                                className="ledger-row"
                                key={row.label}
                                onClick={() => source(row.refs)}
                              >
                                <span>{row.label}</span>
                                <strong>{money(row.cents)}</strong>
                                <ExternalLink size={13} />
                              </button>
                            ))}
                          <div className="ledger-total">
                            <span>Balance supported by these records</span>
                            <strong>
                              {result?.supported_balance_cents == null
                                ? "Withheld"
                                : money(result.supported_balance_cents)}
                            </strong>
                          </div>
                        </div>
                        <p className="footnote">
                          This is a reconstruction, not a live account balance.
                          Later activity or reversals remain unconfirmed.
                        </p>
                      </div>
                      <div className="panel chart-panel">
                        <div className="panel-heading">
                          <h2>Where the money goes</h2>
                          <BarChart3 size={17} />
                        </div>
                        <p className="muted small">
                          Provider arithmetic, then matched payments, beside
                          what the notice requests. Click a bar for its source.
                        </p>
                        {result && (
                          <div className="balance-chart">
                            <MoneyWaterfall
                              result={result}
                              noticeRefs={
                                notice ? [`${notice.id}.balance`] : []
                              }
                              onSelect={source}
                            />
                          </div>
                        )}
                        <div className="comparison-values">
                          <div>
                            <small>Records support</small>
                            <strong>
                              {result?.supported_balance_cents == null
                                ? "Withheld"
                                : money(result.supported_balance_cents)}
                            </strong>
                          </div>
                          <div>
                            <small>Notice requests</small>
                            <strong className="notice-value">
                              {money(result?.collection_cents)}
                            </strong>
                          </div>
                        </div>
                        <p className="footnote">
                          A withheld balance is labeled, never plotted as zero.
                        </p>
                      </div>
                    </div>
                    <details className="findings-details">
                      <summary>
                        All findings & unresolved questions{" "}
                        <span>
                          {result?.findings.length || 0}
                          <ChevronDown size={15} />
                        </span>
                      </summary>
                      {result?.findings.map((item) => (
                        <div className="finding-item" key={item.code}>
                          <h3>{item.title}</h3>
                          <p>{item.detail}</p>
                          {item.refs.length > 0 && (
                            <button
                              className="text-button"
                              onClick={() => source(item.refs)}
                            >
                              Inspect supporting passages{" "}
                              <ArrowRight size={14} />
                            </button>
                          )}
                        </div>
                      ))}
                    </details>
                    <div className="page-actions">
                      <button className="text-button" onClick={() => go(0)}>
                        <ArrowLeft size={15} />
                        Back to the case
                      </button>
                      <button
                        className="button primary"
                        onClick={() => go(2)}
                        disabled={loading}
                      >
                        Prepare a response <ArrowRight size={17} />
                      </button>
                    </div>
                  </section>
                )}
                {step === 2 && (
                  <section className="fade-in">
                    <div className="page-heading">
                      <div className="eyebrow">FROM EVIDENCE TO ACTION</div>
                      <h1>A clear request. Backed by records.</h1>
                      <p>
                        Ask for an updated ledger and confirmation of how your
                        payment was applied.
                      </p>
                    </div>
                    <div className="packet-grid">
                      <div className="panel draft-panel">
                        <div className="panel-heading">
                          <h2>Your draft</h2>
                          <label className="recipient-label">
                            To{" "}
                            <select
                              aria-label="Response recipient"
                              value={recipient}
                              onChange={(e) => {
                                setRecipient(
                                  e.target.value as "provider" | "collector",
                                );
                                setLetter(null);
                                setReviewed(false);
                                setExported(false);
                              }}
                            >
                              <option value="provider">
                                Provider billing office
                              </option>
                              <option value="collector">Debt collector</option>
                            </select>
                          </label>
                        </div>
                        {recipient === "collector" && (
                          <p className="footnote">
                            A collector dispute and a CFPB complaint are
                            separate actions. Confirm the date printed on your
                            notice; the app does not calculate legal deadlines.
                          </p>
                        )}
                        <label htmlFor="draft" className="sr-only">
                          Review and edit your draft
                        </label>
                        <textarea
                          id="draft"
                          className="draft-editor"
                          value={draft}
                          disabled={loading}
                          onChange={(e) => {
                            setLetter(e.target.value);
                            setReviewed(false);
                            setExported(false);
                          }}
                        />
                        <p className="footnote">
                          Review the wording and add your name and reply address
                          before sharing.
                        </p>
                      </div>
                      <div className="packet-side">
                        <div className="panel">
                          <div className="panel-heading">
                            <h2>Inside your packet</h2>
                            <FileCheck2 size={18} />
                          </div>
                          {[
                            "Factual evidence summary",
                            "Reconstructed ledger",
                            "Indexed source passages",
                            "Editable inquiry draft",
                            "Communication log",
                          ].map((item) => (
                            <div className="packet-inclusion" key={item}>
                              <Check size={15} />
                              {item}
                            </div>
                          ))}
                          <div className="attachment-list">
                            <h3>Supporting records</h3>
                            {documents
                              ?.filter((d) => d.included)
                              .map((d) => (
                                <button
                                  key={d.id}
                                  onClick={() => setDrawer({ docId: d.id })}
                                >
                                  <FileText size={14} />
                                  {d.title}
                                  <ExternalLink size={12} />
                                </button>
                              ))}
                          </div>
                          <p className="footnote">
                            Attach copies of the original records separately.
                            The packet includes their references and passages.
                          </p>
                        </div>
                        <div className="export-panel">
                          {pending > 0 && (
                            <p className="review-alert">
                              {pending} facts still need review.{" "}
                              <button
                                className="text-button"
                                onClick={() => setWorkspace("evidence")}
                              >
                                Review documents <ArrowRight size={13} />
                              </button>
                            </p>
                          )}
                          <label className="review-checkbox">
                            <input
                              type="checkbox"
                              checked={reviewed}
                              disabled={
                                loading ||
                                pending > 0 ||
                                !documents?.some(
                                  (d) =>
                                    d.included && Object.keys(d.fields).length,
                                )
                              }
                              onChange={(e) => setReviewed(e.target.checked)}
                            />
                            <span>
                              I reviewed this draft and the supporting facts.
                            </span>
                          </label>
                          <button
                            className="button primary full"
                            disabled={
                              !reviewed || loading || exporting || pending > 0
                            }
                            onClick={download}
                          >
                            {exporting ? (
                              <Loader2 className="spin" size={16} />
                            ) : (
                              <Download size={16} />
                            )}
                            Download evidence packet
                          </button>
                          {exported && (
                            <p className="download-success" role="status">
                              <Check size={14} />
                              Packet downloaded. Nothing was sent.
                            </p>
                          )}
                          <p className="footnote">
                            Printable HTML. Open it in a browser to save as PDF.
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="context-note">
                      <ShieldCheck size={17} />
                      <p>
                        This packet asks specific questions. It does not confirm
                        the current ledger, later reversals, or legal liability.{" "}
                        <a
                          href="https://www.consumerfinance.gov/ask-cfpb/what-should-i-do-when-a-debt-collector-contacts-me-en-1695/"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Read CFPB guidance <ExternalLink size={12} />
                        </a>
                      </p>
                    </div>
                  </section>
                )}
              </>
            )}
            {workspace === "evidence" && (
              <section className="fade-in">
                <div className="page-heading">
                  <div className="eyebrow">DOCUMENTS & REVIEW</div>
                  <h1>Every fact has a source.</h1>
                  <p>
                    Review extracted values, keep the original passages, and
                    decide what to include.
                  </p>
                </div>
                <div className="evidence-layout">
                  <div>
                    <div className="section-heading">
                      <h2>Your documents</h2>
                      <span className="count-label">
                        {pending} facts awaiting review
                      </span>
                    </div>
                    {documents?.map((doc) => (
                      <div className="evidence-row" key={doc.id}>
                        <span className={`doc-icon ${doc.kind}`}>
                          <FileText size={20} />
                        </span>
                        <div>
                          <strong>{doc.title}</strong>
                          <small>
                            {doc.extraction_method} ·{" "}
                            {
                              Object.values(doc.fields).filter(
                                (f) => f.confirmed,
                              ).length
                            }
                            /{Object.keys(doc.fields).length} reviewed
                          </small>
                        </div>
                        <label className="switch-label">
                          <input
                            type="checkbox"
                            role="switch"
                            checked={doc.included}
                            onChange={() => toggle(doc.id)}
                            aria-label={`Include ${doc.title}`}
                          />
                          <span className="switch-track" />
                        </label>
                        <button
                          className="button secondary compact"
                          onClick={() =>
                            setDrawer({ docId: doc.id, edit: true })
                          }
                        >
                          Review
                        </button>
                      </div>
                    ))}
                    {!documents?.length && (
                      <div className="empty-state">
                        <Upload />
                        <h3>Add your first document</h3>
                        <p>
                          Paste labeled text or upload a text PDF. Scanned
                          documents need transcription.
                        </p>
                      </div>
                    )}
                    <button
                      className="text-button"
                      onClick={() => {
                        setWorkspace("demo");
                        go(1);
                      }}
                    >
                      Return to reconciliation <ArrowRight size={15} />
                    </button>
                  </div>
                  <AddDocument
                    boot={boot}
                    onAdded={(doc) => {
                      const id = `${doc.id}-${crypto.randomUUID().slice(0, 8)}`;
                      replaceDocuments([...(documents || []), { ...doc, id }]);
                      setFictional(false);
                      setDrawer({ docId: id, edit: true });
                    }}
                  />
                </div>
              </section>
            )}
            {workspace === "research" && <Research boot={boot} />}
          </>
        )}
        <footer>
          <span>Not My Debt · Carolina Data Challenge 2026</span>
        </footer>
      </main>
      {drawer && documents && boot && (
        <EvidenceDrawer
          key={drawer.docId || drawer.refs?.join()}
          drawer={drawer}
          documents={documents}
          labels={boot.field_labels}
          sources={documentSources}
          onClose={() => setDrawer(null)}
          onSave={(doc) =>
            replaceDocuments(documents.map((d) => (d.id === doc.id ? doc : d)))
          }
        />
      )}
    </div>
  );
}

function EvidenceDrawer({
  drawer,
  documents,
  labels,
  sources,
  onClose,
  onSave,
}: {
  drawer: Drawer;
  documents: Document[];
  labels: Record<string, string>;
  sources: Record<string, string>;
  onClose: () => void;
  onSave: (doc: Document) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const doc = documents.find((d) => d.id === drawer.docId);
  const [sourceView, setSourceView] = useState<"pdf" | "text">("pdf");
  const [fields, setFields] = useState<Record<string, Fact>>(
    doc ? structuredClone(doc.fields) : {},
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [newField, setNewField] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function save() {
    if (!doc) return;
    setSaving(true);
    setError("");
    const updated = {
      ...doc,
      fields: Object.fromEntries(
        Object.entries(fields)
          .filter(([, fact]) => fact.value.trim())
          .map(([key, fact]) => [
            key,
            {
              ...fact,
              value: fact.value.trim(),
              origin:
                fact.value !== doc.fields[key]?.value
                  ? ("user" as const)
                  : fact.origin,
            },
          ]),
      ),
    };
    try {
      await api({
        operation: "reconcile",
        documents: documents.map((d) => (d.id === doc.id ? updated : d)),
      });
      onSave(updated);
      onClose();
    } catch {
      setError(
        "Check the reviewed values. Use nonnegative dollar amounts with up to two decimal places and dates as YYYY-MM-DD.",
      );
    } finally {
      setSaving(false);
    }
  }
  const pdf = doc && sources[doc.id] ? demoPdfUrl(sources[doc.id]) : undefined;
  const refs = [...new Set(drawer.refs || [])];
  const referenced = refs.map((ref) => {
    const document = documents.find(
      (d) => ref === d.id || ref.startsWith(`${d.id}.`),
    );
    const key = document ? ref.slice(document.id.length + 1) : "";
    return { ref, doc: document, key, fact: document?.fields[key] };
  });
  return (
    <dialog
      ref={dialog}
      className="source-drawer"
      aria-labelledby="drawer-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="drawer-inner">
        <div className="drawer-header">
          <div>
            <div className="eyebrow">EVIDENCE / ORIGINAL RECORD</div>
            <h2 id="drawer-title">{doc?.title || "Supporting passages"}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close evidence"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {doc && !drawer.edit && (
          <>
            <div className="source-status">
              <FileText size={16} />
              {doc.extraction_method}
            </div>
            {pdf && (
              <>
                <div className="source-toolbar">
                  <div className="source-tabs" aria-label="Source view">
                    <button
                      className={sourceView === "pdf" ? "selected" : ""}
                      onClick={() => setSourceView("pdf")}
                      aria-pressed={sourceView === "pdf"}
                    >
                      Original PDF
                    </button>
                    <button
                      className={sourceView === "text" ? "selected" : ""}
                      onClick={() => setSourceView("text")}
                      aria-pressed={sourceView === "text"}
                    >
                      Extracted text
                    </button>
                  </div>
                  <a
                    href={pdf}
                    download={sources[doc.id]}
                    className="text-button"
                  >
                    <Download size={14} />
                    Download PDF
                  </a>
                </div>
                <p className="footnote source-disclosure">
                  Fictional original document. Corrected fields do not change
                  this PDF.
                </p>
              </>
            )}
            {pdf && sourceView === "pdf" ? (
              <>
                <iframe
                  className="pdf-preview"
                  src={`${pdf}#toolbar=0&navpanes=0&view=FitH`}
                  title={`Original fictional PDF: ${doc.title}`}
                />
                <a
                  href={pdf}
                  target="_blank"
                  rel="noreferrer"
                  className="text-button"
                >
                  Open PDF in a new tab <ExternalLink size={13} />
                </a>
              </>
            ) : (
              <pre className="original-document">{doc.text}</pre>
            )}

            <button className="button secondary" onClick={onClose}>
              Close source <Check size={15} />
            </button>
          </>
        )}
        {doc && drawer.edit && (
          <>
            <p className="muted">
              Correct values and confirm the facts you reviewed. Original quotes
              are preserved; corrections are labeled as your statements.
            </p>
            {doc.warnings.map((warning, i) => (
              <p className="review-alert" key={i}>
                {warning}
              </p>
            ))}
            {Object.entries(fields).map(([key, fact]) => (
              <div className="fact-editor" key={key}>
                <label htmlFor={`field-${key}`}>{labels[key]}</label>
                <input
                  id={`field-${key}`}
                  value={fact.value}
                  onChange={(e) =>
                    setFields({
                      ...fields,
                      [key]: {
                        ...fact,
                        value: e.target.value,
                        confirmed: false,
                      },
                    })
                  }
                />
                <blockquote>
                  {fact.quote ||
                    "No source passage. This is a user-supplied statement."}
                </blockquote>
                <label className="fact-reviewed">
                  <input
                    type="checkbox"
                    checked={fact.confirmed}
                    onChange={(e) =>
                      setFields({
                        ...fields,
                        [key]: { ...fact, confirmed: e.target.checked },
                      })
                    }
                  />
                  Reviewed · page {fact.page}
                </label>
              </div>
            ))}
            <div className="add-fact">
              <label htmlFor="new-fact">Add a missing fact</label>
              <select
                id="new-fact"
                value={newField}
                onChange={(e) => setNewField(e.target.value)}
              >
                <option value="">Choose a field</option>
                {Object.entries(labels)
                  .filter(([key]) => !fields[key])
                  .map(([key, label]) => (
                    <option value={key} key={key}>
                      {label}
                    </option>
                  ))}
              </select>
              <button
                className="button secondary compact"
                disabled={!newField}
                onClick={() => {
                  setFields({
                    ...fields,
                    [newField]: {
                      value: "",
                      quote: "",
                      page: 1,
                      confirmed: false,
                      origin: "user",
                    },
                  });
                  setNewField("");
                }}
              >
                Add field <Plus size={14} />
              </button>
            </div>
            <details>
              <summary>Read the full original text</summary>
              <pre className="original-document">{doc.text}</pre>
            </details>
            <label className="review-checkbox">
              <input
                type="checkbox"
                checked={
                  Object.values(fields).length > 0 &&
                  Object.values(fields).every((f) => f.confirmed)
                }
                onChange={(e) =>
                  setFields(
                    Object.fromEntries(
                      Object.entries(fields).map(([key, fact]) => [
                        key,
                        { ...fact, confirmed: e.target.checked },
                      ]),
                    ),
                  )
                }
              />
              I reviewed all displayed facts.
            </label>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button
              className="button primary full"
              disabled={saving}
              onClick={save}
            >
              {saving ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <Check size={16} />
              )}
              Save reviewed facts
            </button>
          </>
        )}
        {!doc &&
          referenced.some((item) => item.doc && sources[item.doc.id]) && (
            <div className="source-pdf-links">
              <span className="eyebrow">ORIGINAL FICTIONAL PDFS</span>
              {[
                ...new Map(
                  referenced
                    .filter((item) => item.doc && sources[item.doc.id])
                    .map((item) => [item.doc!.id, item.doc!]),
                ).values(),
              ].map((document) => (
                <a
                  key={document.id}
                  href={demoPdfUrl(sources[document.id])}
                  target="_blank"
                  rel="noreferrer"
                >
                  <FileText size={14} />
                  {document.title}
                  <ExternalLink size={12} />
                </a>
              ))}
            </div>
          )}
        {!doc &&
          referenced
            .filter((item) => item.doc)
            .map(({ ref, doc: document, fact, key }) => (
              <article className="source-passage" key={ref}>
                <span className="source-status">
                  {document!.title} · page {fact?.page || 1}
                </span>
                <h3>{labels[key] || "Document"}</h3>
                <blockquote>{fact?.quote || document!.text}</blockquote>
                <p>
                  {fact
                    ? `${fact.origin === "user" ? "User-confirmed" : fact.confirmed ? "Reviewed" : "Unreviewed"} value: ${fact.value}`
                    : "Original source"}
                </p>
                <small>{ref}</small>
              </article>
            ))}
      </div>
    </dialog>
  );
}

function AddDocument({
  boot,
  onAdded,
}: {
  boot: Bootstrap;
  onAdded: (doc: Document) => void;
}) {
  const [kind, setKind] = useState("bill");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [method, setMethod] = useState("local");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        operation: "extract",
        kind,
        title: title || names[kind],
        text,
        method,
      };
      if (file) {
        if (file.size > 8 * 1024 * 1024)
          throw new Error("Use a file smaller than 8 MB.");
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = () =>
            reject(new Error("The file could not be read."));
          reader.readAsDataURL(file);
        });
        body.file = data;
        body.filename = file.name;
      }
      const result = await api<{ document: Document }>(body);
      onAdded(result.document);
      setText("");
      setTitle("");
      setFile(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel upload-panel" onSubmit={submit}>
      <div className="panel-heading">
        <h2>Add a document</h2>
        <Plus size={18} />
      </div>
      <label htmlFor="doc-kind">Document role</label>
      <select
        id="doc-kind"
        value={kind}
        onChange={(e) => setKind(e.target.value)}
      >
        {Object.entries(boot.kinds).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
      <label htmlFor="doc-title">
        Title <span className="muted">(optional)</span>
      </label>
      <input
        id="doc-title"
        value={title}
        maxLength={180}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="e.g. July provider statement"
      />
      <label htmlFor="doc-text">Paste document text</label>
      <textarea
        id="doc-text"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setFile(null);
        }}
        maxLength={60000}
        placeholder={
          "Account reference: MG-1042\nBalance: 150.00\nDocument date: 2026-07-15"
        }
        disabled={!!file}
      />
      <div className="upload-divider">or upload a text PDF / TXT</div>
      <label className="file-upload">
        <Upload size={18} />
        <span>{file?.name || "Choose a document"}</span>
        <input
          type="file"
          accept=".pdf,.txt,.md"
          aria-label="Upload a text document"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
      </label>
      {file && (
        <button
          type="button"
          className="text-button"
          onClick={() => setFile(null)}
        >
          Remove file <X size={12} />
        </button>
      )}
      <p className="footnote">
        8 MB maximum. Local extraction reads explicit labels. Scans need
        transcription; OCR is not included.
      </p>
      <label className="review-checkbox">
        <input
          type="checkbox"
          checked={method === "openai"}
          disabled={!boot.ai_available}
          onChange={(e) => setMethod(e.target.checked ? "openai" : "local")}
        />
        <span>
          Use OpenAI extraction{!boot.ai_available && " (not configured)"}
        </span>
      </label>
      {method === "openai" && (
        <p className="review-alert">
          This sends the document text to the configured OpenAI provider.
          Requests use store=False; provider retention policies apply.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        className="button primary full"
        disabled={busy || (!text.trim() && !file)}
      >
        {busy ? (
          <Loader2 className="spin" size={16} />
        ) : (
          <FileCheck2 size={16} />
        )}
        Extract for review
      </button>
    </form>
  );
}

function Research({ boot }: { boot: Bootstrap }) {
  const { api: annual, archive } = boot.research;
  return (
    <section className="fade-in">
      <div className="page-heading">
        <div className="eyebrow">THE BROADER PICTURE / CFPB PUBLIC DATA</div>
        <h1>A recurring reported problem.</h1>
        <p>
          Complaint records inform the questions we ask. They are separate from
          our fictional document cases.
        </p>
      </div>
      <div className="research-stats">
        <div className="panel">
          <small>Medical-debt collection complaints · 2025</small>
          <strong>{annual.total_complaints.toLocaleString()}</strong>
          <p>Complaint records, not distinct people</p>
        </div>
        <div className="panel">
          <small>Categorized as “Debt was paid” · 2025</small>
          <strong>
            {annual.not_owed_subissues
              .find((item) => item.label === "Debt was paid")
              ?.count.toLocaleString() || "Not measured"}
          </strong>
          <p>Consumer-selected category, not verified error</p>
        </div>
        <div className="panel">
          <small>Unique narrative texts analyzed</small>
          <strong>{archive.unique_narratives.toLocaleString()}</strong>
          <p>{archive.period} · normalized-text deduplication</p>
        </div>
      </div>
      <ResponseOutcomes research={boot.research} />
      <PatternMatrix research={boot.research} />
      <div className="analysis-grid">
        {[
          {
            title: "Reported documentation patterns",
            data: archive.patterns,
            color: "#2e7d70",
          },
          {
            title: "Documents mentioned",
            data: archive.document_mentions,
            color: "#ce8d6e",
          },
        ].map((chart) => (
          <div className="panel" key={chart.title}>
            <h2>{chart.title}</h2>
            <p className="muted small">
              Keyword matches among {archive.unique_narratives} unique
              narratives
            </p>
            <div className="research-chart">
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart
                  accessibilityLayer
                  data={chart.data}
                  layout="vertical"
                  margin={{ left: 0, right: 20 }}
                >
                  <CartesianGrid horizontal={false} stroke="#e9eeed" />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={196}
                    tick={{ fontSize: 11, fill: "#52615c" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    content={(props) => (
                      <ChartTooltip
                        {...props}
                        mode="count"
                        note={`Among ${archive.unique_narratives.toLocaleString()} unique narratives · Jan–Feb 2025`}
                      />
                    )}
                    cursor={{ fill: "#f3f6f1" }}
                    offset={14}
                    isAnimationActive={false}
                    wrapperStyle={{ outline: "none", zIndex: 10 }}
                  />
                  <Bar
                    dataKey="count"
                    fill={chart.color}
                    barSize={22}
                    radius={[0, 4, 4, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <details>
              <summary>
                View counts as a table <ArrowDown size={13} />
              </summary>
              <table>
                <thead>
                  <tr>
                    <th>Pattern</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {chart.data.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>
        ))}
      </div>
      <div className="context-note">
        <CircleHelp size={18} />
        <p>
          Patterns overlap. A document mention does not mean the document was
          supplied. These rules are descriptive and have not been validated as
          classifiers. CFPB supplies complaints, not paired patient paperwork.
        </p>
      </div>
      <div className="research-sources">
        <a href={annual.source_url} target="_blank" rel="noreferrer">
          2025 CFPB query <ExternalLink size={13} />
        </a>
        <a href={archive.source_url} target="_blank" rel="noreferrer">
          Jan–Feb narrative archive <ExternalLink size={13} />
        </a>
        <span>Retrieved {boot.research.retrieved_at.slice(0, 10)}</span>
      </div>
      <details className="findings-details">
        <summary>
          Methods & limitations <ChevronDown size={15} />
        </summary>
        {boot.research.caveats.map((caveat, index) => (
          <p className="finding-item" key={index}>
            {caveat}
          </p>
        ))}
      </details>
    </section>
  );
}
