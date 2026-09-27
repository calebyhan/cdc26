import {
  ArrowUpRight,
  Check,
  CircleHelp,
  FileText,
  Link2,
  Loader2,
  MessageSquareText,
  Minus,
  Sparkles,
} from "lucide-react";
import {
  money,
  type CaseAnalysisMethod,
  type CaseExplanation,
  type Document,
  type TimelineEvent,
} from "@/lib/types";

const roles: Record<string, string> = {
  eob: "Insurance explanation",
  bill: "Provider bill",
  receipt: "Payment receipt",
  collection: "Collection notice",
};
const methods: Record<CaseAnalysisMethod, string> = {
  codex: "Codex (ChatGPT sign-in)",
  openai: "OpenAI API",
};
const statuses = {
  included: { label: "Included", icon: Check },
  excluded: { label: "Not included", icon: Minus },
  unmatched: { label: "Not used in balance", icon: Link2 },
  needs_review: { label: "Needs review", icon: CircleHelp },
};

function displayDate(value: string | null) {
  if (!value) return "Date needs review";
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Date needs review";
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function SourceChips({
  refs,
  documents,
  onSource,
}: {
  refs: string[];
  documents: Document[];
  onSource: (refs: string[]) => void;
}) {
  const groups = new Map<string, { title: string; refs: string[] }>();
  for (const ref of new Set(refs)) {
    const document = documents
      .filter((doc) => ref === doc.id || ref.startsWith(`${doc.id}.`))
      .sort((left, right) => right.id.length - left.id.length)[0];
    if (!document) continue;
    const group = groups.get(document.id) || {
      title: document.title,
      refs: [],
    };
    group.refs.push(ref);
    groups.set(document.id, group);
  }
  return (
    <div className="nmd-source-chips" aria-label="Sources">
      {[...groups].map(([id, group]) => (
        <button
          type="button"
          className="nmd-source-chip"
          key={id}
          onClick={() => onSource(group.refs)}
          aria-label={`View source: ${group.title}`}
        >
          <FileText size={11} aria-hidden="true" />
          <span>{group.title}</span>
          <ArrowUpRight size={11} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

export function CaseTimeline({
  events,
  documents,
  loading,
  pending,
  method,
  availability,
  explanation,
  explaining,
  error,
  onMethodChange,
  onExplain,
  onSource,
  onReview,
}: {
  events: TimelineEvent[];
  documents: Document[];
  loading: boolean;
  pending: number;
  method: CaseAnalysisMethod;
  availability: Record<CaseAnalysisMethod, boolean>;
  explanation: CaseExplanation | null;
  explaining: boolean;
  error: string | null;
  onMethodChange: (method: CaseAnalysisMethod) => void;
  onExplain: () => void;
  onSource: (refs: string[]) => void;
  onReview: () => void;
}) {
  const anyMethod = availability.codex || availability.openai;
  const needsReview =
    pending > 0 ||
    documents.some(
      (doc) => doc.included && Object.keys(doc.fields).length === 0,
    ) ||
    events.some((event) => event.status === "needs_review");
  const hasReviewedFacts = documents.some(
    (doc) =>
      doc.included && Object.values(doc.fields).some((fact) => fact.confirmed),
  );
  const canExplain =
    !loading &&
    !explaining &&
    !needsReview &&
    hasReviewedFacts &&
    availability[method];

  return (
    <section
      className="nmd-case-timeline"
      aria-labelledby="case-timeline-title"
    >
      <div className="nmd-timeline-heading">
        <div>
          <span className="nmd-timeline-eyebrow">THE SEQUENCE</span>
          <h2 id="case-timeline-title">Your case, in order</h2>
          <p>
            Follow the dates on your records and see where the balance needs
            a closer look.
          </p>
        </div>
        <span className="nmd-timeline-count">
          {documents.length} {documents.length === 1 ? "record" : "records"}
        </span>
      </div>

      {explanation && (
        <div className="nmd-ai-overview">
          <div className="nmd-ai-heading">
            <span>
              <Sparkles size={14} aria-hidden="true" /> AI analysis
            </span>
            <small>{methods[explanation.method]}</small>
          </div>
          <p>{explanation.summary.text}</p>
          <SourceChips
            refs={explanation.summary.refs}
            documents={documents}
            onSource={onSource}
          />
        </div>
      )}

      {loading ? (
        <div className="nmd-timeline-loading" role="status">
          <Loader2 className="spin" size={17} aria-hidden="true" />
          Updating the timeline…
        </div>
      ) : events.length ? (
        <ol className="nmd-timeline-track" aria-label="Documents in date order">
          {events.map((event, index) => {
            const status = statuses[event.status];
            const StatusIcon = status.icon;
            const note = explanation?.events.find(
              (item) => item.document_id === event.document_id,
            );
            return (
              <li
                className={`nmd-timeline-item nmd-event-${event.status}`}
                key={event.document_id}
              >
                <div className="nmd-timeline-date">
                  <span className="nmd-timeline-step">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    {event.date ? (
                      <time dateTime={event.date}>
                        {displayDate(event.date)}
                      </time>
                    ) : (
                      <span>{displayDate(null)}</span>
                    )}
                    <small>{event.date_label}</small>
                  </div>
                </div>
                <article className="nmd-timeline-card">
                  <div className="nmd-timeline-role">
                    <FileText size={15} aria-hidden="true" />
                    <span>{roles[event.kind] || event.kind}</span>
                  </div>
                  <h3>{event.title}</h3>
                  <button
                    type="button"
                    className="nmd-timeline-amount"
                    onClick={() =>
                      onSource(
                        event.refs.length ? event.refs : [event.document_id],
                      )
                    }
                    aria-label={`View source for ${event.amount_label}: ${money(event.amount_cents)}`}
                  >
                    <strong>{money(event.amount_cents)}</strong>
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </button>
                  <p className="nmd-timeline-amount-label">
                    {event.amount_label}
                  </p>
                  <div className="nmd-timeline-card-footer">
                    <span
                      className={`nmd-timeline-status nmd-status-${event.status}`}
                    >
                      <StatusIcon size={11} aria-hidden="true" />
                      {status.label}
                    </span>
                    <button
                      type="button"
                      className="nmd-timeline-open"
                      onClick={() =>
                        onSource(
                          event.refs.length ? event.refs : [event.document_id],
                        )
                      }
                      aria-label={`Open ${event.title}`}
                    >
                      Source <ArrowUpRight size={12} aria-hidden="true" />
                    </button>
                  </div>
                  {note && (
                    <div
                      className="nmd-timeline-note"
                      aria-label={`AI explanation for ${event.title}`}
                    >
                      <span className="nmd-timeline-note-label">
                        <Sparkles size={11} aria-hidden="true" /> AI note
                      </span>
                      <p>{note.text}</p>
                      <SourceChips
                        refs={note.refs}
                        documents={documents}
                        onSource={onSource}
                      />
                    </div>
                  )}
                </article>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="nmd-timeline-empty">
          <FileText size={20} aria-hidden="true" />
          <p>Add your documents to see the sequence.</p>
          <button type="button" className="text-button" onClick={onReview}>
            Add documents
          </button>
        </div>
      )}

      <div className="nmd-analysis-controls">
        <div className="nmd-analysis-prompt">
          <span className="nmd-analysis-icon">
            <Sparkles size={17} aria-hidden="true" />
          </span>
          <div>
            <h3>
              {explanation
                ? "Review the explanation"
                : "Understand what happened"}
            </h3>
            <p>
              Get a source-backed explanation and questions to ask the billing
              office.
            </p>
          </div>
        </div>
        <div className="nmd-analysis-actions">
          <label className="sr-only" htmlFor="case-analysis-method">
            Analysis method
          </label>
          <select
            id="case-analysis-method"
            value={method}
            onChange={(event) =>
              onMethodChange(event.target.value as CaseAnalysisMethod)
            }
            aria-describedby="case-analysis-disclosure"
          >
            <option value="codex" disabled={!availability.codex}>
              Codex (ChatGPT sign-in)
            </option>
            <option value="openai" disabled={!availability.openai}>
              OpenAI API
            </option>
          </select>
          <button
            type="button"
            className="button primary"
            disabled={!canExplain}
            onClick={onExplain}
          >
            {explaining ? (
              <Loader2 className="spin" size={15} aria-hidden="true" />
            ) : (
              <Sparkles size={15} aria-hidden="true" />
            )}
            {explaining ? "Explaining…" : "Explain this case"}
          </button>
        </div>
      </div>
      <p className="nmd-analysis-disclosure" id="case-analysis-disclosure">
        {method === "codex"
          ? "Sends reviewed facts and quotes to OpenAI through Codex using your ChatGPT usage."
          : "Sends reviewed facts and quotes to OpenAI. API usage is billed separately."}
      </p>
      {!anyMethod && (
        <p className="nmd-analysis-guidance">
          Connect Codex or add an OpenAI API key to use AI analysis. The
          timeline is available without it.
        </p>
      )}
      {anyMethod && !availability[method] && (
        <p className="nmd-analysis-guidance">
          This method is unavailable. Choose another method or check its setup.
        </p>
      )}
      {needsReview && !loading && (
        <p className="nmd-analysis-guidance">
          Review the marked documents before requesting an explanation.{" "}
          <button type="button" className="text-button" onClick={onReview}>
            Review documents <ArrowUpRight size={12} aria-hidden="true" />
          </button>
        </p>
      )}
      {!needsReview &&
        !hasReviewedFacts &&
        !loading &&
        documents.length > 0 && (
          <p className="nmd-analysis-guidance">
            Include a reviewed document to explain this case.
          </p>
        )}
      {explaining && (
        <p className="nmd-analysis-progress" role="status">
          Reading the reviewed records and checking the sources…
        </p>
      )}
      {error && (
        <p className="nmd-analysis-error" role="alert">
          {error}
        </p>
      )}

      {explanation &&
        (explanation.issues.length > 0 || explanation.questions.length > 0) && (
          <div className="nmd-explanation-details">
            {explanation.issues.length > 0 && (
              <section
                className="nmd-explanation-issues"
                aria-labelledby="case-issues-title"
              >
                <h3 id="case-issues-title">
                  <CircleHelp size={16} aria-hidden="true" /> What to check
                </h3>
                {explanation.issues.map((issue, index) => (
                  <article
                    className="nmd-explanation-issue"
                    key={`${issue.title}-${index}`}
                  >
                    <h4>{issue.title}</h4>
                    <p>{issue.text}</p>
                    <SourceChips
                      refs={issue.refs}
                      documents={documents}
                      onSource={onSource}
                    />
                  </article>
                ))}
              </section>
            )}
            {explanation.questions.length > 0 && (
              <section
                className="nmd-explanation-questions"
                aria-labelledby="case-questions-title"
              >
                <h3 id="case-questions-title">
                  <MessageSquareText size={16} aria-hidden="true" /> Questions
                  for billing
                </h3>
                <ol>
                  {explanation.questions.map((question, index) => (
                    <li key={index}>
                      <p>{question.text}</p>
                      <SourceChips
                        refs={question.refs}
                        documents={documents}
                        onSource={onSource}
                      />
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>
        )}
    </section>
  );
}
