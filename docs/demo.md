# Presentation demo

All case records are fictional; the default facts are preconfirmed. No live model connection is needed.
The document cards open the original fictional PDFs; **Extracted text** shows the
local parser's source text, and **Download PDF** saves an attachment. Alternate
cases use the matching receipt PDF. Documents without a matching PDF retain
their explicit text fixture. Uploads still require user review.

Run `uv sync --extra dev` and `npm ci`. For rehearsal, `npm run dev` is fine. For the
live presentation, use `npm run build && npm start` to avoid first-request compile
delays. Open http://127.0.0.1:3000 and press **Reset demo** right before presenting.
The deck's slide 8 button opens this address. Record a backup video of this script.

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

Reset restores the receipt, original draft, provider recipient, opening step,
and unreviewed export state. Re-review the packet after changing the evidence.
