"use client";

import { ExternalLink } from "lucide-react";
import { dollars, safeUrl, type Atlas } from "@/lib/atlas";

/** One hospital's posted prices for the six-service basket. */
export function HospitalPrices({ atlas, hospitalId }: { atlas: Atlas; hospitalId: string }) {
  const entry = atlas.prices.hospitals[hospitalId];
  if (!entry) return null;
  const file = safeUrl(entry.mrf_url);
  return (
    <div className="atlas-prices">
      <h5>Posted prices · common services</h5>
      <table className="atlas-table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Cash price</th>
            <th>Insurer median</th>
            <th>Gross charge</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(atlas.prices.basket).map(([code, label]) => {
            const p = entry.prices[code];
            if (!p) return null;
            return (
              <tr key={code}>
                <td>
                  {label}
                  <small> · {code}</small>
                </td>
                <td>{dollars(p.cash_cents)}</td>
                <td title={`Posted range ${dollars(p.negotiated_min_cents)}–${dollars(p.negotiated_max_cents)} across ${p.payer_rates} payer rates`}>
                  {dollars(p.negotiated_median_cents)}
                </td>
                <td>{dollars(p.gross_cents)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="footnote">
        From the hospital’s machine-readable standard-charge file
        {entry.location_name ? ` (${entry.location_name})` : ""}. Posted prices
        are not what you owe; ask for a good-faith estimate or itemized bill.{" "}
        {file && (
          <a href={file} target="_blank" rel="noreferrer">
            Source file <ExternalLink size={11} />
          </a>
        )}
      </p>
    </div>
  );
}

/** Strip plot: each dot is one sampled hospital's cash price, scaled per service. */
export function StatePriceSpread({ atlas, state }: { atlas: Atlas; state: string }) {
  const hospitals = atlas.hospitals.filter(
    (h) => h.state === state && atlas.prices.hospitals[h.id],
  );
  if (hospitals.length < 2) return null;
  const rows = Object.entries(atlas.prices.basket)
    .map(([code, label]) => {
      const points = hospitals
        .map((h) => ({
          name: h.name,
          cents: atlas.prices.hospitals[h.id].prices[code]?.cash_cents ?? null,
        }))
        .filter((p): p is { name: string; cents: number } => p.cents != null);
      return { code, label, points };
    })
    .filter((row) => row.points.length >= 2);
  if (!rows.length) return null;
  return (
    <div className="atlas-spread">
      <h3>Cash-price spread · {hospitals.length} sampled hospitals</h3>
      <p className="muted small">
        Each dot is one hospital’s posted self-pay price. The same service can
        cost several times more across nearby hospitals.
      </p>
      {rows.map((row) => {
        const values = row.points.map((p) => p.cents);
        const min = Math.min(...values);
        const max = Math.max(...values);
        const x = (cents: number) => (max === min ? 50 : 4 + ((cents - min) / (max - min)) * 92);
        return (
          <div className="atlas-spread-row" key={row.code}>
            <div className="atlas-spread-label">
              {row.label}
              <small>
                {dollars(min)} – {dollars(max)}
                {min > 0 ? ` · ${(max / min).toFixed(1)}×` : ""}
              </small>
            </div>
            <div
              className="atlas-spread-track"
              role="img"
              aria-label={`${row.label}: ${row.points
                .map((p) => `${p.name} ${dollars(p.cents)}`)
                .join(", ")}`}
            >
              {row.points.map((p) => (
                <span
                  key={p.name}
                  style={{ left: `${x(p.cents)}%` }}
                  title={`${p.name}: ${dollars(p.cents)}`}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
