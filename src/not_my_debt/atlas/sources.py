"""Public sources, links, and limits shown with the atlas."""

from . import acs, cfpb, cms, geo, prices, schedule_h

SOURCES = [
    {
        "id": "cfpb",
        "name": "CFPB Consumer Complaint Database — Debt collection • Medical debt",
        "url": "https://www.consumerfinance.gov/data-research/consumer-complaints/",
        "api": cfpb.API_BASE,
        "use": "Complaint counts by state, month, issue, company response, and ZIP (2021–Aug 2026).",
        "limits": "Complaints are not a statistical sample and do not establish wrongdoing. "
        "Most name a debt collector, not the hospital or provider that billed.",
    },
    {
        "id": "acs",
        "name": "U.S. Census Bureau, American Community Survey 2020–2024 5-year estimates",
        "url": acs.BASE,
        "use": "Population (B01003), uninsured (B27010), poverty (B17001), median income (B19013), "
        "disability (B18101), and rent burden ≥30% of income (B25070).",
        "limits": "Survey estimates with margins of error; small counties are less precise.",
    },
    {
        "id": "cms",
        "name": "CMS Hospital General Information",
        "url": cms.HOSPITALS_PAGE,
        "use": "Hospital name, ZIP, type, ownership, and emergency services.",
        "limits": "Map points use Census ZIP-area (ZCTA) centroids, not street addresses.",
    },
    {
        "id": "schedule_h",
        "name": "IRS Form 990 e-file XML — Schedule H (Hospitals)",
        "url": schedule_h.DOWNLOADS_PAGE,
        "instructions": schedule_h.SCHEDULE_H_INSTRUCTIONS,
        "use": "Reported financial-assistance income limits, publicity, and extraordinary "
        "collection actions permitted before reasonable efforts to determine eligibility.",
        "limits": "Self-reported filing answers, not audited practice. Returns filed in 2025–2026 "
        "(mostly tax year 2024). Facility links to CMS use ZIP and name similarity.",
    },
    {
        "id": "prices",
        "name": "Hospital price-transparency machine-readable files (via each site's cms-hpt.txt)",
        "url": prices.CMS_PAGE,
        "use": "Gross charge, discounted cash price, and payer-negotiated rates for six "
        "shoppable services at up to four linked nonprofit hospitals per state.",
        "limits": "A bounded sample, not every hospital. Files vary in format and completeness; "
        "posted prices are not what a given patient owes.",
    },
    {
        "id": "geo",
        "name": "Census ZCTA gazetteer and ZCTA-to-county relationship file",
        "url": geo.ZCTA_COUNTY_URL,
        "use": "Approximate hospital points and ZIP-to-county assignment for complaints.",
        "limits": "ZIP codes and ZCTAs differ; masked 3-digit complaint ZIPs cannot be placed in a county.",
    },
    {
        "id": "maps",
        "name": "us-atlas (Census cartographic boundaries, 1:10m)",
        "url": "https://github.com/topojson/us-atlas",
        "use": "State and county outlines.",
        "limits": "2017 county boundaries: Connecticut's 2022 planning regions are not drawn.",
    },
]
