"use client";

import { useEffect, useMemo, useState } from "react";
import { MapPin, X } from "lucide-react";
import {
  fpg,
  loadAtlas,
  num,
  ownershipLabel,
  policyFor,
  type Atlas,
  type Hospital,
  type LinkedPolicy,
} from "@/lib/atlas";
import { HospitalCard, type Community } from "@/app/components/atlas/community-atlas";

/** Questions grounded in the selected hospital's filed policy; no legal conclusions. */
export function communityQuestions(
  hospital: Hospital | null,
  linked: LinkedPolicy | null,
): string[] {
  const questions: string[] = [];
  if (!hospital) {
    return [
      "Which hospital or provider sent the original bill? Choose it above to see its reported financial-assistance policy.",
    ];
  }
  if (linked) {
    const p = linked.policy;
    questions.push(
      `Ask ${hospital.name}’s billing office whether this account was screened for financial assistance before it went to collections, and request an application.`,
    );
    if (p.free_fpg != null)
      questions.push(
        `Its filed policy offers free care up to ${fpg(p.free_fpg)}${
          p.discount_fpg != null ? ` and discounts up to ${fpg(p.discount_fpg)}` : ""
        }. Ask whether your household income qualifies.`,
      );
    questions.push(
      "Ask whether collection activity is paused while a financial-assistance application is pending, and get the answer in writing.",
    );
    if (p.ecas_permitted_before_efforts.length)
      questions.push(
        "Its filing reports that some collection actions were permitted before eligibility was checked. Ask whether any were taken on this account.",
      );
  } else if (hospital.ownership_class === "nonprofit") {
    questions.push(
      `We couldn’t link a Schedule H filing to ${hospital.name}. Ask for its financial-assistance policy, plain-language summary, and application.`,
    );
  } else {
    questions.push(
      `${hospital.name} is ${ownershipLabel[hospital.ownership_class].toLowerCase()}; Schedule H doesn’t apply. Ask whether it offers charity care, a self-pay discount, or an interest-free payment plan.`,
    );
  }
  questions.push(
    "Request an itemized bill and an account ledger that shows every insurance payment, adjustment, and patient payment.",
  );
  return questions;
}

export function CommunityContext({
  community,
  onChange,
  onClear,
}: {
  community: Community;
  onChange: (community: Community) => void;
  onClear: () => void;
}) {
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  useEffect(() => {
    loadAtlas().then(setAtlas).catch(() => setAtlas(null));
  }, []);
  const row = atlas?.summary.states.find((s) => s.state_abbr === community.state);
  const hospitals = useMemo(
    () =>
      (atlas?.hospitals ?? [])
        .filter((h) => h.state === community.state)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [atlas, community.state],
  );
  if (!atlas || !row) return null;
  const hospital = hospitals.find((h) => h.id === community.hospitalId) ?? null;
  const linked = policyFor(atlas, hospital);
  return (
    <div className="panel community-context">
      <div className="community-context-head">
        <div>
          <div className="eyebrow">
            <MapPin size={12} /> YOUR COMMUNITY · PUBLIC DATA
          </div>
          <h2>
            {row.name}: {num(row.rate_per_100k, 1)} reported medical-debt
            collection complaints per 100k residents in {atlas.summary.rate_year}
          </h2>
          <p className="muted small">
            {num(row.ratio_to_national, 1)}× the U.S. rate ·{" "}
            {num(row.paid)} complaints said the debt was already paid. Community
            data give context; your own records decide your case.
          </p>
        </div>
        <button className="icon-button" onClick={onClear} aria-label="Remove community">
          <X size={16} />
        </button>
      </div>
      <label className="community-hospital">
        <span>Hospital that billed you</span>
        <select
          value={community.hospitalId ?? ""}
          onChange={(e) =>
            onChange({ ...community, hospitalId: e.target.value || null })
          }
        >
          <option value="">Choose a hospital in {row.name}</option>
          {hospitals.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name} — {h.city}
            </option>
          ))}
        </select>
      </label>
      <div className="community-context-body">
        {hospital && <HospitalCard atlas={atlas} hospital={hospital} />}
        <div>
          <h3>Questions to ask</h3>
          <ol className="community-questions">
            {communityQuestions(hospital, linked).map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
