# Presentation rehearsal

The app starts with an empty case. Use the four fictional PDFs at the top level
of `sample_documents/` for the main story; they contain no real patient information.
User uploads require field review, even when using these files. The secondary
Maya example has preconfirmed fixture facts and remains available for rehearsal.

Run `uv sync --extra dev` and `npm ci`. For rehearsal, `npm run dev` is fine. For the
live presentation, use `npm run build && npm start` to avoid first-request compile
delays. Open http://127.0.0.1:3000 and select **Start over** for a fresh upload case.
The presentation's app link opens this address.
Record a backup video of the upload and review flow.

## Upload and review

1. Under **Start with your documents**, select **Choose documents** and add the
   four main PDFs together. Check each **Document type**: insurance explanation,
   provider bill, payment receipt, and collection notice. Filename guesses can be
   changed; files without a guessed type need a selection.
2. Choose an extractor under **Read with** and select **Read documents**.
   **Local parser** works with these labeled PDFs without sending text to a model.
   **Codex (ChatGPT sign-in)** and **OpenAI API** send the selected documents' text
   to OpenAI. If only some files were extracted, use **Retry failed documents** or
   explicitly **Continue with N documents** to keep the successful files. Do not
   describe skipped files as evidence in the case.
3. On **Check what we read.**, open **Review** for each extracted document. Compare
   the values with their source passages, correct anything needed, select
   **I checked every value above.**, and select **Save reviewed facts**.
4. Choose **Codex (ChatGPT sign-in)** or **OpenAI API** under **Analysis method**,
   then select **Create timeline & explanation**. This is a separate, explicit
   network request using only the included, reviewed facts and reconciliation.
5. After the request succeeds, walk through the timeline and explanation. Follow
   the waterfall from charges to the supplied-record balance; click the receipt
   bar or a source citation. Maya's records support $0 while the notice requests $150.
6. Select **Prepare a response**, inspect the cited records, confirm review, and
   download. Nothing is sent or filed.

To show the deterministic results without a model call, select **View timeline only**
after review. This is a deliberate local-only path, not an automatic fallback.

Rehearse extraction and analysis with the chosen connection before presenting.
A failed request stays visible and does not silently switch to a different method.
If the evidence changes, review it again and explicitly regenerate the explanation.

## Preloaded example walkthrough

Select **Open an example** from **Upload a case** for a shorter Maya walkthrough. Its original PDFs and preconfirmed
facts come from the same fictional records used in the upload flow. Alternate
cases use their matching receipt PDF; documents without a matching PDF retain
their text fixture. This path does not demonstrate live extraction or review.

| Time | Action | Spoken point |
| --- | --- | --- |
| 0:00–0:20 | Introduce Maya and the four document cards | Her provider bill says $150. She pays. A later collection notice requests $150. |
| 0:20–0:55 | Select Connect the records; walk the waterfall from charges to $0; click the Receipt bar | The records support $0; the notice requests $150. Every bar opens its source passage. |
| 0:55–1:20 | Turn Include payment receipt off, then on | The coral discrepancy becomes a neutral “payment evidence is missing.” An EOB is not proof of payment. |
| 1:20–2:15 | Select Prepare a response; point to the cited records in the letter, confirm review, and download | Maya can ask billing for an updated itemized ledger and confirmation of payment allocation. Nothing is sent. |

The times above are a rehearsal target, not a measured usability result.

Open the exported HTML in a browser to print or save as PDF. It contains source
passages and an attachment index; original files must be attached separately.
The app performs no sending or filing. The current ledger, later reversals,
and legal liability remain unconfirmed.

Keep the research explanation on the presentation slides. The secondary Complaint research
workspace is available for questions: it shows company responses, the complaint
language × document heatmap, and the checks those themes shaped. CFPB complaints
are reported experiences, not Maya's documents or verified errors. Documents & review
preserves the local extraction and field-correction path.

For questions about ambiguous evidence, open **Explore another case → Receipt belongs
to another account**, then Connect the records: the receipt is not applied and the
supported balance is withheld (dashed bar) rather than guessed.

**Start over** clears an uploaded case and its queue. **Reset case** restores the
selected preloaded example. Both clear the prior explanation and export approval.
Re-review the packet after changing the evidence.

## Case explanation and source checks

The generated results combine **Your case, in order**, **AI analysis**, **What to
check**, and **Questions for billing**. Timeline dates and amounts come from the
reviewed records and deterministic engine, not the model. Valid reviewed values
may still appear on excluded records. A card marked **Not used in balance** does
not establish an applied payment.

**Create timeline & explanation** is the explicit AI action after review. It sends
included, reviewed values, their source passages, and the current reconciliation
to OpenAI through the selected analysis method. Removing the receipt or changing a
field clears the prior explanation; analysis does not run again automatically.

Source-reference and numeric checks do not establish that the AI's interpretation
is correct. Review each claim, especially where the records disagree or remain
incomplete. A failed request shows an error without a fallback and leaves the
records available for review. **View timeline only** remains an explicit local
option. This explanation is not automatically inserted into the response letter
or exported packet.

Use the same connection setup and privacy considerations described below. The
[recorded case-analysis check](#recorded-case-analysis-check) is separate from the
extraction check later in this guide.

## Recorded upload-to-analysis check

A separate programmatic run processed the four main fictional PDFs through Codex
extraction and case analysis in 57.21 seconds. Analysis was blocked before field
review. All 40 returned facts matched the fixtures; the receipt's `statement_date`
was omitted and left unfilled, while its `payment_date` was present. After review,
the deterministic balance was $0 and the analysis contained four document events.
This check covers the combined integration path, not complete field recall,
real-document accuracy, or browser review time.

## Recorded case-analysis check

A live Codex check used the existing ChatGPT sign-in and the installed CLI's default
model on four fictional bootstrap scenarios. All four outputs passed structural
and citation checks. Inspection found the explanations consistent with the
following deterministic supplied-record balances:

| Scenario | Supported balance | Elapsed time |
| --- | --- | --- |
| `paid` | $0 | 14.2 s |
| `missing_receipt` | $150 | 14.5 s |
| `wrong_account` | Unknown; withheld because the receipt does not match | 15.0 s |
| `partial_payment` | $100 | 15.3 s |

The records and arithmetic were unchanged. These are four synthetic integration
checks, not an accuracy estimate for real patient documents or a performance
guarantee. The OpenAI API analysis path was not live-tested.

## Optional live Codex extraction

To extract the uploaded PDFs with Codex, use the installed CLI with your
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
