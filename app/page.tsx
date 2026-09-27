"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Map as MapIcon,
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
  type CaseAnalysisMethod,
  type CaseExplanation,
  type Document,
  type ExtractionMethod,
  type Fact,
} from "@/lib/types";

import { ChartTooltip } from "@/app/components/chart-tooltip";
import { MoneyWaterfall } from "@/app/components/money-waterfall";
import {
  PatternMatrix,
  ResponseOutcomes,
} from "@/app/components/research-evidence";
import { CaseTimeline } from "@/app/components/case-timeline";
import { UploadCase, type UploadedRecord } from "@/app/components/upload-case";
import {
  CommunityAtlas,
  type AtlasFocus,
  type Community,
} from "@/app/components/atlas/community-atlas";
import { Assistant, type AssistantAction } from "@/app/components/assistant";
import { CommunityContext } from "@/app/components/atlas/community-context";

const demoPdfUrl = (file: string) =>
  `/api/demo-document?file=${encodeURIComponent(file)}`;

const sourceUrl = (source: string) =>
  source.startsWith("blob:") ? source : demoPdfUrl(source);

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
type ExplanationState =
  | { documentKey: string; status: "loading" }
  | { documentKey: string; status: "ready"; explanation: CaseExplanation }
  | { documentKey: string; status: "error"; message: string };

export default function Home() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [documentSources, setDocumentSources] = useState<
    Record<string, string>
  >({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [step, setStep] = useState(0);
  const [workspace, setWorkspace] = useState("atlas");
  const [community, setCommunity] = useState<Community | null>(null);
  const [atlasFocus, setAtlasFocus] = useState<AtlasFocus | null>(null);
  const [atlasSelection, setAtlasSelection] = useState<{
    state: string | null;
    hospitalId: string | null;
  }>({ state: null, hospitalId: null });
  const onAtlasSelection = useCallback(
    (state: string | null, hospitalId: string | null) =>
      setAtlasSelection({ state, hospitalId }),
    [],
  );
  const [uploadFlow, setUploadFlow] = useState(true);
  const [uploadGeneration, setUploadGeneration] = useState(0);
  const [basicTimelineKey, setBasicTimelineKey] = useState<string | null>(null);
  const uploadUrls = useRef<string[]>([]);
  const [scenario, setScenario] = useState("paid");
  const [fictional, setFictional] = useState(false);
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
  const [caseAnalysisMethod, setCaseAnalysisMethod] =
    useState<CaseAnalysisMethod>("codex");
  const [explanationState, setExplanationState] =
    useState<ExplanationState | null>(null);
  const explanationRequest = useRef<{
    sequence: number;
    controller: AbortController | null;
  }>({ sequence: 0, controller: null });
  const documentKey = JSON.stringify(documents);
  const currentExplanation =
    explanationState?.documentKey === documentKey ? explanationState : null;

  // Hide results by snapshot immediately, then cancel on any document change or
  // unmount. The sequence guard also rejects late responses from aborted requests.
  useEffect(() => {
    const active = explanationRequest.current;
    return () => {
      active.controller?.abort();
      active.controller = null;
      active.sequence += 1;
    };
  }, [documentKey]);

  useEffect(() => {
    const controller = new AbortController();
    api<Bootstrap>({ operation: "bootstrap" }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setBoot(data);
        setCaseAnalysisMethod(
          data.gemini_available
            ? "gemini"
            : data.codex_available
              ? "codex"
              : "openai",
        );
        setDocuments([]);
        // Demo link into the navigator: ?community=GA&hospital=<CMS ID>
        const params = new URLSearchParams(window.location.search);
        const state = params.get("community")?.toUpperCase();
        if (state && /^[A-Z]{2}$/.test(state)) {
          setCommunity({ state, hospitalId: params.get("hospital") });
          setWorkspace("upload");
        }
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
        if (controller.signal.aborted) return;
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

  useEffect(() => {
    const urls = uploadUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  function clearUploadedSources() {
    uploadUrls.current.splice(0).forEach((url) => URL.revokeObjectURL(url));
  }
  function rememberPdf(id: string, file?: File) {
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) return null;
    const url = URL.createObjectURL(
      new Blob([file], { type: "application/pdf" }),
    );
    uploadUrls.current.push(url);
    return { [id]: url };
  }
  function startUploadCase() {
    clearUploadedSources();
    replaceDocuments([]);
    setDocumentSources({});
    setUploadFlow(true);
    setUploadGeneration((value) => value + 1);
    setFictional(false);
    setStep(0);
    setWorkspace("upload");
    setDrawer(null);
    setRecipient("provider");
  }
  function receiveUploads(records: UploadedRecord[]) {
    clearUploadedSources();
    const sources: Record<string, string> = {};
    const uploaded = records.map(({ document, file }) => {
      const id = `${document.id}-${crypto.randomUUID().slice(0, 8)}`;
      Object.assign(sources, rememberPdf(id, file));
      return { ...document, id };
    });
    replaceDocuments(uploaded);
    setDocumentSources(sources);
    setUploadFlow(true);
    setUploadGeneration((value) => value + 1);
    setFictional(false);
    setStep(0);
    setWorkspace("evidence");
    setDrawer(null);
    setRecipient("provider");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function clearCaseExplanation() {
    const active = explanationRequest.current;
    active.controller?.abort();
    active.controller = null;
    active.sequence += 1;
    setExplanationState(null);
  }
  function changeCaseAnalysisMethod(method: CaseAnalysisMethod) {
    if (method === caseAnalysisMethod) return;
    clearCaseExplanation();
    setCaseAnalysisMethod(method);
  }
  function replaceDocuments(
    docs: Document[] | ((current: Document[] | null) => Document[]),
  ) {
    clearCaseExplanation();
    setBasicTimelineKey(null);
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
    clearUploadedSources();
    setUploadFlow(false);
    setUploadGeneration((value) => value + 1);
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
      : "Let’s check\nyour medical bill.";

  const includedDocuments = documents?.filter((doc) => doc.included) || [];
  const toReview = includedDocuments.filter(awaitingReview);
  const factsReady =
    !!analysis &&
    !loading &&
    !pending &&
    includedDocuments.length > 0 &&
    includedDocuments.every((doc) => Object.keys(doc.fields).length > 0) &&
    !analysis.timeline.some((event) => event.status === "needs_review");
  const methodReady = (method: CaseAnalysisMethod | ExtractionMethod) =>
    method === "local"
      ? true
      : method === "codex"
        ? !!boot?.codex_available
        : method === "gemini"
          ? !!boot?.gemini_available
          : !!boot?.ai_available;
  const analysisAvailable = methodReady(caseAnalysisMethod);

  async function explainCase(openResult = false) {
    if (!documents?.length || !analysis || loading || pending) return;
    const needsReview =
      documents.some(
        (doc) => doc.included && Object.keys(doc.fields).length === 0,
      ) || analysis.timeline?.some((event) => event.status === "needs_review");
    if (needsReview) return;
    const hasReviewedFacts = documents.some(
      (doc) =>
        doc.included &&
        Object.values(doc.fields).some((fact) => fact.confirmed),
    );
    if (!hasReviewedFacts) return;
    const method = caseAnalysisMethod;
    const available = methodReady(method);
    if (!available) {
      setExplanationState({
        documentKey,
        status: "error",
        message:
          "This analysis method is unavailable. Choose another method or check its setup.",
      });
      return;
    }
    const active = explanationRequest.current;
    active.controller?.abort();
    const controller = new AbortController();
    const sequence = ++active.sequence;
    active.controller = controller;
    const snapshot = structuredClone(documents);
    const snapshotKey = JSON.stringify(snapshot);
    setExplanationState({ documentKey: snapshotKey, status: "loading" });
    try {
      const response = await api<{ explanation: CaseExplanation }>(
        { operation: "analyze_case", documents: snapshot, method },
        controller.signal,
      );
      if (controller.signal.aborted || active.sequence !== sequence) return;
      if (response.explanation.method !== method) {
        throw new Error(
          "The analysis returned a different method. Please try again.",
        );
      }
      setExplanationState({
        documentKey: snapshotKey,
        status: "ready",
        explanation: response.explanation,
      });
      if (openResult) {
        setWorkspace("demo");
        go(1);
      }
    } catch (cause) {
      if (controller.signal.aborted || active.sequence !== sequence) return;
      setExplanationState({
        documentKey: snapshotKey,
        status: "error",
        message:
          cause instanceof Error
            ? cause.message
            : "Could not explain this case. Please try again.",
      });
    } finally {
      if (active.sequence === sequence) active.controller = null;
    }
  }

  function generationPanel() {
    const explaining = currentExplanation?.status === "loading";
    return (
      <div className="panel upload-panel">
        <div className="eyebrow">CONNECT YOUR RECORDS</div>
        <h2>Create your timeline</h2>
        <p className="muted">
          Review the extracted facts, then see what happened, where the records
          disagree, and what to ask billing.
        </p>
        <p className="small" role="status">
          {loading
            ? "Checking your reviewed facts…"
            : pending
              ? `${pending} facts still need your review.`
              : factsReady
                ? "Your included records are reviewed and ready."
                : "Add and review facts for each included document."}
        </p>
        {toReview.length > 0 && (
          <>
            <button
              className="button primary full"
              onClick={() => setDrawer({ docId: toReview[0].id, edit: true })}
            >
              <FileCheck2 size={16} />
              Review {toReview[0].title}
            </button>
            <p className="footnote">
              {includedDocuments.length - toReview.length} of{" "}
              {includedDocuments.length} documents reviewed. The timeline opens
              once each one is checked.
            </p>
          </>
        )}
        <label htmlFor="upload-analysis-method">Analysis method</label>
        <select
          id="upload-analysis-method"
          value={caseAnalysisMethod}
          onChange={(event) =>
            changeCaseAnalysisMethod(event.target.value as CaseAnalysisMethod)
          }
        >
          <option value="gemini" disabled={!boot?.gemini_available}>
            Google Gemini
          </option>
          <option value="codex" disabled={!boot?.codex_available}>
            Codex (ChatGPT sign-in)
          </option>
          <option value="openai" disabled={!boot?.ai_available}>
            OpenAI API
          </option>
        </select>
        <p className="footnote">
          {caseAnalysisMethod === "gemini"
            ? "Sends reviewed facts and quotes to Google Gemini. Amounts and dates stay controlled by the app."
            : caseAnalysisMethod === "codex"
            ? "Sends reviewed facts and quotes to OpenAI through Codex using your ChatGPT usage."
            : "Sends reviewed facts and quotes to OpenAI. API usage is billed separately."}
        </p>
        {!analysisAvailable && (
          <p className="review-alert">
            Connect an analysis method to get an explanation. You can still view
            the timeline on its own.
          </p>
        )}
        <button
          className={`button ${toReview.length ? "secondary" : "primary"} full`}
          disabled={!factsReady || !analysisAvailable || explaining}
          onClick={() => void explainCase(true)}
        >
          {explaining ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <Layers size={16} />
          )}
          {explaining
            ? "Creating your timeline & explanation…"
            : "Create timeline & explanation"}
        </button>
        {explaining && (
          <p className="footnote" role="status">
            Connecting the reviewed records and checking the sources…
          </p>
        )}
        {currentExplanation?.status === "error" && (
          <p className="error" role="alert">
            {currentExplanation.message}
          </p>
        )}
        <button
          className="text-button"
          disabled={!factsReady || explaining}
          onClick={() => {
            setBasicTimelineKey(documentKey);
            setWorkspace("demo");
            go(1);
          }}
        >
          View timeline only <ArrowRight size={14} />
        </button>
      </div>
    );
  }

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

  // Shared with the guide only when the user turns on "Share my case summary".
  const caseSummary = useMemo(() => {
    if (!analysis || !documents?.some((doc) => doc.included)) return null;
    const { result } = analysis;
    const dollars = (cents: number | null) =>
      cents == null ? "unknown" : (cents / 100).toFixed(2);
    return {
      documents: documents
        .filter((doc) => doc.included)
        .map((doc) => ({
          type: boot?.kinds[doc.kind] ?? doc.kind,
          fields_reviewed: Object.values(doc.fields).filter((f) => f.confirmed)
            .length,
          fields_total: Object.keys(doc.fields).length,
        })),
      amount_requested_by_collector: dollars(result.collection_cents),
      balance_supported_by_records: dollars(result.supported_balance_cents),
      patient_payments_applied: dollars(result.applied_payments_cents),
      findings: result.findings.map((f) => ({
        title: f.title,
        detail: f.detail,
        severity: f.severity,
      })),
    };
  }, [analysis, documents, boot]);

  function handleAssistantAction(action: AssistantAction) {
    if (action.type === "open_workspace") {
      setWorkspace(action.workspace);
      return;
    }
    if (action.type === "open_state") {
      setWorkspace("atlas");
      setAtlasFocus((current) => ({
        state: action.state,
        hospitalId: action.hospitalId ?? null,
        nonce: (current?.nonce ?? 0) + 1,
      }));
      return;
    }
    setCommunity({ state: action.state, hospitalId: action.hospitalId ?? null });
    setWorkspace("upload");
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
            { id: "atlas", name: "Community map", icon: MapIcon },
            { id: "upload", name: "Upload a case", icon: Upload },
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
              {confirmedValue(notice, "account")
                ? `Account ${confirmedValue(notice, "account")}`
                : "Medical bills & payments"}
            </small>
          </div>
        </div>
        <div className="sidebar-bottom">
          <details className="scenario-picker">
            <summary>
              Explore another case <ChevronDown size={14} />
            </summary>
            <label htmlFor="scenario">Choose a case</label>
            <select
              id="scenario"
              value={fictional ? scenario : ""}
              onChange={(e) => loadCase(e.target.value)}
              disabled={!boot}
            >
              <option value="" disabled>
                Choose an example case
              </option>
              {Object.entries(boot?.scenarios || {}).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
            <button className="text-button" onClick={startUploadCase}>
              Start a new case <ArrowRight size={14} />
            </button>
          </details>
          <button
            className="reset-button"
            onClick={() => (fictional ? loadCase(scenario) : startUploadCase())}
            disabled={!boot}
          >
            <RotateCcw size={15} />
            {fictional ? "Reset case" : "Start over"}
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>Medical bills & payments</span>
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
            <h2>{error ? "Your case couldn’t load" : "Opening your case…"}</h2>
          </div>
        ) : (
          <>
            {workspace === "atlas" && (
              <CommunityAtlas
                focus={atlasFocus}
                onSelectionChange={onAtlasSelection}
                onOpenNavigator={(next) => {
                  setCommunity(next);
                  setWorkspace("upload");
                }}
              />
            )}
            <div hidden={workspace !== "upload"}>
              {community && (
                <CommunityContext
                  community={community}
                  onChange={setCommunity}
                  onClear={() => setCommunity(null)}
                />
              )}
              <UploadCase
                key={uploadGeneration}
                boot={boot}
                onComplete={receiveUploads}
                onExample={() => loadCase("paid")}
              />
            </div>
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
                            : "Compare your bill, insurance explanation, receipt, and collection notice."}
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
                      </div>
                    </div>
                    <div className="section-heading">
                      <div>
                        <h2>Your documents</h2>
                        <p>Open a document to check the details.</p>
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
                        <p>
                          Add a bill, receipt, or collection notice to begin.
                        </p>
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
                        An insurance explanation shows your share of the bill. A
                        receipt shows what you paid.
                      </p>
                    </div>
                    {community && (
                      <CommunityContext
                        community={community}
                        onChange={setCommunity}
                        onClear={() => setCommunity(null)}
                      />
                    )}
                  </section>
                )}
                {step === 1 &&
                  (!uploadFlow ||
                    currentExplanation?.status === "ready" ||
                    basicTimelineKey === documentKey) && (
                    <section className="fade-in">
                      <div className="page-heading">
                        <div>
                          <div className="eyebrow">FOLLOW THE MONEY</div>
                          <h1>Check the balance</h1>
                          <p>Click an amount to see where it came from.</p>
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
                            ? "Updating…"
                            : "Based on the included documents"}
                        </span>
                      </div>
                      <CaseTimeline
                        events={analysis?.timeline || []}
                        documents={documents || []}
                        loading={loading}
                        pending={pending}
                        method={caseAnalysisMethod}
                        availability={{
                          codex: boot.codex_available,
                          openai: boot.ai_available,
                          gemini: boot.gemini_available,
                        }}
                        explanation={
                          currentExplanation?.status === "ready"
                            ? currentExplanation.explanation
                            : null
                        }
                        explaining={currentExplanation?.status === "loading"}
                        error={
                          currentExplanation?.status === "error"
                            ? currentExplanation.message
                            : null
                        }
                        onMethodChange={changeCaseAnalysisMethod}
                        onExplain={() => void explainCase()}
                        onSource={source}
                        onReview={() => setWorkspace("evidence")}
                      />
                      {loading ? (
                        <div className="finding-banner loading">
                          <Loader2 className="spin" />
                          Checking your documents…
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
                                  ? "We need a payment receipt."
                                  : result?.supported_balance_cents == null
                                    ? "Some details still need review."
                                    : "Here’s the balance from your records."}
                            </h2>
                            <p>
                              {finding
                                ? "The receipt matches this account and visit. It was paid after the bill and before the collection notice. Ask the provider to check how the payment was applied."
                                : missing
                                  ? "The insurance explanation alone doesn’t show whether you paid this balance."
                                  : "Check the details below before contacting the billing office."}
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
                                Why this payment matches{" "}
                                <ArrowRight size={14} />
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
                              .map((row, index) => (
                                <button
                                  className="ledger-row"
                                  key={`${row.label}-${index}`}
                                  onClick={() => source(row.refs)}
                                >
                                  <span>{row.label}</span>
                                  <strong>{money(row.cents)}</strong>
                                  <ExternalLink size={13} />
                                </button>
                              ))}
                            <div className="ledger-total">
                              <span>Balance from these records</span>
                              <strong>
                                {result?.supported_balance_cents == null
                                  ? "Withheld"
                                  : money(result.supported_balance_cents)}
                              </strong>
                            </div>
                          </div>
                          <p className="footnote">
                            Later charges or payment reversals may change this
                            amount. Ask the provider for the current balance.
                          </p>
                        </div>
                        <div className="panel chart-panel">
                          <div className="panel-heading">
                            <h2>Where the money goes</h2>
                            <BarChart3 size={17} />
                          </div>
                          <p className="muted small">
                            How the bill reaches its balance, next to what the
                            notice requests. Click a bar to see its source.
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
                              <small>Your records show</small>
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
                            A missing balance is marked “Withheld,” not shown as
                            $0.
                          </p>
                        </div>
                      </div>
                      <details className="findings-details">
                        <summary>
                          Details & questions to resolve{" "}
                          <span>
                            {result?.findings.length || 0}
                            <ChevronDown size={15} />
                          </span>
                        </summary>
                        {/* Codes are categories: one code can appear for several records. */}
                        {result?.findings.map((item, index) => (
                          <div
                            className="finding-item"
                            key={`${item.code}-${index}`}
                          >
                            <h3>{item.title}</h3>
                            <p>{item.detail}</p>
                            {item.refs.length > 0 && (
                              <button
                                className="text-button"
                                onClick={() => source(item.refs)}
                              >
                                View source <ArrowRight size={14} />
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
                {step === 1 &&
                  uploadFlow &&
                  currentExplanation?.status !== "ready" &&
                  basicTimelineKey !== documentKey && (
                    <section className="fade-in">
                      <div className="page-heading">
                        <div className="eyebrow">YOUR RECORDS</div>
                        <h1>Let’s connect the paperwork.</h1>
                        <p>
                          Start with your documents. The timeline and
                          explanation will appear here when they’re ready.
                        </p>
                      </div>
                      {generationPanel()}
                      <button
                        className="text-button"
                        onClick={() =>
                          setWorkspace(
                            documents?.length ? "evidence" : "upload",
                          )
                        }
                      >
                        {documents?.length
                          ? "Review documents"
                          : "Upload documents"}{" "}
                        <ArrowRight size={15} />
                      </button>
                    </section>
                  )}
                {step === 2 && (
                  <section className="fade-in">
                    <div className="page-heading">
                      <div className="eyebrow">YOUR RESPONSE</div>
                      <h1>Prepare your response</h1>
                      <p>
                        Ask the billing office to check the balance and how your
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
                            Check the dispute date printed on your notice. This
                            letter goes to the collector; a CFPB complaint is a
                            separate step.
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
                            "Case summary",
                            "Balance breakdown",
                            "Quotes from your documents",
                            "Your letter",
                            "Contact history",
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
                            Attach copies of your original documents when you
                            send the letter.
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
                              Packet downloaded.
                            </p>
                          )}
                          <p className="footnote">
                            Open the download, then print or save it as a PDF.
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="context-note">
                      <ShieldCheck size={17} />
                      <p>
                        Keep a copy of your letter and proof of delivery.{" "}
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
                  <h1>
                    {uploadFlow
                      ? "Check what we read."
                      : "Review your documents"}
                  </h1>
                  <p>
                    Check each value against the original and correct any
                    mistakes.
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
                          aria-label={`Review ${doc.title}`}
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
                          Paste the text, or upload a PDF or photo of the bill.
                        </p>
                      </div>
                    )}
                    {!uploadFlow && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setWorkspace("demo");
                          go(1);
                        }}
                      >
                        Check the balance <ArrowRight size={15} />
                      </button>
                    )}
                  </div>
                  <div>
                    {uploadFlow && generationPanel()}
                    <details open={!uploadFlow} className="findings-details">
                      <summary>
                        Add another document <Plus size={15} />
                      </summary>
                      <AddDocument
                        key={uploadGeneration}
                        boot={boot}
                        onAdded={(doc, file) => {
                          const id = `${doc.id}-${crypto.randomUUID().slice(0, 8)}`;
                          replaceDocuments((current) => [
                            ...(current || []),
                            { ...doc, id },
                          ]);
                          const pdfSource = rememberPdf(id, file);
                          if (pdfSource)
                            setDocumentSources((sources) => ({
                              ...sources,
                              ...pdfSource,
                            }));
                          setUploadFlow(true);
                          setFictional(false);
                          setDrawer({ docId: id, edit: true });
                        }}
                      />
                    </details>
                  </div>
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
          key={`${uploadGeneration}:${drawer.docId || drawer.refs?.join()}`}
          drawer={drawer}
          documents={documents}
          labels={boot.field_labels}
          sources={documentSources}
          nextTitle={
            drawer.edit
              ? documents.find((d) => d.id !== drawer.docId && awaitingReview(d))
                  ?.title
              : undefined
          }
          onClose={() => setDrawer(null)}
          onSave={(doc) => {
            replaceDocuments((current) =>
              (current || []).map((d) => (d.id === doc.id ? doc : d)),
            );
            // Move straight on to the next document that still needs review.
            const next =
              drawer.edit && !awaitingReview(doc)
                ? documents.find((d) => d.id !== doc.id && awaitingReview(d))
                : undefined;
            setDrawer(next ? { docId: next.id, edit: true } : null);
          }}
        />
      )}
      {boot && (
        <Assistant
          workspace={workspace}
          context={
            workspace === "atlas"
              ? atlasSelection
              : {
                  state: community?.state ?? null,
                  hospitalId: community?.hospitalId ?? null,
                }
          }
          caseSummary={caseSummary}
          onAction={handleAssistantAction}
        />
      )}
    </div>
  );
}

// A document needs review until it has facts and every one is confirmed.
function awaitingReview(doc: Document) {
  return (
    doc.included &&
    (Object.keys(doc.fields).length === 0 ||
      Object.values(doc.fields).some((fact) => !fact.confirmed))
  );
}

function EvidenceDrawer({
  drawer,
  documents,
  labels,
  sources,
  nextTitle,
  onClose,
  onSave,
}: {
  drawer: Drawer;
  documents: Document[];
  labels: Record<string, string>;
  sources: Record<string, string>;
  nextTitle?: string;
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
  const saveRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => saveRequest.current?.abort();
  }, []);
  async function save() {
    if (!doc) return;
    saveRequest.current?.abort();
    const controller = new AbortController();
    saveRequest.current = controller;
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
      await api(
        {
          operation: "reconcile",
          documents: documents.map((d) => (d.id === doc.id ? updated : d)),
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      onSave(updated);
    } catch {
      if (controller.signal.aborted) return;
      setError(
        "Check the reviewed values. Use nonnegative dollar amounts with up to two decimal places and dates as YYYY-MM-DD.",
      );
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  }
  const allChecked =
    Object.values(fields).length > 0 &&
    Object.values(fields).every((f) => f.confirmed);
  const pdf = doc && sources[doc.id] ? sourceUrl(sources[doc.id]) : undefined;
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
            <div className="eyebrow">ORIGINAL DOCUMENT</div>
            <h2 id="drawer-title">{doc?.title || "Source details"}</h2>
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
                    download={
                      sources[doc.id].startsWith("blob:")
                        ? `${doc.title}.pdf`
                        : sources[doc.id]
                    }
                    className="text-button"
                  >
                    <Download size={14} />
                    Download PDF
                  </a>
                </div>
                <p className="footnote source-disclosure">
                  Edits to extracted values do not change this PDF.
                </p>
              </>
            )}
            {pdf && sourceView === "pdf" ? (
              <>
                <iframe
                  className="pdf-preview"
                  src={`${pdf}#toolbar=0&navpanes=0&view=FitH`}
                  title={`Original PDF: ${doc.title}`}
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
            {pdf && (
              <a
                href={pdf}
                target="_blank"
                rel="noreferrer"
                className="text-button"
              >
                Open original PDF <ExternalLink size={13} />
              </a>
            )}
            <p className="muted">
              Check each value against the quote below it. Your corrections keep
              the original text for reference.
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
                    "You added this value. No document quote is attached."}
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
                checked={allChecked}
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
              I checked every value above.
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
              {allChecked && nextTitle
                ? "Save reviewed facts & open next"
                : "Save reviewed facts"}
            </button>
            <p className="footnote" role="status">
              {!allChecked
                ? "Tick “I checked every value above” to mark this document reviewed."
                : nextTitle
                  ? `Next: ${nextTitle}`
                  : "This is the last document to review."}
            </p>
          </>
        )}
        {!doc &&
          referenced.some((item) => item.doc && sources[item.doc.id]) && (
            <div className="source-pdf-links">
              <span className="eyebrow">ORIGINAL DOCUMENTS</span>
              {[
                ...new Map(
                  referenced
                    .filter((item) => item.doc && sources[item.doc.id])
                    .map((item) => [item.doc!.id, item.doc!]),
                ).values(),
              ].map((document) => (
                <a
                  key={document.id}
                  href={sourceUrl(sources[document.id])}
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
  onAdded: (doc: Document, file?: File) => void;
}) {
  const [kind, setKind] = useState("bill");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [method, setMethod] = useState<ExtractionMethod>("local");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const extractionRequest = useRef<AbortController | null>(null);
  useEffect(() => () => extractionRequest.current?.abort(), []);
  const methodAvailable =
    method === "local"
      ? true
      : method === "codex"
        ? boot.codex_available
        : method === "gemini"
          ? boot.gemini_available
          : boot.ai_available;
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!methodAvailable) {
      setError(
        "This extractor is unavailable. Check its setup or choose another method.",
      );
      return;
    }
    extractionRequest.current?.abort();
    const controller = new AbortController();
    extractionRequest.current = controller;
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
      if (controller.signal.aborted) return;
      const result = await api<{ document: Document }>(body, controller.signal);
      if (controller.signal.aborted) return;
      onAdded(
        {
          ...result.document,
          fields: Object.fromEntries(
            Object.entries(result.document.fields).map(([key, fact]) => [
              key,
              { ...fact, confirmed: false },
            ]),
          ),
        },
        file || undefined,
      );
      setText("");
      setTitle("");
      setFile(null);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
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
      <div className="upload-divider">or upload a PDF, photo, or TXT</div>
      <label className="file-upload">
        <Upload size={18} />
        <span>{file?.name || "Choose a document"}</span>
        <input
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md"
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
        Up to 8 MB. Scans and photos are read locally with OCR; check each value.
      </p>
      <label htmlFor="doc-extractor">Extraction method</label>
      <select
        id="doc-extractor"
        value={method}
        disabled={busy}
        aria-describedby="extraction-help"
        onChange={(e) => {
          setMethod(e.target.value as ExtractionMethod);
          setError("");
        }}
      >
        <option value="local">This computer (no AI)</option>
        <option value="gemini" disabled={!boot.gemini_available}>
          Google Gemini
        </option>
        <option value="codex" disabled={!boot.codex_available}>
          Codex (ChatGPT sign-in)
        </option>
        <option value="openai" disabled={!boot.ai_available}>
          OpenAI API
        </option>
      </select>
      <div id="extraction-help">
        {method === "local" && (
          <p className="footnote">
            Reads the text, PDF, scan, or photo on this computer. Nothing is sent anywhere.
          </p>
        )}
        {method === "gemini" && (
          <p className="review-alert">
            Sends the document text to Google Gemini for extraction. You review
            every value before it is used.
          </p>
        )}
        {method === "codex" && (
          <p className="review-alert">
            Sends the document text to OpenAI using your ChatGPT sign-in and
            usage allowance. No API key needed.
          </p>
        )}
        {method === "openai" && (
          <p className="review-alert">
            Sends the document text to OpenAI. API usage is billed separately
            from your ChatGPT plan.
          </p>
        )}
        {!boot.codex_available && (
          <p className="footnote">Install Codex to use your ChatGPT sign-in.</p>
        )}
        {!boot.ai_available && (
          <p className="footnote">
            Add an API key to use OpenAI API extraction.
          </p>
        )}
        {!methodAvailable && (
          <p className="error" role="alert">
            This extractor is unavailable. Check its setup or choose another
            method.
          </p>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        className="button primary full"
        disabled={busy || !methodAvailable || (!text.trim() && !file)}
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
        <div className="eyebrow">CFPB PUBLIC DATA</div>
        <h1>Medical debt complaints</h1>
        <p>What consumers report about bills sent to collections.</p>
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
          <p>Reported by the consumer; not a verified billing error</p>
        </div>
        <div className="panel">
          <small>Unique narrative texts analyzed</small>
          <strong>{archive.unique_narratives.toLocaleString()}</strong>
          <p>{archive.period} · repeated text removed</p>
        </div>
      </div>
      <ResponseOutcomes research={boot.research} />
      <PatternMatrix research={boot.research} />
      <div className="analysis-grid">
        {[
          {
            title: "Common phrases in complaints",
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
          A complaint can match several phrases. Mentioning a document doesn’t
          mean it was provided. These counts describe complaint text, not
          confirmed billing errors.
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
        {[
          "These are complaint records, not counts of people or confirmed billing errors.",
          "The annual totals and narrative charts cover different periods, so their counts aren’t directly comparable.",
          "Only some consumers publish a narrative. Those stories may not represent all complaints.",
          "One narrative can match several keywords. The charts count unique, nonempty narratives.",
          "A keyword match does not verify a payment, error, or missing document. These searches do not interpret context or negation.",
          "This analysis does not measure model accuracy, debt recovery, or the effect of a response letter.",
          "CFPB provides complaint text, not the underlying medical bills or receipts. These data do not validate the app’s document checks.",
        ].map((caveat, index) => (
          <p className="finding-item" key={index}>
            {caveat}
          </p>
        ))}
      </details>
    </section>
  );
}
