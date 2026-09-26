# Uploadable demo documents

All six PDFs are **fictional, one-page, searchable text documents**. They contain
no real patient information and were not supplied by CFPB. The four main PDFs
match Maya's case in the presentation and app fixtures.

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

## Upload into the prototype

1. In the sidebar, open **More cases & tools**, then **Start an empty case**. This
   removes the preloaded example and opens **Evidence & uploads**.
2. Expand **Add a document**. Select its **Document role**, choose
   **Upload a text PDF or TXT**, select the PDF, and click **Extract for review**.
   Leave optional OpenAI extraction unchecked; these files work with the local parser.
3. Open the added document's expander. Compare the extracted facts to the PDF,
   check **I checked every value above against this document**, then select
   **Save reviewed facts**.
4. Repeat for all four PDFs with the roles in the table above.
5. Set **Workspace** to **Presentation demo**, then select **2 · Connect the records**.
   The supplied records should support a possible uncredited $150 payment and a
   $0 reconstructed balance. The notice still requests $150.
6. Select **3 · Prepare a response** to review and export the packet. Original
   PDFs must be attached separately when using that packet; the app sends nothing.

Do not select **Reset demo** or **Load fictional case** after uploading: those
replace the uploaded records. Never upload both a main receipt and its replacement.

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
