# Presentation rehearsal

Implemented with assistance from OpenAI Codex. All case records are fictional;
the default facts are preconfirmed. No live model connection is needed.
The document cards open the original fictional PDFs; **Extracted text** shows the
local parser's source text, and **Download PDF** saves an attachment. Alternate
cases use the matching receipt PDF. Documents without a matching PDF retain
their explicit text fixture. Uploads still require user review.

Run `uv sync --extra dev`, `npm ci`, and `npm run dev`. Open
http://127.0.0.1:3000 and use **Reset case** before rehearsal. The Next.js UI
uses the existing Python engine and Recharts; the legacy Streamlit UI remains available.

| Time | Action | Spoken point |
| --- | --- | --- |
| 0:00–0:20 | Introduce Maya and the four document cards | Her provider bill says $150. She pays. A later collection notice requests $150. |
| 0:20–0:50 | Select Connect the records; click a ledger row or Why this payment matches | Each amount and the possible uncredited-payment finding are linked to records. |
| 0:50–1:15 | Turn Include payment receipt off, then on | Without payment evidence, the app withdraws the payment-supported finding. An EOB is not proof of payment. |
| 1:15–2:00 | Select Prepare a response; under Prepare your response, inspect the summary and inquiry, confirm review, and download | Maya can ask billing for an updated itemized ledger and confirmation of payment allocation. |

The times above are a rehearsal target, not a measured usability result.

Open the exported HTML in a browser to print or save as PDF. It contains source
passages and an attachment index; original files must be attached separately.
The app performs no sending or filing. The current ledger, later reversals,
and legal liability remain unconfirmed.

Keep the research explanation on the presentation slides. The secondary Complaint research
workspace is available for questions; CFPB complaints are reported experiences,
not Maya's documents or verified errors. Documents & review preserves the local
extraction and field-correction path; Explore another case contains alternate cases.

Reset restores the receipt, original draft, provider recipient, opening step,
and unreviewed export state. Re-review the packet after changing the evidence.

## Optional live Codex extraction

The opening demo above uses preconfirmed fictional facts and needs no model call.
To demonstrate live extraction separately, use the installed Codex CLI with your
saved ChatGPT sign-in on the machine running the Next.js/Python server. Complete
the local setup above, then run:

```sh
codex login
codex login status
npm run dev
```

Open **Documents & review**, paste or upload one fictional document, choose
**Codex (ChatGPT sign-in)** under **Extraction method**, and run extraction. Review the proposed fields and
source passages before confirming them. This sends that document's text to OpenAI
and consumes your ChatGPT/Codex usage allowance; it needs an internet connection
but no API key. The adapter uses the installed CLI's default model without passing
`--model`; leave `NMD_CODEX_MODEL` empty unless you have confirmed an account-supported
model identifier. The default timeout is 120 seconds.

If login, model access, usage limits, or extraction fail, the app shows an error.
Select **Local parser** and retry to use the explicit-label parser without a network
request; there is no automatic fallback. **OpenAI API** is a separate option for an environment with
`OPENAI_API_KEY`. Next.js loads local `.env` values on the server; the legacy
Streamlit app requires exported variables. Keep credentials and model settings
server-side without `NEXT_PUBLIC_` prefixes. Rehearse the chosen path before presenting and distinguish a
live model result from the preconfirmed case. A successful fictional example is
not a measured accuracy result on real patient paperwork.

The Codex invocation uses a temporary working directory and `--ephemeral`, so it
does not intentionally keep a persistent rollout for this extraction. Provider
policies still apply. Use this setup for a local fictional demo, not as instructions
for a public service sharing your ChatGPT login. See the [README setup and data handling](../README.md#extraction-and-data-handling),
[OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
and [OpenAI usage limits](https://learn.chatgpt.com/docs/pricing).

## Recorded live check

One live run used Codex CLI 0.152.1, ChatGPT sign-in, and the installed CLI's default
model with no override to extract the four main fictional PDFs in
`sample_documents/`. All 41 normalized fields matched the fixture manifest;
source-quotation and page checks passed. Each document took 9.8–10.5 seconds.
Extracted facts initially required review and were blocked from reconciliation
until confirmed.

After confirmation, the supplied-record ledger applied the $150 payment against
the $150 collection amount, reconstructed a $0 balance, and flagged a possible
uncredited payment. Removing the receipt withdrew that finding and restored the
$150 reconstructed balance. This records one synthetic integration run, not an
accuracy estimate for real patient documents, a performance guarantee, or a legal
conclusion about a debt.
