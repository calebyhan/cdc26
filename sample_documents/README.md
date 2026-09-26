# Uploadable demo documents

All six PDFs are **fictional, one-page, searchable text documents**. They contain
no real patient information and were not supplied by CFPB. The four main PDFs
match Maya's case in the presentation and app fixtures. The PDFs omit demo badges
and AI footers; their fictional origin is documented here.

Upload **only the four PDFs at the top level** for the main story:

| File | Select this document role | Key fact |
| --- | --- | --- |
| `01_insurance_explanation.pdf` | Insurance explanation | $150 patient responsibility; not proof of payment |
| `02_provider_bill.pdf` | Provider bill | July 15 balance $150, before Maya's payment |
| `03_payment_receipt.pdf` | Payment receipt | $150 completed payment on July 20 for account MG-1042 |
| `04_collection_notice.pdf` | Collection notice | August 15 request for $150 on that same account |

Names, dates, identifiers, and amounts are generated from
[`example_documents()`](../src/not_my_debt/examples.py). The collection document is
an explicitly simplified notice excerpt, not a legally complete notice template.
Its September 20, 2026 dispute date belongs to the fictional scenario; it is not
a live deadline.

## Use in the Next.js demo

The default case already loads facts and original quotes extracted locally from
these PDFs. They are preconfirmed because they are known fictional fixtures.
Open a document card to view **Original PDF**, switch to **Extracted text**, or
**Download PDF**. Ledger citations also link to the original fictional PDFs.
Corrections preserve the original source. Alternate cases automatically select
the matching receipt PDF; the later zero-balance text fixtures have no PDF.

To demonstrate the upload and review path:

1. Open **Explore another case**, then **Start an empty case**. This opens
   **Documents & review**.
2. In **Add a document**, select **Document role** and choose a PDF. Under
   **Extraction method**, choose **Local parser** to extract without a network
   request, then click **Extract for review**. For live AI extraction, first run
   `codex login` in a terminal on the same machine running the app, then choose
   **Codex (ChatGPT sign-in)** instead. That option sends the document text to
   OpenAI and uses your ChatGPT/Codex allowance. **OpenAI API** is a separate option
   when the server has `OPENAI_API_KEY` configured.
3. Click **Review** on the added document. Compare its values to the source,
   check **I checked every value above.**, then **Save reviewed facts**.
4. Repeat for the four main PDFs with the roles in the table above.
5. Select **Check the balance**. The supplied records should support a
   possible uncredited $150 payment and a $0 reconstructed balance. The notice
   still requests $150.
6. Select **Prepare a response**. Under **Prepare your response**, review and
   export the packet. Attach original PDFs separately when using that packet;
   the app sends nothing.

If extraction fails, the app shows an error and does not automatically use another
method. Select **Local parser** and retry explicitly to use the local
parser. These fictional PDFs are designed to work with it.

Do not select **Reset case** or change the selected case after uploading: those
replace the uploaded records. Never upload both a main receipt and its replacement.
User uploads require review and remain in memory; only the committed fictional
PDFs are served by the original-document endpoint.

## Useful demo variations

Start an empty case each time and use the three non-receipt documents above:

| Receipt to use | Expected behavior after reviewing fields |
| --- | --- |
| No receipt | Withdraw the payment-supported finding; report missing payment evidence |
| `variants/03_payment_receipt_partial_payment.pdf` | Apply $50, leaving $100 in the supplied-record ledger |
| `variants/03_payment_receipt_wrong_account.pdf` | Flag account MG-9999 as a mismatch; do not apply its $150 to MG-1042 |

The outputs describe the supplied documents, not confirmed current balances,
debt cancellation, or legal liability. All examples are synthetic regression cases.

## Regenerate and verify

From the repository root, after the normal `uv sync --extra dev` setup:

```sh
uv run --with reportlab==5.0.1 python scripts/generate_sample_documents.py
uv run pytest -q tests/test_sample_documents.py
```

`manifest.json` records the expected fields of every PDF. Labels are deliberately
compatible with the local parser, and each label/value is kept on one extractable
text line. The PDFs exercise document upload and reconciliation; they are not
a benchmark of general document understanding or OCR.

Created with assistance from OpenAI Codex for fictional document design,
generation code, and verification.
