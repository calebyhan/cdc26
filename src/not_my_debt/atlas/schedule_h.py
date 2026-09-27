"""IRS Form 990 Schedule H: nonprofit hospital financial-assistance and collection policies.

Returns are located via the IRS e-file index, then single XML members are read
from the IRS batch ZIPs with HTTP range requests. Values are what filers
reported on Schedule H; they are not audited facts about a hospital's practice.
Facility links to CMS hospitals use ZIP code and name similarity and are
labeled as approximate.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .net import cached_download, get, read_zip_member, zip_directory

INDEX_URL = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv"
DOWNLOADS_PAGE = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
SCHEDULE_H_INSTRUCTIONS = "https://www.irs.gov/instructions/i990sh"

NAME_PATTERN = re.compile(
    r"HOSPITAL|MEDICAL CENTER|MEDICAL CTR|MEDICAL CENTRE|HEALTH ?SYSTEM|HEALTHCARE|HEALTH CARE|"
    r"HEALTH SERVICES|HEALTH NETWORK|REGIONAL HEALTH|HEALTH INC|HEALTH$|\bHOSP\b"
)
NAME_EXCLUDE = re.compile(
    r"FOUNDATION|AUXILIARY|GUILD|ASSOCIATION|\bASSN\b|\bFUND\b|VOLUNTEER|INSURANCE|\bPLAN\b|"
    r"HOME HEALTH|HOSPICE|\bCLUB\b|SOCIETY|ALUMNI|EMPLOYEE|RETIRE|VETERINAR|ANIMAL|\bPET\b"
)
NAME_STOPWORDS = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "THE", "OF", "AND", "CO", "LTD",
    "DBA", "HOSPITAL", "HOSPITALS", "MEDICAL", "CENTER", "CENTERS", "CTR", "HEALTH", "HEALTHCARE",
    "CARE", "SYSTEM", "SYSTEMS", "CAMPUS", "A", "AT", "SERVICES", "MED", "HOSP",
    "ST", "SAINT", "SAINTS", "STS",
}
PERMIT_LABELS = (
    ("Credit", "credit_reporting"),
    ("Sell", "selling_debt"),
    ("Legal", "legal_process"),
    ("Judicial", "legal_process"),
    ("Defer", "defer_or_deny_care"),
    ("Deny", "defer_or_deny_care"),
    ("Other", "other"),
)


def normalize_name(value: str) -> str:
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9 ]", " ", value)
    value = re.sub(r"\b(INC|INCORPORATED|CORP|CORPORATION|LLC|THE|CO|LTD|DBA)\b", " ", value)
    return " ".join(value.split())


def core_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_name(value).split()
        if len(token) > 1 and token not in NAME_STOPWORDS
    }


# A unit hosted inside another hospital (a NICU) or a specialty facility sharing a
# ZIP with a general hospital must not inherit that hospital's policy.
FACILITY_TYPES = {
    "NICU": "nicu",
    "REHAB": "rehab",
    "REHABILITATION": "rehab",
    "BEHAVIORAL": "behavioral",
    "PSYCHIATRIC": "behavioral",
    "PSYCH": "behavioral",
}


def facility_types(value: str) -> set[str]:
    return {FACILITY_TYPES[t] for t in normalize_name(value).split() if t in FACILITY_TYPES}


def similarity(left: str, right: str) -> float:
    if facility_types(left) != facility_types(right):
        return 0.0
    a, b = core_tokens(left), core_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- index


def fetch_index(raw_dir: Path, year: int, *, reuse: bool = True) -> Path:
    return cached_download(INDEX_URL.format(year=year), raw_dir / f"irs_index_{year}.csv", reuse=reuse)


def batch_urls(year: int) -> list[str]:
    html = get(DOWNLOADS_PAGE).decode("utf-8", "replace")
    pattern = rf"https://apps\.irs\.gov/pub/epostcard/990/xml/{year}/{year}_TEOS_XML_\w+?\.zip"
    return sorted(set(re.findall(pattern, html)))


def candidate_returns(index_paths: list[Path], hospital_names: set[str]) -> list[dict]:
    """Latest Form 990 per EIN whose filer name looks like a hospital or matches CMS."""
    latest: dict[str, dict] = {}
    for path in index_paths:
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            for row in csv.DictReader(handle):
                if row.get("RETURN_TYPE") != "990":
                    continue
                name = (row.get("TAXPAYER_NAME") or "").upper()
                normalized = normalize_name(name)
                if not (
                    normalized in hospital_names
                    or (NAME_PATTERN.search(name) and not NAME_EXCLUDE.search(name))
                ):
                    continue
                key = row["EIN"]
                rank = (row.get("TAX_PERIOD") or "", row.get("OBJECT_ID") or "")
                if key not in latest or rank > latest[key]["_rank"]:
                    latest[key] = {**row, "_rank": rank}
    return [
        {
            "ein": row["EIN"],
            "name": row["TAXPAYER_NAME"],
            "tax_period": row["TAX_PERIOD"],
            "object_id": row["OBJECT_ID"],
        }
        for row in latest.values()
    ]


def locate(object_ids: set[str], urls: list[str], cache_path: Path, *, reuse: bool = True) -> dict:
    """Map object IDs to their ZIP member location using each batch's central directory."""
    located: dict[str, dict] = {}
    if reuse and cache_path.exists():
        located = json.loads(cache_path.read_text())
    missing = object_ids - set(located)
    if missing:
        with ThreadPoolExecutor(6) as pool:
            for url, members in zip(urls, pool.map(zip_directory, urls)):
                for member in members:
                    object_id = member["name"].split("/")[-1].split("_")[0]
                    if object_id in missing:
                        located[object_id] = {**member, "url": url}
        cache_path.write_text(json.dumps(located))
    return located


# --------------------------------------------------------------------------- parse


def _parse_xml(xml_text: str) -> ET.Element:
    root = ET.fromstring(xml_text.encode())
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def _flag(element: ET.Element | None, tag: str) -> bool | None:
    if element is None:
        return None
    value = element.findtext(tag)
    if value is None:
        return None
    return value.strip().upper() in {"1", "X", "TRUE"}


def _num(element: ET.Element | None, path: str) -> float | None:
    value = element.findtext(path) if element is not None else None
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def positive_pct(value: float | None) -> float | None:
    """An FPG income limit of 0% is not a threshold; keep it unknown instead."""
    return value if value is not None and value > 0 else None


def _part1_fpg(schedule: ET.Element) -> tuple[float | None, float | None]:
    """Part I lines 3a/3b: FPG thresholds reported as checkbox sequences."""
    free = discounted = None
    section = None
    for child in schedule:
        tag = child.tag
        if tag == "FPGReferenceFreeCareInd":
            section = "free"
        elif tag == "FPGReferenceDiscountedCareInd":
            section = "discounted"
        elif tag in {"FreeCareMedicallyIndigentInd", "FinancialAssistanceBudgetInd"}:
            section = None
        match = re.fullmatch(r"Percent(\d+)Ind", tag)
        value = float(match.group(1)) if match else None
        if tag in {"FreeCareOtherPct", "DiscountedCareOtherPct"}:
            value = _num(schedule, tag)
        if value is not None:
            if section == "free" and free is None:
                free = value
            elif section == "discounted" and discounted is None:
                discounted = value
    return free, discounted


def parse_policy(group: ET.Element) -> dict:
    """Part V Section B for one facility or reporting group.

    Line 18 lists extraordinary collection actions (ECAs) the policy permitted
    *before* reasonable efforts to determine FAP eligibility; line 19 asks whether
    any were taken before those efforts. Neither says whether ECAs occur afterward.
    """
    permitted = []
    for child in group:
        if child.tag.startswith("Permit") and child.tag != "PermitNoActionsInd":
            if (child.text or "").strip().upper() in {"1", "X", "TRUE"}:
                label = next(
                    (name for key, name in PERMIT_LABELS if key in child.tag), child.tag
                )
                if label not in permitted:
                    permitted.append(label)
    criteria = sorted(
        child.tag.removesuffix("CriteriaInd")
        for child in group
        if child.tag.endswith("CriteriaInd") and (child.text or "").strip()
    )
    return {
        "facility_num": group.findtext("FacilityNum"),
        "name": " ".join(
            (group.findtext(f"HospitalFacilityName/BusinessNameLine{n}Txt") or "").strip()
            for n in (1, 2)
        ).strip(),
        "free_fpg": positive_pct(_num(group, "FPGFamilyIncmLmtFreeCarePct")),
        "discount_fpg": positive_pct(_num(group, "FPGFamilyIncmLmtDscntCarePct")),
        "criteria": criteria,
        "fap_url": (group.findtext("FAPAvailableOnWebsiteURLTxt") or "").strip() or None,
        "application_url": (group.findtext("FAPAppAvailableOnWebsiteURLTxt") or "").strip()
        or None,
        "summary_url": (group.findtext("FAPSummaryOnWebsiteURLTxt") or "").strip() or None,
        "notice_on_bills": _flag(group, "NotifiedFAPCopyBillDisplayInd"),
        "translated": _flag(group, "FAPTranslatedInd"),
        "nonpayment_actions_policy": _flag(group, "FAPActionsOnNonpaymentInd"),
        "no_ecas_before_efforts": _flag(group, "PermitNoActionsInd"),
        "ecas_permitted_before_efforts": permitted,
        "ecas_before_reasonable_efforts": _flag(group, "CollectionActivitiesInd"),
        "emergency_care_policy": _flag(group, "NondisEmergencyCarePolicyInd"),
        "charged_more_than_agb": _flag(group, "AmountsGenerallyBilledInd"),
        "charged_gross_charges": _flag(group, "GrossChargesInd"),
    }


def parse_return(xml_text: str) -> dict | None:
    """Extract filer header, Schedule H Part I/III, facilities, and Part V policies."""
    start = xml_text.find("<IRS990ScheduleH")
    if start < 0:
        return None
    root = _parse_xml(xml_text)
    schedule = root.find(".//IRS990ScheduleH")
    if schedule is None:
        return None
    header = root.find("ReturnHeader")
    filer = header.find("Filer") if header is not None else None
    free_fpg, discount_fpg = _part1_fpg(schedule)
    facilities = []
    for group in schedule.findall("HospitalFacilitiesGrp"):
        facilities.append(
            {
                "num": group.findtext("FacilityNum"),
                "name": " ".join(
                    (group.findtext(f"BusinessName/BusinessNameLine{n}Txt") or "").strip()
                    for n in (1, 2)
                ).strip(),
                "city": (group.findtext("USAddress/CityNm") or "").strip(),
                "state": (group.findtext("USAddress/StateAbbreviationCd") or "").strip(),
                "zip": re.sub(r"\D", "", group.findtext("USAddress/ZIPCd") or "")[:5],
                "website": (group.findtext("WebsiteAddressTxt") or "").strip() or None,
                "group": (group.findtext("FacilityReportingGroupCd") or "").strip() or None,
                "emergency_room": _flag(group, "EmergencyRoom24HrsInd"),
            }
        )
    policies = [parse_policy(group) for group in schedule.findall("HospitalFcltyPoliciesPrctcGrp")]
    assign_policies(facilities, policies)
    return {
        "ein": (filer.findtext("EIN") if filer is not None else None),
        "name": (filer.findtext("BusinessName/BusinessNameLine1Txt") if filer is not None else "")
        or "",
        "state": (filer.findtext("USAddress/StateAbbreviationCd") if filer is not None else None),
        "tax_year": header.findtext("TaxYr") if header is not None else None,
        "tax_period_end": header.findtext("TaxPeriodEndDt") if header is not None else None,
        "fap": _flag(schedule, "FinancialAssistancePolicyInd"),
        "written_fap": _flag(schedule, "WrittenPolicyInd"),
        "free_fpg": free_fpg,
        "discount_fpg": discount_fpg,
        "written_collection_policy": _flag(schedule, "WrittenDebtCollectionPolicyInd"),
        "collection_policy_fap_provisions": _flag(schedule, "FinancialAssistancePrvsnInd"),
        "financial_assistance_cost": _num(
            schedule, "FinancialAssistanceAtCostTyp/NetCommunityBenefitExpnsAmt"
        ),
        "financial_assistance_pct_expense": _num(
            schedule, "FinancialAssistanceAtCostTyp/TotalExpensePct"
        ),
        "community_benefit_net": _num(schedule, "TotalCommunityBenefitsGrp/NetCommunityBenefitExpnsAmt"),
        "community_benefit_pct_expense": _num(schedule, "TotalCommunityBenefitsGrp/TotalExpensePct"),
        "bad_debt_expense": _num(schedule, "BadDebtExpenseAmt"),
        "bad_debt_fap_attributable": _num(schedule, "BadDebtExpenseAttributableAmt"),
        "facility_count": len(facilities),
        "facilities": facilities,
        "policies": policies,
    }


def assign_policies(facilities: list[dict], policies: list[dict]) -> None:
    """Attach a policy index to each facility using Part V numbering and group letters.

    Part V Section B is completed per facility (``FacilityNum``) or once per
    reporting group (facilities sharing ``FacilityReportingGroupCd``). Group
    sections are listed in letter order and carry no facility number.
    """
    by_num = {p["facility_num"]: i for i, p in enumerate(policies) if p["facility_num"]}
    ungrouped = [i for i, p in enumerate(policies) if not p["facility_num"]]
    group_letters = []
    for facility in facilities:
        if facility["group"] and facility["group"] not in group_letters:
            group_letters.append(facility["group"])
    by_group = dict(zip(sorted(group_letters), ungrouped))
    for facility in facilities:
        index = None
        if facility["num"] in by_num:
            index = by_num[facility["num"]]
        elif facility["group"] in by_group:
            index = by_group[facility["group"]]
        elif len(policies) == 1:
            index = 0
        elif len(facilities) == 1 and ungrouped:
            index = ungrouped[0]
        facility["policy"] = index


def fetch_parsed(candidate: dict, located: dict, cache_dir: Path) -> dict | None:
    path = cache_dir / f"{candidate['object_id']}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        return cached or None
    member = located.get(candidate["object_id"])
    if not member:
        return None
    xml_text = read_zip_member(member["url"], member).decode("utf-8", "replace")
    parsed = parse_return(xml_text)
    if parsed:
        parsed.update({"object_id": candidate["object_id"], "index_tax_period": candidate["tax_period"]})
    path.write_text(json.dumps(parsed or {}))
    return parsed


def fetch_all(candidates: list[dict], located: dict, cache_dir: Path, workers: int = 16) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)

    def safe(candidate: dict) -> dict | None:
        try:
            return fetch_parsed(candidate, located, cache_dir)
        except Exception:  # one malformed or unreachable return must not stop the build
            return None

    with ThreadPoolExecutor(workers) as pool:
        return [row for row in pool.map(safe, candidates) if row]


# --------------------------------------------------------------------------- linkage


def match_facilities(filers: list[dict], hospitals: list[dict]) -> None:
    """Link Schedule H facilities to CMS hospitals by ZIP (then city) and name overlap."""
    by_zip: dict[str, list[dict]] = {}
    by_city: dict[tuple[str, str], list[dict]] = {}
    for hospital in hospitals:
        by_zip.setdefault(hospital["zip"], []).append(hospital)
        by_city.setdefault((hospital["state"], hospital["city"].upper()), []).append(hospital)
    for filer in filers:
        claimed: set[str] = set()  # one CMS hospital per facility within a filing
        for facility in filer["facilities"]:
            facility["cms_id"] = None
            facility["match"] = None
            candidates = [h for h in by_zip.get(facility["zip"], []) if h["id"] not in claimed]
            scored = sorted(
                ((similarity(facility["name"], h["name"]), h) for h in candidates),
                key=lambda pair: -pair[0],
            )
            if scored and (scored[0][0] >= 0.34 or (len(scored) == 1 and scored[0][0] >= 0.2)):
                facility["cms_id"], facility["match"] = scored[0][1]["id"], "zip+name"
                claimed.add(scored[0][1]["id"])
                continue
            city = [
                h
                for h in by_city.get((facility["state"], facility["city"].upper()), [])
                if h["id"] not in claimed
            ]
            scored = sorted(
                ((similarity(facility["name"], h["name"]), h) for h in city),
                key=lambda pair: -pair[0],
            )
            if scored and scored[0][0] > 0.5:
                facility["cms_id"], facility["match"] = scored[0][1]["id"], "city+name"
                claimed.add(scored[0][1]["id"])
