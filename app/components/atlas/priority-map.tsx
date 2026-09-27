"use client";

import { useEffect, useMemo, useState } from "react";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import {
  num,
  ownershipColor,
  ownershipLabel,
  pct,
  type CountyData,
  type Hospital,
  type Ownership,
  type StateRow,
} from "@/lib/atlas";

export type MapMetric = "rate" | "adjusted" | "uninsured_rate_burden" | "per_uninsured";

type Shape = Feature<Geometry, { name: string }> & { id?: string | number };

const WIDTH = 975;
const HEIGHT = 610;
const path = geoPath();
// Matches the pre-projected us-atlas Albers files (975 × 610).
const projection = geoAlbersUsa().scale(1300).translate([487.5, 305]);

type Shapes = { states: Shape[]; counties: Shape[] | null };
const shapeCache: {
  states?: Promise<Shape[]>;
  counties?: Promise<Shape[]>;
} = {};

function loadShapes(file: string, object: string): Promise<Shape[]> {
  return fetch(`/atlas/${file}`)
    .then((response) => {
      if (!response.ok) throw new Error("Map outlines didn’t load");
      return response.json();
    })
    .then((topo: Topology) => {
      const collection = feature(
        topo,
        topo.objects[object] as GeometryCollection<{ name: string }>,
      ) as FeatureCollection<Geometry, { name: string }>;
      return collection.features as Shape[];
    });
}
const loadStates = () =>
  (shapeCache.states ??= loadShapes("states-albers-10m.json", "states"));
const loadCounties = () =>
  (shapeCache.counties ??= loadShapes("counties-albers-10m.json", "counties"));

/** One-hue sequential ramp (light → dark), anchored to the app's green. */
export const SEQUENTIAL = [
  "#e6f1ea",
  "#c5e0cf",
  "#9dcab0",
  "#71ae8c",
  "#4a906c",
  "#2e6b58",
  "#1b4a3b",
];
/** Diverging: blue (below expected) ↔ gray ↔ orange-red (above expected). */
export const DIVERGING = [
  "#256abf",
  "#6da7ec",
  "#b7d3f6",
  "#e4e3df",
  "#f6c3a8",
  "#eb8a5e",
  "#c4471b",
];
/** 3×3 bivariate grid indexed [burden][need]. */
export const BIVARIATE = [
  ["#e8e8e8", "#e4acac", "#c85a5a"],
  ["#b0d5df", "#ad9ea5", "#985356"],
  ["#64acbe", "#627f8c", "#574249"],
];
const NO_DATA = "#f1f1ee";
/** Counties with too few complaints for a stable rate. */
export const LOW_COUNT = "#f3f4f0";

export type Scale = {
  color: (value: number | null | undefined) => string;
  legend: { color: string; label: string }[];
};

function quantileBreaks(values: number[], steps: number) {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  return Array.from({ length: steps - 1 }, (_, i) => {
    const q = sorted[Math.floor(((i + 1) * sorted.length) / steps)];
    return q >= 10 ? Math.round(q) : Math.round(q * 10) / 10;
  }).filter((v, i, all) => i === 0 || v > all[i - 1]);
}

export function sequentialScale(values: number[], unit: string): Scale {
  const breaks = quantileBreaks(values, SEQUENTIAL.length);
  const ramp = SEQUENTIAL.slice(SEQUENTIAL.length - breaks.length - 1);
  const color = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return NO_DATA;
    const index = breaks.findIndex((b) => value < b);
    return ramp[index === -1 ? breaks.length : index];
  };
  const legend = ramp.map((c, i) => ({
    color: c,
    label:
      i === 0
        ? `< ${breaks[0]}`
        : i === breaks.length
          ? `≥ ${breaks[i - 1]}`
          : `${breaks[i - 1]}–${breaks[i]}`,
  }));
  legend[legend.length - 1].label += ` ${unit}`;
  return { color, legend };
}

const ratioBreaks = [0.5, 0.75, 0.9, 1.1, 1.33, 2];
export const ratioScale: Scale = {
  color: (value) => {
    if (value == null) return NO_DATA;
    const index = ratioBreaks.findIndex((b) => value < b);
    return DIVERGING[index === -1 ? ratioBreaks.length : index];
  },
  legend: [
    { color: DIVERGING[0], label: "< 0.5×" },
    { color: DIVERGING[1], label: "0.5–0.75×" },
    { color: DIVERGING[2], label: "0.75–0.9×" },
    { color: DIVERGING[3], label: "About as expected" },
    { color: DIVERGING[4], label: "1.1–1.33×" },
    { color: DIVERGING[5], label: "1.33–2×" },
    { color: DIVERGING[6], label: "≥ 2× expected" },
  ],
};

type Props = {
  states: StateRow[];
  metric: MapMetric;
  scale: Scale;
  selected: string | null;
  onSelect: (abbr: string | null) => void;
  showBubbles: boolean;
  showHospitals: boolean;
  ownershipFilter: Set<Ownership>;
  hospitals: Hospital[];
  counties: CountyData;
  countyScale: Scale;
  onHospital: (hospital: Hospital) => void;
  focusHospital: string | null;
};

type Hover = { x: number; y: number; title: string; lines: string[] } | null;

export function stateValue(row: StateRow | undefined, metric: MapMetric) {
  if (!row) return null;
  if (metric === "rate") return row.rate_per_100k;
  if (metric === "adjusted") return row.adjusted_ratio ?? null;
  if (metric === "per_uninsured") return row.per_10k_uninsured;
  return null;
}

export function PriorityMap(props: Props) {
  const {
    states,
    metric,
    scale,
    selected,
    onSelect,
    showBubbles,
    showHospitals,
    ownershipFilter,
    hospitals,
    counties,
    countyScale,
    onHospital,
    focusHospital,
  } = props;
  const [hover, setHover] = useState<Hover>(null);
  const [shapes, setShapes] = useState<Shapes>({ states: [], counties: null });
  const stateShapes = shapes.states;
  const countyShapes = shapes.counties;
  useEffect(() => {
    let live = true;
    loadStates().then((states) => {
      if (live) setShapes((current) => ({ ...current, states }));
    });
    return () => {
      live = false;
    };
  }, []);
  const byFips = useMemo(
    () => new Map(states.map((row) => [row.fips, row])),
    [states],
  );
  const countyByFips = useMemo(
    () => new Map(counties.counties.map((row) => [row.fips, row])),
    [counties],
  );
  const selectedRow = states.find((row) => row.state_abbr === selected);
  const selectedShape = stateShapes.find(
    (shape) => String(shape.id) === selectedRow?.fips,
  );

  useEffect(() => {
    if (!selected || countyShapes) return;
    let live = true;
    loadCounties().then((counties) => {
      if (live) setShapes((current) => ({ ...current, counties }));
    });
    return () => {
      live = false;
    };
  }, [selected, countyShapes]);

  const view = useMemo(() => {
    if (!selectedShape) return { k: 1, x: 0, y: 0 };
    const [[x0, y0], [x1, y1]] = path.bounds(selectedShape);
    const k = Math.min(
      8,
      0.86 / Math.max((x1 - x0) / WIDTH, (y1 - y0) / HEIGHT),
    );
    return {
      k,
      x: WIDTH / 2 - (k * (x0 + x1)) / 2,
      y: HEIGHT / 2 - (k * (y0 + y1)) / 2,
    };
  }, [selectedShape]);

  const bubbles = useMemo(() => {
    const max = Math.max(...states.map((s) => s.uninsured || 0));
    return stateShapes
      .map((shape) => {
        const row = byFips.get(String(shape.id));
        if (!row?.uninsured) return null;
        const [cx, cy] = path.centroid(shape);
        return { row, cx, cy, r: 2 + 20 * Math.sqrt(row.uninsured / max) };
      })
      .filter(Boolean) as { row: StateRow; cx: number; cy: number; r: number }[];
  }, [states, byFips, stateShapes]);

  const visibleHospitals = useMemo(() => {
    if (!showHospitals) return [];
    return hospitals
      .filter(
        (h) =>
          h.lat != null &&
          h.lon != null &&
          ownershipFilter.has(h.ownership_class) &&
          (!selected || h.state === selected),
      )
      .map((h) => {
        const point = projection([h.lon as number, h.lat as number]);
        return point ? { h, x: point[0], y: point[1] } : null;
      })
      .filter(Boolean) as { h: Hospital; x: number; y: number }[];
  }, [hospitals, showHospitals, ownershipFilter, selected]);

  const stateCounties = useMemo(
    () =>
      selectedRow && countyShapes
        ? countyShapes.filter((shape) =>
            String(shape.id).startsWith(selectedRow.fips),
          )
        : [],
    [countyShapes, selectedRow],
  );

  const fillFor = (row: StateRow | undefined) => {
    if (!row) return NO_DATA;
    if (metric === "uninsured_rate_burden") {
      return row.bivariate
        ? BIVARIATE[row.bivariate[1]][row.bivariate[0]]
        : NO_DATA;
    }
    return scale.color(stateValue(row, metric));
  };

  const k = view.k;
  const show = (
    event: React.MouseEvent,
    title: string,
    lines: string[],
  ) => {
    const box = (
      event.currentTarget.closest("svg") as SVGSVGElement
    ).getBoundingClientRect();
    setHover({
      x: event.clientX - box.left,
      y: event.clientY - box.top,
      title,
      lines,
    });
  };

  const stateLines = (row: StateRow) => [
    `${num(row.complaints)} complaints in 2025 · ${num(row.rate_per_100k, 1)} per 100k residents`,
    row.adjusted_ratio != null
      ? `${num(row.adjusted_ratio, 2)}× the count expected from population, uninsured and poverty rates`
      : "Not included in the national model",
    `${pct(row.uninsured_rate, 1)} uninsured · ${pct(row.poverty_rate, 1)} in poverty`,
  ];

  return (
    <div className="atlas-map" onMouseLeave={() => setHover(null)}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={
          selectedRow
            ? `${selectedRow.name}: counties and hospitals`
            : "United States medical-debt complaint map"
        }
      >
        <rect
          width={WIDTH}
          height={HEIGHT}
          fill="transparent"
          onClick={() => onSelect(null)}
        />
        <g
          className="atlas-zoom"
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${k})`,
          }}
        >
          {stateShapes.map((shape) => {
            const row = byFips.get(String(shape.id));
            const active = row?.state_abbr === selected;
            return (
              <path
                key={String(shape.id)}
                d={path(shape) || ""}
                className={`atlas-state ${active ? "active" : ""} ${
                  selected && !active ? "muted" : ""
                }`}
                fill={selected && !active ? "#f4f5f2" : fillFor(row)}
                tabIndex={row ? 0 : -1}
                aria-label={row ? `${row.name}` : undefined}
                onClick={(event) => {
                  event.stopPropagation();
                  if (row) onSelect(active ? null : row.state_abbr);
                }}
                onKeyDown={(event) => {
                  if (row && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    onSelect(active ? null : row.state_abbr);
                  }
                }}
                onMouseMove={(event) =>
                  row && !active && show(event, row.name, stateLines(row))
                }
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
          {stateCounties.map((shape) => {
            const row = countyByFips.get(String(shape.id));
            const rate = row?.annual_rate_per_100k;
            return (
              <path
                key={String(shape.id)}
                d={path(shape) || ""}
                className="atlas-county"
                fill={rate == null ? LOW_COUNT : countyScale.color(rate)}
                onMouseMove={(event) =>
                  show(event, row?.name || shape.properties.name, [
                    row
                      ? `${num(row.complaints)} complaints mapped, ${counties.years[0]}–${counties.years[1]}`
                      : "No ACS match for this boundary",
                    rate == null
                      ? `Rate not shown (fewer than ${counties.min_count} complaints)`
                      : `${num(rate, 1)} per 100k residents per year`,
                    row
                      ? `${pct(row.uninsured_rate, 1)} uninsured · ${pct(row.poverty_rate, 1)} in poverty`
                      : "",
                  ])
                }
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
          {selectedShape && (
            <path
              d={path(selectedShape) || ""}
              className="atlas-state-outline"
            />
          )}
          {showBubbles &&
            !selected &&
            bubbles.map(({ row, cx, cy, r }) => (
              <circle
                key={row.fips}
                cx={cx}
                cy={cy}
                r={r}
                className="atlas-bubble"
                onClick={() => onSelect(row.state_abbr)}
                onMouseMove={(event) =>
                  show(event, row.name, [
                    `${num(row.uninsured)} uninsured residents (${pct(row.uninsured_rate, 1)})`,
                    ...stateLines(row).slice(0, 1),
                  ])
                }
                onMouseLeave={() => setHover(null)}
              />
            ))}
          {visibleHospitals.map(({ h, x, y }) => (
            <circle
              key={h.id}
              cx={x}
              cy={y}
              r={(selected ? 2.4 : 1.6) / Math.sqrt(k)}
              className={`atlas-hospital ${h.policy_ref ? "linked" : ""} ${
                focusHospital === h.id ? "focus" : ""
              }`}
              stroke={ownershipColor[h.ownership_class]}
              fill={h.policy_ref ? ownershipColor[h.ownership_class] : "#fff"}
              strokeWidth={selected ? 1.4 : 0.8}
              onClick={(event) => {
                event.stopPropagation();
                onHospital(h);
              }}
              onMouseMove={(event) =>
                show(event, h.name, [
                  `${ownershipLabel[h.ownership_class]} · ${h.type}`,
                  `${h.city}, ${h.state} ${h.zip} (ZIP-area location)`,
                  h.policy_ref
                    ? "Schedule H financial-assistance policy linked"
                    : h.ownership_class === "nonprofit"
                      ? "No Schedule H policy linked"
                      : "Schedule H applies to nonprofit hospitals",
                ])
              }
              onMouseLeave={() => setHover(null)}
            />
          ))}
        </g>
      </svg>
      {hover && (
        <div
          className="atlas-tooltip"
          style={{
            left: Math.min(hover.x + 14, 9999),
            top: hover.y + 14,
          }}
        >
          <strong>{hover.title}</strong>
          {hover.lines.filter(Boolean).map((line) => (
            <span key={line}>{line}</span>
          ))}
        </div>
      )}
    </div>
  );
}
