"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ChevronDown,
  CircleHelp,
  ExternalLink,
  FileDown,
  Loader2,
  MapPin,
  Search,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import {
  ecaLabel,
  fpg,
  loadAtlas,
  monthLabel,
  num,
  ownershipColor,
  ownershipLabel,
  pct,
  policyFor,
  safeUrl,
  yearOverYear,
  type Atlas,
  type Hospital,
  type Ownership,
  type StateRow,
} from "@/lib/atlas";
import { downloadBriefing } from "@/lib/briefing";
import {
  HospitalPrices,
  StatePriceSpread,
} from "@/app/components/atlas/price-basket";
import {
  BIVARIATE,
  PriorityMap,
  ratioScale,
  sequentialScale,
  stateValue,
  type MapMetric,
} from "@/app/components/atlas/priority-map";

export type Community = { state: string; hospitalId: string | null };
export type AtlasFocus = { state: string | null; hospitalId: string | null; nonce: number };

const metricOptions: { id: MapMetric; label: string; note: string }[] = [
  {
    id: "rate",
    label: "Complaints per 100k residents",
    note: "2025 CFPB medical-debt collection complaints ÷ ACS population",
  },
  {
    id: "adjusted",
    label: "Compared with expected",
    note: "Observed ÷ expected from population, uninsured rate, and poverty rate",
  },
  {
    id: "uninsured_rate_burden",
    label: "Uninsured rate × complaint burden",
    note: "Terciles of each measure across the 50 states and DC",
  },
  {
    id: "per_uninsured",
    label: "Complaints per 10k uninsured",
    note: "2025 complaints ÷ ACS uninsured residents",
  },
];

const OWNERSHIP: Ownership[] = ["nonprofit", "for_profit", "government"];
const TOP_COUNTY_MIN = 20;

export function CommunityAtlas({
  onOpenNavigator,
  focus,
  onSelectionChange,
}: {
  onOpenNavigator: (community: Community) => void;
  /** External request (e.g. from the guide) to show a state/hospital. */
  focus?: AtlasFocus | null;
  onSelectionChange?: (state: string | null, hospitalId: string | null) => void;
}) {
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  const [error, setError] = useState("");
  const [metric, setMetric] = useState<MapMetric>("rate");
  const [selected, setSelected] = useState<string | null>(null);
  const [showBubbles, setShowBubbles] = useState(true);
  const [showHospitals, setShowHospitals] = useState(false);
  const [ownership, setOwnership] = useState<Set<Ownership>>(
    () => new Set(OWNERSHIP),
  );
  const [hospitalId, setHospitalId] = useState<string | null>(null);
  const [seenFocus, setSeenFocus] = useState(0);
  if (focus && focus.nonce !== seenFocus) {
    // Adjust state while rendering in response to a new external focus request.
    setSeenFocus(focus.nonce);
    setSelected(focus.state);
    setHospitalId(focus.hospitalId);
    if (focus.state) setShowHospitals(true);
  }
  useEffect(() => {
    onSelectionChange?.(selected, hospitalId);
  }, [selected, hospitalId, onSelectionChange]);

  useEffect(() => {
    loadAtlas()
      .then((data) => {
        setAtlas(data);
        // Deep link for demos and shared briefings: ?state=GA
        const requested = new URLSearchParams(window.location.search)
          .get("state")
          ?.toUpperCase();
        if (data.summary.states.some((s) => s.state_abbr === requested)) {
          setSelected(requested ?? null);
          setShowHospitals(true);
        }
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const states = useMemo(() => atlas?.summary.states ?? [], [atlas]);
  const scale = useMemo(() => {
    if (metric === "adjusted") return ratioScale;
    const values = states
      .map((row) => stateValue(row, metric))
      .filter((v): v is number => v != null);
    return sequentialScale(
      values,
      metric === "per_uninsured" ? "per 10k uninsured" : "per 100k",
    );
  }, [states, metric]);
  const countyScale = useMemo(
    () =>
      sequentialScale(
        (atlas?.counties.counties ?? [])
          .map((c) => c.annual_rate_per_100k)
          .filter((v): v is number => v != null),
        "per 100k / yr",
      ),
    [atlas],
  );

  if (error)
    return (
      <div className="error" role="alert">
        {error}. Run <code>python scripts/refresh_atlas.py</code> to rebuild
        the public data.
      </div>
    );
  if (!atlas)
    return (
      <div className="loading-screen">
        <Loader2 className="spin" />
        <h2>Loading public data…</h2>
      </div>
    );

  const { summary } = atlas;
  const row = states.find((s) => s.state_abbr === selected);
  const hospital = atlas.hospitals.find((h) => h.id === hospitalId) ?? null;
  const option = metricOptions.find((o) => o.id === metric)!;
  const topAdjusted = [...states]
    .filter((s) => s.adjusted_ratio != null && s.complaints >= 100)
    .sort((a, b) => (b.adjusted_ratio ?? 0) - (a.adjusted_ratio ?? 0))
    .slice(0, 5);

  const selectState = (abbr: string | null) => {
    setSelected(abbr);
    setHospitalId(null);
    if (abbr) setShowHospitals(true);
  };

  return (
    <section className="fade-in atlas">
      <div className="page-heading">
        <div className="eyebrow">COMMUNITY MEDICAL-DEBT PRIORITY MAP</div>
        <h1>Where people may need billing help</h1>
        <p>
          Reported medical-debt collection complaints, adjusted for population
          and insurance coverage, alongside local hospitals and their reported
          financial-assistance policies.
        </p>
      </div>

      <div className="atlas-stats">
        <div className="panel">
          <small>Medical-debt collection complaints · {summary.rate_year}</small>
          <strong>{num(summary.national.count)}</strong>
          <p>{num(summary.national.rate_per_100k, 2)} per 100k residents nationally</p>
        </div>
        <div className="panel">
          <small>Highest vs. expected · states with 100+ complaints</small>
          <strong>{topAdjusted.map((s) => s.state_abbr).slice(0, 3).join(" · ")}</strong>
          <p>
            {topAdjusted
              .slice(0, 3)
              .map((s) => `${s.state_abbr} ${num(s.adjusted_ratio, 1)}×`)
              .join(", ")}{" "}
            the count predicted by population, uninsured and poverty rates
          </p>
        </div>
        <div className="panel">
          <small>Nonprofit hospitals with a linked policy</small>
          <strong>
            {num(summary.counts.cms_nonprofit_with_policy)}
            <span> / {num(summary.counts.cms_nonprofit)}</span>
          </strong>
          <p>CMS nonprofit hospitals matched to an IRS Schedule H filing</p>
        </div>
      </div>

      <div className="atlas-controls" role="group" aria-label="Map controls">
        <label>
          <span>Color states by</span>
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value as MapMetric)}
          >
            {metricOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="atlas-toggle">
          <input
            type="checkbox"
            checked={showBubbles}
            onChange={(e) => setShowBubbles(e.target.checked)}
          />
          Uninsured residents
        </label>
        <label className="atlas-toggle">
          <input
            type="checkbox"
            checked={showHospitals}
            onChange={(e) => setShowHospitals(e.target.checked)}
          />
          Hospitals
        </label>
        {showHospitals && (
          <div className="atlas-ownership" aria-label="Hospital ownership">
            {OWNERSHIP.map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={ownership.has(key)}
                className={ownership.has(key) ? "on" : ""}
                onClick={() =>
                  setOwnership((current) => {
                    const next = new Set(current);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
              >
                <i style={{ borderColor: ownershipColor[key] }} />
                {ownershipLabel[key]}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className={`atlas-layout ${row ? "with-panel" : ""}`}>
        <div className="panel atlas-map-panel">
          <div className="atlas-map-heading">
            <div>
              <h2>{row ? `${row.name} by county` : option.label}</h2>
              <p className="muted small">
                {row
                  ? `Complaints ${atlas.counties.years[0]}–${atlas.counties.years[1]} per 100k residents per year, placed by ZIP code`
                  : option.note}
              </p>
            </div>
            {row && (
              <button
                className="text-button"
                onClick={() => selectState(null)}
              >
                <X size={14} /> National view
              </button>
            )}
          </div>
          <PriorityMap
            states={states}
            metric={metric}
            scale={scale}
            selected={selected}
            onSelect={selectState}
            showBubbles={showBubbles}
            showHospitals={showHospitals}
            ownershipFilter={ownership}
            hospitals={atlas.hospitals}
            counties={atlas.counties}
            countyScale={countyScale}
            onHospital={(h) => {
              setSelected(h.state);
              setHospitalId(h.id);
            }}
            focusHospital={hospitalId}
          />
          <MapLegend
            metric={metric}
            zoomed={Boolean(row)}
            scale={row ? countyScale : scale}
            showBubbles={showBubbles && !row}
            showHospitals={showHospitals}
            minCount={atlas.counties.min_count}
          />
          {!row && (
            <p className="atlas-hint">
              <MapPin size={13} /> Select a state for counties, trends,
              hospitals, and an advocate briefing.
            </p>
          )}
        </div>
        {row && (
          <RegionPanel
            atlas={atlas}
            row={row}
            hospital={hospital}
            onHospital={setHospitalId}
            onClose={() => selectState(null)}
            onOpenNavigator={() =>
              onOpenNavigator({ state: row.state_abbr, hospitalId })
            }
          />
        )}
      </div>

      <SupportGap
        atlas={atlas}
        selected={selected}
        onSelect={selectState}
      />

      <div className="context-note">
        <CircleHelp size={18} />
        <p>
          A complaint is a consumer’s report to the CFPB, not a verified
          finding. Most name a debt collector rather than the hospital that
          billed, and complaint volume reflects awareness of the CFPB as well as
          harm. Hospitals appear as local context; this map does not rank or
          blame facilities.
        </p>
      </div>
      <AtlasMethods atlas={atlas} />
    </section>
  );
}

function MapLegend({
  metric,
  zoomed,
  scale,
  showBubbles,
  showHospitals,
  minCount,
}: {
  metric: MapMetric;
  zoomed: boolean;
  scale: ReturnType<typeof sequentialScale>;
  showBubbles: boolean;
  showHospitals: boolean;
  minCount: number;
}) {
  return (
    <div className="atlas-legend">
      {!zoomed && metric === "uninsured_rate_burden" ? (
        <div className="bivariate-legend">
          <div className="bivariate-grid" aria-hidden>
            {[2, 1, 0].map((burden) =>
              [0, 1, 2].map((need) => (
                <i
                  key={`${burden}${need}`}
                  style={{ background: BIVARIATE[burden][need] }}
                />
              )),
            )}
          </div>
          <div className="bivariate-axes">
            <span>↑ Complaint burden</span>
            <span>Uninsured rate →</span>
          </div>
        </div>
      ) : (
        <div className="atlas-swatches">
          {scale.legend.map((item) => (
            <span key={item.label}>
              <i style={{ background: item.color }} />
              {item.label}
            </span>
          ))}
          {zoomed && (
            <span>
              <i className="hatch" />
              Fewer than {minCount} complaints
            </span>
          )}
        </div>
      )}
      <div className="atlas-swatches">
        {showBubbles && (
          <span>
            <i className="bubble" /> Circle size: uninsured residents
          </span>
        )}
        {showHospitals && (
          <>
            {OWNERSHIP.map((key) => (
              <span key={key}>
                <i
                  className="dot"
                  style={{ borderColor: ownershipColor[key] }}
                />
                {ownershipLabel[key]}
              </span>
            ))}
            <span>
              <i className="dot filled" /> Filled: Schedule H policy linked
            </span>
          </>
        )}
      </div>
    </div>
  );
}

function RegionPanel({
  atlas,
  row,
  hospital,
  onHospital,
  onClose,
  onOpenNavigator,
}: {
  atlas: Atlas;
  row: StateRow;
  hospital: Hospital | null;
  onHospital: (id: string | null) => void;
  onClose: () => void;
  onOpenNavigator: () => void;
}) {
  const { summary } = atlas;
  const [query, setQuery] = useState("");
  const perMillion = (count: number, population: number) =>
    Math.round((count / population) * 1_000_000 * 100) / 100;
  const trend = summary.months.map((month, i) => ({
    label: monthLabel(month),
    state: perMillion(row.monthly[i], row.population),
    national: perMillion(summary.national.monthly[i], summary.national.population),
  }));
  const yoy = yearOverYear(row.monthly);
  const issueRows = summary.national.issues.slice(0, 6).map((issue) => ({
    label: issue.label,
    state: row.complaints
      ? Math.round(
          ((row.issues.find((i) => i.label === issue.label)?.count ?? 0) /
            row.complaints) *
            1000,
        ) / 10
      : 0,
    national: Math.round((issue.count / summary.national.count) * 1000) / 10,
  }));
  const counties = atlas.counties.counties
    .filter(
      (c) =>
        c.state === row.state_abbr &&
        c.annual_rate_per_100k != null &&
        c.complaints >= TOP_COUNTY_MIN,
    )
    .sort((a, b) => (b.annual_rate_per_100k ?? 0) - (a.annual_rate_per_100k ?? 0))
    .slice(0, 8);
  const inState = atlas.hospitals.filter((h) => h.state === row.state_abbr);
  const listed = inState
    .filter(
      (h) =>
        (h.ownership_class === "nonprofit" || h.policy_ref) &&
        h.name.toLowerCase().includes(query.trim().toLowerCase()),
    )
    .sort((a, b) =>
      Number(Boolean(b.policy_ref)) - Number(Boolean(a.policy_ref)) ||
      a.name.localeCompare(b.name),
    );
  const paidShare = row.complaints ? row.paid / row.complaints : null;
  const unmapped = atlas.counties.unmapped_by_state[row.state_abbr] ?? 0;

  return (
    <aside className="panel atlas-region" aria-label={`${row.name} details`}>
      <div className="atlas-region-head">
        <div>
          <div className="eyebrow">{row.state_abbr} · COMMUNITY PROFILE</div>
          <h2>{row.name}</h2>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>
      <div className="atlas-actions">
        <button
          className="button primary"
          onClick={() => downloadBriefing(atlas, row)}
        >
          <FileDown size={15} /> Advocate briefing
        </button>
        <button className="button secondary" onClick={onOpenNavigator}>
          Open evidence navigator <ArrowRight size={15} />
        </button>
      </div>

      <div className="atlas-tiles">
        <div>
          <small>Complaints · {summary.rate_year}</small>
          <strong>{num(row.complaints)}</strong>
          <span>
            {num(row.rate_per_100k, 1)} per 100k (95% CI{" "}
            {num(row.rate_ci[0], 1)}–{num(row.rate_ci[1], 1)})
          </span>
        </div>
        <div>
          <small>vs. national rate</small>
          <strong>{num(row.ratio_to_national, 2)}×</strong>
          <span>
            {row.adjusted_ratio != null
              ? `${num(row.adjusted_ratio, 2)}× after uninsured & poverty rates`
              : "Not modeled"}
          </span>
        </div>
        <div>
          <small>“Debt was paid”</small>
          <strong>{num(row.paid)}</strong>
          <span>{pct(paidShare)} of this state’s complaints</span>
        </div>
      </div>

      <h3>Monthly complaints per 1M residents</h3>
      <p className="muted small">
        Last 12 months: {num(yoy.recent)} complaints
        {yoy.change != null &&
          ` (${yoy.change >= 0 ? "+" : ""}${pct(yoy.change)} vs. the prior 12)`}
        . Through {monthLabel(summary.months[summary.months.length - 1])}.
      </p>
      <div className="atlas-chart">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={trend} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#edf0ec" />
            <XAxis
              dataKey="label"
              interval={11}
              tick={{ fontSize: 10, fill: "#6c7670" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#6c7670" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<SeriesTooltip unit="per 1M residents" />} />
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontSize: 11 }}
              formatter={(value) => <span className="legend-ink">{value}</span>}
            />
            <Line
              name={row.name}
              dataKey="state"
              stroke="#2e6b58"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              name="United States"
              dataKey="national"
              stroke="#9aa39d"
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <h3>What consumers reported · share of complaints</h3>
      <div className="atlas-chart tall">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <BarChart
            data={issueRows}
            layout="vertical"
            margin={{ top: 0, right: 12, left: 0, bottom: 0 }}
            barGap={2}
          >
            <CartesianGrid horizontal={false} stroke="#edf0ec" />
            <XAxis
              type="number"
              unit="%"
              tick={{ fontSize: 10, fill: "#6c7670" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={150}
              tick={{ fontSize: 10, fill: "#52615c" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<SeriesTooltip unit="% of complaints" />} cursor={{ fill: "#f3f6f1" }} />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              formatter={(value) => <span className="legend-ink">{value}</span>}
            />
            <Bar
              name={row.state_abbr}
              dataKey="state"
              fill="#2e6b58"
              barSize={8}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
            />
            <Bar
              name="United States"
              dataKey="national"
              fill="#b7c4bd"
              barSize={8}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <h3>How companies responded</h3>
      <ResponseBars row={row} national={summary.national.responses} />

      <h3>Companies named most often</h3>
      <ol className="atlas-companies">
        {row.top_companies.map((c) => (
          <li key={c.label}>
            <span>{c.label}</span>
            <strong>{num(c.count)}</strong>
          </li>
        ))}
      </ol>
      <p className="footnote">
        The company a consumer complained about — usually a collector, not the
        original provider. A complaint doesn’t establish that it acted
        improperly.
      </p>

      <h3>Community context · ACS 2020–2024</h3>
      <dl className="atlas-facts">
        <div>
          <dt>Uninsured</dt>
          <dd>
            {pct(row.uninsured_rate, 1)} · {num(row.uninsured)} people
          </dd>
        </div>
        <div>
          <dt>Below poverty line</dt>
          <dd>{pct(row.poverty_rate, 1)}</dd>
        </div>
        <div>
          <dt>Median household income</dt>
          <dd>${num(row.median_income)}</dd>
        </div>
        <div>
          <dt>With a disability</dt>
          <dd>{pct(row.disability_rate, 1)}</dd>
        </div>
        <div>
          <dt>Renters paying ≥30% of income</dt>
          <dd>{pct(row.rent_burden_rate, 0)}</dd>
        </div>
      </dl>

      {counties.length > 0 && (
        <>
          <h3>
            Highest county rates · {atlas.counties.years[0]}–
            {atlas.counties.years[1]}
          </h3>
          <table className="atlas-table">
            <thead>
              <tr>
                <th>County</th>
                <th>Complaints</th>
                <th>Per 100k / yr</th>
              </tr>
            </thead>
            <tbody>
              {counties.map((c) => (
                <tr key={c.fips}>
                  <td>{c.name.split(",")[0]}</td>
                  <td>{num(c.complaints)}</td>
                  <td>{num(c.annual_rate_per_100k, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="footnote">
            Counties with at least {TOP_COUNTY_MIN} complaints; smaller
            counts are too unstable to rank.{" "}
            {num(unmapped)} complaints in this state had a masked or unmatched
            ZIP code and are not placed in a county.
          </p>
        </>
      )}

      <h3>Hospitals · CMS</h3>
      <div className="atlas-ownership-counts">
        {OWNERSHIP.map((key) => (
          <span key={key}>
            <i style={{ borderColor: ownershipColor[key] }} />
            {num(row.hospitals[key] ?? 0)} {ownershipLabel[key].toLowerCase()}
          </span>
        ))}
      </div>
      <p className="muted small">
        {num(row.nonprofit_linked)} of {num(row.nonprofit_hospitals)} nonprofit
        hospitals linked to a Schedule H policy. Median free-care limit:{" "}
        {fpg(row.schedule_h.median_free_fpg)}.
      </p>
      {hospital ? (
        <HospitalCard
          atlas={atlas}
          hospital={hospital}
          onBack={() => onHospital(null)}
          onUse={onOpenNavigator}
        />
      ) : (
        <>
          <label className="atlas-search">
            <Search size={14} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a nonprofit hospital"
              aria-label="Find a nonprofit hospital"
            />
          </label>
          <ul className="atlas-hospitals">
            {listed.slice(0, 60).map((h) => {
              const linked = policyFor(atlas, h);
              return (
                <li key={h.id}>
                  <button onClick={() => onHospital(h.id)}>
                    <span>
                      <strong>{h.name}</strong>
                      <small>
                        {h.city} · {ownershipLabel[h.ownership_class]}
                      </small>
                    </span>
                    <small>
                      {h.has_prices ? "Prices · " : ""}
                      {linked
                        ? linked.policy.free_fpg != null
                          ? `Free ≤ ${Math.round(linked.policy.free_fpg)}% FPG`
                          : "Policy linked"
                        : "No filing linked"}
                    </small>
                  </button>
                </li>
              );
            })}
          </ul>
          {listed.length > 60 && (
            <p className="footnote">
              Showing 60 of {listed.length}. Search to narrow the list.
            </p>
          )}
        </>
      )}
      <StatePriceSpread atlas={atlas} state={row.state_abbr} />
    </aside>
  );
}

function ResponseBars({
  row,
  national,
}: {
  row: StateRow;
  national: { label: string; count: number }[];
}) {
  const colors: Record<string, string> = {
    "Closed with explanation": "#b7c4bd",
    "Closed with non-monetary relief": "#2e7d70",
    "Closed with monetary relief": "#263c35",
    "In progress": "#e4d9ac",
    "Untimely response": "#ce8d6e",
  };
  const groups = [
    { label: row.state_abbr, items: row.responses },
    { label: "U.S.", items: national },
  ];
  return (
    <div className="atlas-response">
      {groups.map((group) => {
        const total = group.items.reduce((a, b) => a + b.count, 0);
        return (
          <div className="response-row" key={group.label}>
            <div className="response-label">{group.label}</div>
            <div
              className="response-bar"
              role="img"
              aria-label={`${group.label}: ${group.items
                .map((i) => `${i.label} ${i.count}`)
                .join(", ")}`}
            >
              {group.items.map((item) => (
                <span
                  key={item.label}
                  title={`${item.label}: ${num(item.count)} (${pct(item.count / total)})`}
                  style={{
                    width: `${(100 * item.count) / total}%`,
                    background: colors[item.label] ?? "#d5dbd7",
                  }}
                />
              ))}
            </div>
          </div>
        );
      })}
      <div className="response-legend">
        {Object.entries(colors).map(([label, color]) => (
          <span key={label}>
            <i style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function HospitalCard({
  atlas,
  hospital,
  onBack,
  onUse,
}: {
  atlas: Atlas;
  hospital: Hospital;
  onBack?: () => void;
  onUse?: () => void;
}) {
  const linked = policyFor(atlas, hospital);
  const policy = linked?.policy;
  const link = safeUrl(policy?.fap_url);
  const application = safeUrl(policy?.application_url);
  return (
    <div className="atlas-hospital-card">
      {onBack && (
        <button className="text-button" onClick={onBack}>
          ← All hospitals
        </button>
      )}
      <h4>{hospital.name}</h4>
      <p className="muted small">
        {ownershipLabel[hospital.ownership_class]} · {hospital.type} ·{" "}
        {hospital.city}, {hospital.state}
        {hospital.emergency ? " · Emergency services" : ""}
      </p>
      {linked && policy ? (
        <>
          <dl className="atlas-facts">
            <div>
              <dt>Free care</dt>
              <dd>{policy.free_fpg != null ? `Up to ${fpg(policy.free_fpg)}` : "Not reported"}</dd>
            </div>
            <div>
              <dt>Discounted care</dt>
              <dd>
                {policy.discount_fpg != null
                  ? `Up to ${fpg(policy.discount_fpg)}`
                  : "Not reported"}
              </dd>
            </div>
            <div>
              <dt>Policy notice on bills</dt>
              <dd>{yesNo(policy.notice_on_bills)}</dd>
            </div>
            <div>
              <dt>Translated policy</dt>
              <dd>{yesNo(policy.translated)}</dd>
            </div>
            <div>
              <dt>Collection actions permitted before eligibility is checked</dt>
              <dd>
                {policy.ecas_permitted_before_efforts.length
                  ? policy.ecas_permitted_before_efforts
                      .map((e) => ecaLabel[e] ?? e)
                      .join("; ")
                  : policy.no_ecas_before_efforts
                    ? "None reported"
                    : "Not reported"}
              </dd>
            </div>
            <div>
              <dt>Reported taking such actions before those efforts</dt>
              <dd>{yesNo(policy.ecas_before_reasonable_efforts)}</dd>
            </div>
          </dl>
          <div className="atlas-links">
            {link && (
              <a href={link} target="_blank" rel="noreferrer">
                Financial-assistance policy <ExternalLink size={12} />
              </a>
            )}
            {application && application !== link && (
              <a href={application} target="_blank" rel="noreferrer">
                Application <ExternalLink size={12} />
              </a>
            )}
          </div>
          <p className="footnote">
            From {linked.filer.name}’s Form 990 Schedule H
            {linked.filer.tax_year ? ` for tax year ${linked.filer.tax_year}` : ""}{" "}
            (EIN {linked.filer.ein}). Filers report these answers; they are not
            audited. Linked to this CMS hospital by ZIP code and name.
          </p>
        </>
      ) : (
        <p className="muted small">
          {hospital.ownership_class === "nonprofit"
            ? "No Schedule H filing was linked to this hospital. Ask its billing office for the financial-assistance policy."
            : "Schedule H applies to nonprofit hospitals. Ask this hospital whether it offers charity care or a self-pay discount."}
        </p>
      )}
      <HospitalPrices atlas={atlas} hospitalId={hospital.id} />
      {onUse && (
        <button className="button secondary" onClick={onUse}>
          Use with my records <ArrowRight size={14} />
        </button>
      )}
    </div>
  );
}

const yesNo = (value: boolean | null) =>
  value == null ? "Not reported" : value ? "Yes" : "No";

type TooltipProps = {
  active?: boolean;
  label?: string | number;
  payload?: readonly {
    name?: string | number;
    value?: unknown;
    color?: string;
  }[];
  unit: string;
};

function SeriesTooltip({ active, payload, label, unit }: TooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip" role="status">
      <div className="chart-tooltip-title">{label}</div>
      {payload.map((entry) => (
        <div className="chart-tooltip-value-row" key={String(entry.name)}>
          <span className="chart-tooltip-measure">
            <i style={{ background: entry.color }} />
            {entry.name}
          </span>
          <strong>{typeof entry.value === "number" ? num(entry.value, 1) : "—"}</strong>
        </div>
      ))}
      <div className="chart-tooltip-note">{unit}</div>
    </div>
  );
}

type GapColor = "free" | "eca";

function SupportGap({
  atlas,
  selected,
  onSelect,
}: {
  atlas: Atlas;
  selected: string | null;
  onSelect: (abbr: string) => void;
}) {
  const [x, setX] = useState<"uninsured_rate" | "poverty_rate">("uninsured_rate");
  const [colorBy, setColorBy] = useState<GapColor>("free");
  const { summary } = atlas;
  const groups =
    colorBy === "free"
      ? [
          { id: "high", label: "Median free-care limit ≥ 200% FPG", color: "#2a78d6" },
          { id: "low", label: "Median free-care limit < 200% FPG", color: "#eb6834" },
          { id: "none", label: "No linked nonprofit policy", color: "#b9bdb9" },
        ]
      : [
          { id: "high", label: "No linked facility permits actions before screening", color: "#2a78d6" },
          { id: "low", label: "Some linked facilities permit actions before screening", color: "#eb6834" },
          { id: "none", label: "No linked nonprofit policy", color: "#b9bdb9" },
        ];
  const groupOf = (row: StateRow) => {
    const h = row.schedule_h;
    if (!h.facilities_with_policy) return "none";
    if (colorBy === "free")
      return (h.median_free_fpg ?? 0) >= 200 ? "high" : "low";
    return (h.share_ecas_permitted_before_efforts ?? 0) > 0 ? "low" : "high";
  };
  const points = summary.states
    .filter((row) => row.bivariate)
    .map((row) => ({
      abbr: row.state_abbr,
      name: row.name,
      x: Math.round(row[x] * 1000) / 10,
      y: row.rate_per_100k,
      z: row.population,
      group: groupOf(row),
      row,
    }));
  return (
    <div className="panel atlas-gap">
      <div className="atlas-map-heading">
        <div>
          <h2>Support gap: need vs. reported complaint burden</h2>
          <p className="muted small">
            Each circle is a state, sized by population. Upper right = higher
            need and more reported collection complaints.
          </p>
        </div>
        <div className="atlas-gap-controls">
          <label>
            <span>Horizontal axis</span>
            <select value={x} onChange={(e) => setX(e.target.value as typeof x)}>
              <option value="uninsured_rate">Uninsured rate</option>
              <option value="poverty_rate">Poverty rate</option>
            </select>
          </label>
          <label>
            <span>Color</span>
            <select
              value={colorBy}
              onChange={(e) => setColorBy(e.target.value as GapColor)}
            >
              <option value="free">Free-care income limit</option>
              <option value="eca">Collection actions before screening</option>
            </select>
          </label>
        </div>
      </div>
      <div className="atlas-gap-chart">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ScatterChart margin={{ top: 12, right: 24, bottom: 18, left: -6 }}>
            <CartesianGrid stroke="#edf0ec" />
            <XAxis
              type="number"
              dataKey="x"
              unit="%"
              name={x === "uninsured_rate" ? "Uninsured" : "Poverty"}
              domain={[0, (max: number) => Math.ceil(max / 5) * 5]}
              allowDecimals={false}
              tick={{ fontSize: 10, fill: "#6c7670" }}
              label={{
                value: x === "uninsured_rate" ? "Uninsured rate (ACS)" : "Poverty rate (ACS)",
                position: "insideBottom",
                offset: -10,
                fontSize: 11,
                fill: "#52615c",
              }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Complaints per 100k"
              tick={{ fontSize: 10, fill: "#6c7670" }}
              label={{
                value: `Complaints per 100k · ${summary.rate_year}`,
                angle: -90,
                position: "insideLeft",
                offset: 18,
                fontSize: 11,
                fill: "#52615c",
              }}
            />
            <ZAxis type="number" dataKey="z" range={[140, 1100]} />
            <ReferenceLine
              y={summary.national.rate_per_100k}
              stroke="#9aa39d"
              strokeDasharray="4 3"
              label={{
                value: "U.S. rate",
                position: "insideTopRight",
                fontSize: 10,
                fill: "#6c7670",
              }}
            />
            <Tooltip
              cursor={false}
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as (typeof points)[number] | undefined;
                if (!active || !p) return null;
                const h = p.row.schedule_h;
                return (
                  <div className="chart-tooltip" role="status">
                    <div className="chart-tooltip-title">{p.name}</div>
                    <div className="chart-tooltip-value-row">
                      <span className="chart-tooltip-measure">Complaints per 100k</span>
                      <strong>{num(p.y, 1)}</strong>
                    </div>
                    <div className="chart-tooltip-value-row">
                      <span className="chart-tooltip-measure">
                        {x === "uninsured_rate" ? "Uninsured" : "In poverty"}
                      </span>
                      <strong>{num(p.x, 1)}%</strong>
                    </div>
                    <div className="chart-tooltip-note">
                      {h.facilities_with_policy
                        ? `${h.facilities_with_policy} linked nonprofit hospitals · median free care ≤ ${num(h.median_free_fpg)}% FPG · ${pct(h.share_ecas_permitted_before_efforts)} permit collection actions before screening`
                        : "No linked nonprofit hospital policy"}
                    </div>
                  </div>
                );
              }}
            />
            <Legend
              verticalAlign="top"
              height={30}
              wrapperStyle={{ fontSize: 11 }}
              formatter={(value) => <span className="legend-ink">{value}</span>}
            />
            {groups.map((group) => (
              <Scatter
                key={group.id}
                name={group.label}
                data={points.filter((p) => p.group === group.id)}
                fill={group.color}
                fillOpacity={0.72}
                stroke="#fff"
                strokeWidth={1.5}
                isAnimationActive={false}
                onClick={(point) => {
                  const entry = point as unknown as {
                    abbr?: string;
                    payload?: { abbr?: string };
                  };
                  const abbr = entry.abbr ?? entry.payload?.abbr;
                  if (abbr) onSelect(abbr);
                }}
                shape={(props: unknown) => {
                  const p = props as {
                    cx: number;
                    cy: number;
                    size?: number;
                    payload: (typeof points)[number];
                    fill: string;
                  };
                  const r = Math.sqrt((p.size ?? 60) / Math.PI);
                  const active = p.payload.abbr === selected;
                  return (
                    <g style={{ cursor: "pointer" }}>
                      <circle
                        cx={p.cx}
                        cy={p.cy}
                        r={r}
                        fill={p.fill}
                        fillOpacity={0.72}
                        stroke={active ? "#263c35" : "#fff"}
                        strokeWidth={active ? 2.5 : 1.5}
                      />
                      <text
                        x={p.cx}
                        y={p.cy + 3}
                        textAnchor="middle"
                        fontSize={r > 9 ? 9 : 7.5}
                        fill="#1d2a25"
                        pointerEvents="none"
                      >
                        {p.payload.abbr}
                      </text>
                    </g>
                  );
                }}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <details>
        <summary>
          View states as a table <ArrowDown size={13} />
        </summary>
        <table>
          <thead>
            <tr>
              <th>State</th>
              <th>Uninsured</th>
              <th>Poverty</th>
              <th>Complaints</th>
              <th>Per 100k</th>
              <th>vs. expected</th>
              <th>Median free-care limit</th>
            </tr>
          </thead>
          <tbody>
            {[...summary.states]
              .sort((a, b) => b.rate_per_100k - a.rate_per_100k)
              .map((row) => (
                <tr key={row.fips}>
                  <td>{row.name}</td>
                  <td>{pct(row.uninsured_rate, 1)}</td>
                  <td>{pct(row.poverty_rate, 1)}</td>
                  <td>{num(row.complaints)}</td>
                  <td>{num(row.rate_per_100k, 2)}</td>
                  <td>{row.adjusted_ratio != null ? `${num(row.adjusted_ratio, 2)}×` : "—"}</td>
                  <td>
                    {row.schedule_h.median_free_fpg != null
                      ? `${num(row.schedule_h.median_free_fpg)}% FPG`
                      : "—"}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function AtlasMethods({ atlas }: { atlas: Atlas }) {
  const { summary, manifest } = atlas;
  const c = summary.counts;
  const rr = summary.model.rate_ratio_per_sd;
  return (
    <details className="findings-details">
      <summary>
        Methods, sources & limitations <ChevronDown size={15} />
      </summary>
      {[
        `Complaints: ${num(c.cfpb_records)} CFPB “Debt collection • Medical debt” records received January 2021 – August 2026. Rates use ${summary.rate_year} complaints and ACS 2020–2024 5-year population.`,
        `“Compared with expected” divides each state’s ${summary.rate_year} complaints by a Poisson regression prediction with a population offset. Each standard deviation of uninsured rate multiplies expected complaints by ${num(rr.uninsured_rate, 2)} and of poverty rate by ${num(rr.poverty_rate, 2)} (n = ${summary.model.n}, Puerto Rico excluded). Pearson dispersion is ${num(summary.model.pearson_dispersion, 1)}, so states vary far more than the model explains; read the ratio descriptively.`,
        `County rates pool ${atlas.counties.years[0]}–${atlas.counties.years[1]}: ${num(c.county_complaints_mapped)} of ${num(c.county_complaints)} complaints had a full ZIP code that maps to a county through the Census ZCTA relationship file. Counties with fewer than ${atlas.counties.min_count} complaints show no rate.`,
        `Hospitals: ${num(c.cms_hospitals)} CMS facilities, ${num(c.cms_hospitals_located)} placed at their ZIP area’s center. ${num(c.schedule_h_filers)} Form 990 filers (filed 2025–2026) included Schedule H, listing ${num(c.schedule_h_facilities)} facilities; ${num(c.schedule_h_facilities_linked)} were linked to a CMS hospital by ZIP code and name.`,
        `Prices: a bounded sample of up to four linked nonprofit hospitals per state. ${num(c.price_hospitals_with_basket)} of ${num(c.price_hospitals_attempted)} attempted hospitals published a readable standard-charge file with at least one of six basket services; the rest had no cms-hpt.txt index, no matching location, an oversized file, or an unrecognized format.`,
        "Schedule H line 18 asks which extraordinary collection actions a policy permitted before reasonable efforts to check financial-assistance eligibility. It does not say whether actions happen afterward.",
        "Complaint counts do not measure how much medical debt exists, whether a debt was valid, or which hospital billed. States with more CFPB awareness can show higher rates.",
      ].map((text) => (
        <p className="finding-item" key={text}>
          {text}
        </p>
      ))}
      <div className="atlas-sources">
        {manifest.sources.map((source) => (
          <div key={source.id}>
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.name} <ExternalLink size={12} />
            </a>
            <span>{source.use}</span>
            <small>{source.limits}</small>
          </div>
        ))}
        <small>Built {manifest.generated_at.slice(0, 10)} from public data.</small>
      </div>
    </details>
  );
}
