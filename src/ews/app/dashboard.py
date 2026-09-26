"""Public complaint screening dashboard; all reads use chart-ready Parquet marts."""

import html
import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ews.app.data import BUNDLE, manifest, read

VIEWS = [
    "Risk leaderboard",
    "Company detail",
    "Enforcement timeline",
    "Backtest results",
    "Limitations",
]
BANNER = "Screening tool based on public complaint data. Not a finding of wrongdoing."
REGIME = "CFPB has filed no enforcement action since 2025-08-21. Historical enforcement patterns may not describe the present."
COLORS = [
    "#147D92",
    "#BF7B39",
    "#6E72AB",
    "#497963",
    "#A75567",
    "#344E68",
    "#898B94",
    "#93BAC1",
]


def band(value):
    if pd.isna(value):
        return "unavailable"
    return "low" if value < 0.03 else "elevated" if value < 0.1 else "high"


def probability_cell(value):
    label = band(value)
    tooltip = (
        "Unavailable" if pd.isna(value) else f"historical-regime estimate: {value:.2%}"
    )
    return f'<span class="tier {label}" title="{tooltip}">{label}</span>'


def sparkline(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return ""
    high = max(1, values.max())
    points = " ".join(
        f"{i*100/max(1,len(values)-1):.1f},{25-v/high*23:.1f}"
        for i, v in enumerate(values)
    )
    return f'<svg width="100" height="28" viewBox="0 0 100 28" role="img" aria-label="Last 24 months of complaints"><polyline points="{points}" fill="none" stroke="#147D92" stroke-width="1.6"/></svg>'


def chart(fig, title=None):
    fig.update_layout(
        template="plotly_white",
        colorway=COLORS,
        margin=dict(l=12, r=12, t=40, b=15),
        height=350,
        legend=dict(orientation="h", y=-0.2),
        title=title,
        font=dict(color="#172C42"),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def company_select(key, ids=None):
    entities = read("entities")
    if ids is not None:
        entities = entities[entities.entity_id.isin(ids)]
    entities = entities.sort_values("display_name")
    names = entities.set_index("entity_id").display_name.to_dict()
    options = entities.entity_id.tolist()
    if not options:
        st.info("No companies available for this selection.")
        return None
    preferred = st.query_params.get("company", read("leaderboard").entity_id.iloc[0])
    return st.selectbox(
        "Company",
        options,
        index=options.index(preferred) if preferred in options else 0,
        format_func=lambda e: names[e],
        key=key,
    )


def leaderboard():
    st.title("Risk leaderboard")
    st.caption(
        "Elevated complaint signal · Model A screening score · public mortgage complaint patterns"
    )
    frame = read("leaderboard")
    cols = st.columns([1.2, 1.5, 1, 1.5])
    groups = cols[0].multiselect("Peer group", sorted(frame.peer_group.unique()))
    sizes = cols[1].multiselect("Size band", sorted(frame.size_band.unique()))
    states = read("states")
    state = cols[2].selectbox(
        "Complaint state", ["All"] + sorted(states.state.unique())
    )
    exclude = cols[3].checkbox("Exclude companies with active actions")
    if groups:
        frame = frame[frame.peer_group.isin(groups)]
    if sizes:
        frame = frame[frame.size_band.isin(sizes)]
    if state != "All":
        frame = frame[
            frame.entity_id.isin(states.loc[states.state.eq(state), "entity_id"])
        ]
    if exclude:
        frame = frame[~frame.active_action]
    frame = frame.sort_values(["anomaly_score", "entity_id"], ascending=[False, True])
    a, b, c = st.columns(3)
    a.metric("Companies", len(frame))
    b.metric("Elevated / high risk tier", int(frame.risk_tier.ne("low").sum()))
    c.metric("Score month", manifest()["live_as_of"])
    st.caption(
        "Size bands use trailing complaint volume. State filters use the buffered 12-month complaint geography; scores remain national. Risk tiers: low <0.5, elevated 0.5–<1, high ≥1."
    )
    st.caption(
        "Model B/C columns: historical-regime estimate · low <3%, elevated 3%–<10%, high ≥10%. Hover a band for its numeric value. Frozen pre-2025 models applied to current features; no present-regime calibration claim."
    )
    heads = [
        "Rank",
        "Company",
        "Peer group",
        "Screening score",
        "Risk tier",
        "12m complaints",
        "Normalized rate",
        "Top 3 drivers",
        "24m trend",
    ] + [
        f"{m} p_{h}m<br>historical-regime estimate"
        for m in ["B", "C"]
        for h in [6, 12, 18]
    ]
    rows = []
    for row in frame.itertuples():
        rate = (
            "Unavailable"
            if pd.isna(row.normalized_rate)
            else f"{row.normalized_rate:.2f} {row.rate_basis}"
        )
        cells = [
            str(row.rank),
            f'<a href="?view=Company%20detail&amp;company={row.entity_id}">{html.escape(row.display_name)}</a>',
            html.escape(row.peer_group),
            f"{row.anomaly_score:.3f}",
            f'<span class="tier {row.risk_tier}">{row.risk_tier}</span>',
            f"{row.c_12m:,}",
            html.escape(rate),
            html.escape(row.top_drivers),
            sparkline(row.sparkline),
        ]
        cells += [
            probability_cell(getattr(row, f"{m}_{h}"))
            for m in ["B", "C"]
            for h in [6, 12, 18]
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    st.html(
        '<div class="table-scroll"><table class="screening-table"><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in heads)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    if frame.empty:
        st.info("No companies match these filters.")
    with st.expander("Scoring and action-status definitions"):
        info = manifest()
        st.write(info["action_filter_rule"])
        st.json(info["hazard_sources"])
        st.write(
            "High risk tiers can arise from very few complaints. Always inspect complaint counts and missing exposure denominators before interpreting a screening score."
        )


def enforcement_company(entity_id, shade=False):
    events = read("events", entity_id).sort_values("date_filed")
    if events.empty:
        st.info("No linked enforcement filing in the reviewed source.")
        return
    trend = read("company_trend", entity_id)
    fig = go.Figure(
        go.Scatter(
            x=trend.month,
            y=trend.complaints,
            name="Monthly complaints",
            line=dict(color=COLORS[0]),
        )
    )
    flags = read("flags", entity_id)
    if shade:
        for row in flags.itertuples():
            fig.add_vrect(
                x0=pd.Timestamp(row.cutoff),
                x1=pd.Timestamp(row.cutoff) + pd.DateOffset(months=12),
                fillcolor=COLORS[0],
                opacity=0.07,
                line_width=0,
            )
    for row in events.itertuples():
        fig.add_vline(
            x=pd.Timestamp(row.date_filed).timestamp() * 1000,
            line_dash="dash",
            line_color=COLORS[1],
        )
    fig.update_layout(xaxis_title="Complaint received month", yaxis_title="Complaints")
    chart(fig, "Complaint trend and enforcement filing dates")
    st.dataframe(
        events[["date_filed", "name", "status", "forum", "url"]],
        hide_index=True,
        width="stretch",
        column_config={"url": st.column_config.LinkColumn("Source")},
    )
    if shade:
        earliest = events.date_filed.min()
        prior = flags[pd.to_datetime(flags.cutoff) < earliest]
        if len(prior):
            first = pd.to_datetime(prior.cutoff).min()
            months = (earliest - first).days / 30.4375
            st.write(
                f"First saved top-20 Model A cutoff preceded the first filing by {months:.1f} months."
            )
        else:
            st.write(
                "No saved pre-filing top-20 Model A cutoff in the primary 12-month backtest."
            )
        st.caption(
            "Shading covers the 12-month horizon after each saved annual top-20 cutoff; it does not imply continuously observed ranks."
        )


def ownership(entity_id):
    st.subheader("Ownership and identity history")
    entities = read("entities")
    names = entities.set_index("entity_id").display_name.to_dict()
    relations = read("relationships")
    parent_edges = relations[
        relations.relationship.isin(["parent", "ownership", "subsidiary_of"])
    ]
    ancestors, cursor, visited = [], entity_id, set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        ancestors.append(cursor)
        match = parent_edges[parent_edges.entity_id.eq(cursor)]
        cursor = str(match.iloc[0].successor_entity_id) if len(match) else ""
    if len(ancestors) > 1:
        labels = [names.get(e, e) for e in ancestors[::-1]]
        fig = go.Figure(
            go.Scatter(
                x=[0] * len(labels),
                y=list(range(len(labels))),
                mode="lines+markers+text",
                text=labels,
                textposition="middle right",
                hoverinfo="text",
            )
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        chart(fig, "Reviewed parent chain")
    else:
        st.info(manifest()["ownership_coverage"])
    related = relations[
        relations.entity_id.eq(entity_id) | relations.successor_entity_id.eq(entity_id)
    ]
    if len(related):
        st.dataframe(
            related[
                ["relationship", "effective_date", "old_name", "new_name", "evidence"]
            ],
            hide_index=True,
            width="stretch",
            column_config={"evidence": st.column_config.LinkColumn("Evidence")},
        )
    aliases = read("aliases", entity_id)
    with st.expander("Reviewed names and FDIC merger history"):
        st.dataframe(aliases, hide_index=True, width="stretch")
        st.dataframe(read("bank_history", entity_id), hide_index=True, width="stretch")


def company_detail():
    st.title("Company detail")
    entity_id = company_select("detail_company")
    if entity_id is None:
        return
    trend = read("company_trend", entity_id)
    if trend.empty:
        st.info("No observed company-month features for this entity.")
        return
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=trend.month,
            y=trend.peer_high,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=trend.month,
            y=trend.peer_low,
            fill="tonexty",
            mode="lines",
            line=dict(width=0),
            fillcolor="rgba(20,125,146,.12)",
            name="Peer interquartile band",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=trend.month,
            y=trend.peer_median,
            name="Peer median",
            line=dict(dash="dot", color=COLORS[1]),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=trend.month,
            y=trend.complaints,
            name="Company complaints",
            line=dict(color=COLORS[0]),
        )
    )
    changes = trend[trend.change_point.fillna(False)]
    fig.add_trace(
        go.Scatter(
            x=changes.month,
            y=changes.complaints,
            mode="markers",
            marker=dict(symbol="diamond", size=9, color=COLORS[2]),
            name="Change-point marker",
        )
    )
    chart(fig, "Monthly complaints versus peers")
    st.caption(
        manifest()["change_point_rule"]
        + ". Complaint counts use received month; model features retain a full calendar-month publication buffer."
    )
    left, right = st.columns(2)
    with left:
        rates = trend.melt(
            id_vars="month",
            value_vars=["c_per_bn_assets", "c_per_1k_orig"],
            var_name="basis",
            value_name="rate",
        ).dropna()
        if len(rates):
            rates["basis"] = rates.basis.map(
                {
                    "c_per_bn_assets": "Per $1bn assets",
                    "c_per_1k_orig": "Per 1,000 HMDA originations",
                }
            )
            chart(
                px.line(rates, x="month", y="rate", color="basis"),
                "Complaint rate by available exposure",
            )
        else:
            st.info(
                "Comparable exposure denominator unavailable. HMDA measures originations, not servicing; FDIC covers banks only."
            )
    with right:
        response = trend[["month", "relief_share_12m", "untimely_rate_12m"]].copy()
        response["Timely response share"] = 1 - response.untimely_rate_12m / 100
        response["Relief share"] = response.relief_share_12m
        melted = response.melt(
            id_vars="month",
            value_vars=["Timely response share", "Relief share"],
            var_name="measure",
            value_name="share",
        )
        fig = px.line(melted, x="month", y="share", color="measure")
        fig.update_yaxes(tickformat=".0%")
        chart(fig, "Trailing 12-month response and relief shares")
    issues = read("issue_mix", entity_id)
    if len(issues):
        issues["severity"] = "Tier " + issues.severity_tier.astype(str)
        chart(
            px.area(
                issues.groupby(["month", "severity"], as_index=False).complaints.sum(),
                x="month",
                y="complaints",
                color="severity",
                color_discrete_map={
                    "Tier 1": "#94BDBB",
                    "Tier 2": "#D5AB65",
                    "Tier 3": "#A96B7C",
                },
            ),
            "Issue mix by severity tier",
        )
        with st.expander("Complaint issue breakdown"):
            chart(
                px.area(issues, x="month", y="complaints", color="issue_std"),
                "Issue categories",
            )
    st.subheader("Financial condition")
    current = trend.iloc[-1]
    if pd.notna(current.assets_lag):
        a, b, c = st.columns(3)
        a.metric("Assets ($bn)", f"{current.assets_lag/1_000_000:.2f}")
        b.metric(
            "Equity / assets",
            (
                f"{current.equity_to_assets_lag:.1%}"
                if pd.notna(current.equity_to_assets_lag)
                else "Unavailable"
            ),
        )
        c.metric(
            "Noncurrent loans / loans",
            (
                f"{current.noncurrent_ratio_lag:.1%}"
                if pd.notna(current.noncurrent_ratio_lag)
                else "Unavailable"
            ),
        )
        financial = trend.melt(
            id_vars="month",
            value_vars=[
                "equity_to_assets_lag",
                "noncurrent_ratio_lag",
                "provision_ratio_lag",
            ],
            var_name="measure",
            value_name="ratio",
        )
        chart(
            px.line(financial, x="month", y="ratio", color="measure"),
            "Financial condition over time",
        )
        st.caption(
            f"FDIC report: {current.fdic_report_date} · Available from: {current.fdic_available_from}"
        )
    else:
        st.info("No current FDIC financial condition coverage for this company.")
    if pd.notna(current.hmda_denial_rate_lag):
        st.write(
            f"HMDA {int(current.hmda_year)} denial rate screening indicator: {current.hmda_denial_rate_lag:.1%}. This does not establish discrimination."
        )
    ownership(entity_id)
    st.subheader("Enforcement timeline")
    enforcement_company(entity_id)
    st.subheader("Why flagged: screening score drivers")
    drivers = read("drivers", entity_id)
    if len(drivers):
        chart(
            px.bar(
                drivers,
                x="contribution",
                y="label",
                orientation="h",
                color="contribution",
                color_continuous_scale=["#94BDBB", "#147D92"],
            ),
            "Contribution to Model A screening score",
        )
        st.caption(
            "Signed contributions versus peers. These are descriptive complaint and financial signals."
        )
    else:
        st.info(
            "No live Model A drivers available; this entity may have exited through merger or closure."
        )


def enforcement_timeline():
    st.title("Enforcement timeline")
    entity_id = company_select("timeline_company", read("events").entity_id.unique())
    if entity_id:
        enforcement_company(entity_id, shade=True)
    if entity_id:
        aligned = read("event_company", entity_id)
        events = read("events", entity_id)
        if len(aligned):
            names = events.set_index("action_id").name.to_dict()
            action_id = st.selectbox(
                "Align to filing",
                sorted(aligned.action_id.unique()),
                format_func=lambda x: names.get(x, x),
            )
            rows = aligned[aligned.action_id.eq(action_id)].sort_values(
                "relative_month"
            )
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=rows.relative_month,
                    y=rows.complaints,
                    name="Company complaints",
                    line=dict(color=COLORS[0]),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=rows.relative_month,
                    y=rows.peer_median,
                    name="Peer median",
                    line=dict(color=COLORS[1], dash="dot"),
                )
            )
            fig.add_vline(x=0, line_dash="dash", annotation_text="Filing")
            flags = read("flags", entity_id)
            event_date = pd.Timestamp(rows.date_filed.iloc[0])
            earlier = flags[pd.to_datetime(flags.cutoff) < event_date]
            for row in earlier.itertuples():
                offset = (
                    (pd.Timestamp(row.cutoff).year - event_date.year) * 12
                    + pd.Timestamp(row.cutoff).month
                    - event_date.month
                )
                fig.add_vrect(
                    x0=offset,
                    x1=offset + 12,
                    fillcolor=COLORS[0],
                    opacity=0.07,
                    line_width=0,
                )
            if len(earlier):
                first = pd.to_datetime(earlier.cutoff).min()
                lead = (event_date - first).days / 30.4375
                fig.add_annotation(
                    x=0.02,
                    y=0.98,
                    xref="paper",
                    yref="paper",
                    text=f"Earliest saved top-20 screening cutoff: {lead:.1f} months before filing",
                    showarrow=False,
                    xanchor="left",
                )
            fig.update_xaxes(
                range=[-48, 12], title="Months relative to selected filing"
            )
            fig.update_yaxes(title="Monthly complaints")
            chart(fig, "Selected company aligned to filing")
    st.subheader("Event-aligned aggregate: companies with filings versus matched peers")
    aggregate = read("event_aggregate")
    fig = go.Figure()
    for group, label, color in [
        ("case", "Companies with filings", COLORS[0]),
        ("peer", "Matched peers", COLORS[1]),
    ]:
        rows = aggregate[aggregate.series.eq(group)]
        fig.add_trace(
            go.Scatter(
                x=rows.relative_month,
                y=rows.high,
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=rows.relative_month,
                y=rows.low,
                line=dict(width=0),
                fill="tonexty",
                fillcolor=(
                    "rgba(20,125,146,.10)"
                    if group == "case"
                    else "rgba(191,123,57,.10)"
                ),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=rows.relative_month,
                y=rows.value,
                name=label,
                line=dict(color=color),
                customdata=rows[["n_pairs", "low", "high"]],
                hovertemplate="Month %{x}<br>Index %{y:.2f}<br>Pairs %{customdata[0]}<br>95% CI [%{customdata[1]:.2f}, %{customdata[2]:.2f}]<extra>%{fullData.name}</extra>",
            )
        )
    fig.add_vline(x=0, line_dash="dash", annotation_text="First filing")
    fig.update_xaxes(range=[-48, 12], title="Months relative to filing")
    fig.update_yaxes(title="Trailing 12m complaints / own −48m baseline (add one)")
    chart(fig)
    info = manifest()["event_chart"]
    st.caption(
        f"{info['pairs']} eligible matched pairs; 95% company-cluster bootstrap intervals. {info['matching']}. Descriptive association; post-filing data never enter model inputs."
    )
    with st.expander("Matched pairs and coverage exclusions"):
        st.dataframe(read("event_pairs"), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(info["excluded"]), hide_index=True, width="stretch")


def backtest_results():
    st.title("Backtest results")
    metrics = read("metrics")
    a, b, c = st.columns(3)
    window = a.selectbox("Evaluation window", ["primary", "secondary"])
    policy = b.selectbox("Dismissal policy", ["include", "exclude_confirmed"])
    horizon = c.selectbox("Horizon (months)", [6, 12, 18], index=1)
    st.caption(
        "Primary: outcomes through 2024-12-31. Secondary: through 2025-08-31. Dismissals describe case status, not merits. 95% company-cluster bootstrap intervals; undefined metrics remain unavailable."
    )
    selected = metrics[
        metrics.window.eq(window)
        & metrics.policy.eq(policy)
        & metrics.horizon.eq(horizon)
    ]
    models = st.multiselect(
        "Models and baselines",
        sorted(selected.model.unique()),
        default=sorted(selected.model.unique()),
    )
    selected = selected[selected.model.isin(models)]
    temporal = selected[selected.cutoff.ne("pooled")].copy()
    temporal["cutoff"] = pd.to_datetime(temporal.cutoff)
    for metric, title in [("precision_20", "Precision@20"), ("pr_auc", "PR-AUC")]:
        if metric not in temporal:
            st.error(f"M4 metric column missing: {metric}")
            continue
        fig = go.Figure()
        for number, (model, rows) in enumerate(temporal.groupby("model", sort=True)):
            rows = rows.sort_values("cutoff")
            fig.add_trace(
                go.Scatter(
                    x=rows.cutoff,
                    y=rows[metric],
                    name=model,
                    mode="lines+markers",
                    line=dict(color=COLORS[number % len(COLORS)]),
                    error_y=dict(
                        type="data",
                        symmetric=False,
                        array=rows[metric + "_high"] - rows[metric],
                        arrayminus=rows[metric] - rows[metric + "_low"],
                    ),
                )
            )
        fig.update_yaxes(range=[0, 1])
        chart(fig, title + " by cutoff · 95% confidence intervals")
    st.subheader("Top 20 at a historical cutoff")
    a, b = st.columns(2)
    cutoff = a.selectbox(
        "Cutoff", sorted(temporal.cutoff.dt.strftime("%Y-%m-%d").unique())
    )
    model = b.selectbox("Hit-table model", models or ["A"])
    hits = read("hits")
    hits = hits[
        hits.window.eq(window)
        & hits.policy.eq(policy)
        & hits.horizon.eq(horizon)
        & hits.cutoff.eq(cutoff)
        & hits.model.eq(model)
    ].copy()
    if len(hits):
        hits["Event within horizon"] = hits.outcome.map(
            {0: "No observed filing", 1: "Observed filing"}
        )
        columns = [
            "rank",
            "display_name",
            "Event within horizon",
            "event_date",
            "c_12m",
        ]
        if model not in ["B", "C"]:
            hits["screening score"] = hits.score
            columns.insert(2, "screening score")
        else:
            label = "historical-regime estimate"
            hits[label] = hits.score.map(band)
            columns.insert(2, label)
            hover = go.Figure(
                go.Scatter(
                    x=hits["rank"],
                    y=hits[label],
                    mode="markers",
                    text=hits.display_name,
                    customdata=hits[["score"]],
                    hovertemplate="%{text}<br>historical-regime estimate: %{customdata[0]:.2%}<extra></extra>",
                )
            )
            chart(hover, "Historical-regime estimate bands · numeric values on hover")
        display = hits[columns]

        def highlight(row):
            return [
                (
                    "background-color: #DBEEE5"
                    if row["Event within horizon"] == "Observed filing"
                    else ""
                )
            ] * len(row)

        st.dataframe(
            display.style.apply(highlight, axis=1), hide_index=True, width="stretch"
        )
    else:
        st.info(
            "This model was unavailable at the selected cutoff; no substitute scores are shown."
        )
    st.subheader("Lead time")
    leads = read("leads")
    leads = leads[
        leads.window.eq(window)
        & leads.policy.eq(policy)
        & leads.horizon.eq(horizon)
        & leads.model.isin(models)
    ]
    chart(
        px.histogram(
            leads, x="lead_months", color="model", nbins=18, barmode="overlay"
        ),
        "Earliest observed top-20 hit per company/model",
    )
    st.subheader("Error review")
    st.caption(
        "False-positive and miss categories are retrospective evaluation labels. No observed filing is not evidence of lawful or unlawful conduct. M4 error reviews cover the primary/include/12-month analysis only."
    )
    errors = read("errors")
    errors = errors[errors.model.isin(models)]
    kind = st.selectbox("Review category", ["All", "false_positive", "miss"])
    if kind != "All":
        errors = errors[errors.kind.eq(kind)]
    # Hazard numeric scores stay out of rendered tables and downloads.
    st.dataframe(
        errors[
            [
                "cutoff",
                "model",
                "display_name",
                "kind",
                "rank",
                "category",
                "c_12m",
                "event_date",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    with st.expander("Metric availability and pooled estimates"):
        st.dataframe(
            selected[
                [
                    "cutoff",
                    "model",
                    "status",
                    "events",
                    "n_cutoffs",
                    "precision_20",
                    "precision_20_low",
                    "precision_20_high",
                    "pr_auc",
                    "pr_auc_low",
                    "pr_auc_high",
                ]
            ],
            hide_index=True,
            width="stretch",
        )


def limitations():
    st.title("Limitations")
    for title, text in [
        (
            "Interpretation",
            "A screening score describes complaint patterns. Enforcement also depends on priorities, resources, and politics. CFPB uses complaints in supervision, so circularity can make this tool a mirror of regulatory attention. Absence of enforcement establishes neither innocence nor wrongdoing.",
        ),
        (
            "Complaint data",
            "Complainants are self-selected. Filing awareness and services vary across populations and time. The 2017 taxonomy crosswalk and older severity mapping are approximate. Complaints have publication lag; scoring uses a full calendar-month buffer. Response values change after publication; refreshes re-pull a trailing 30-day window.",
        ),
        (
            "Exposure and narratives",
            "HMDA measures originations, not servicing; FDIC financial data covers banks only. Missing denominators remain unavailable. CFPB stopped publishing narratives on 2026-08-14; the frozen FOIA archive barely covers recent months. This dashboard does not use narratives.",
        ),
        (
            "Statistical uncertainty",
            "Few events yield imprecise estimates; charts show confidence intervals. Pre-2025 historical-regime estimates may not describe the current regime. Several 2025 actions were dismissed; case status does not establish merits. Entity-resolution errors can create false links; M4 includes sensitivity analysis. Merger and bankruptcy censoring can create survivorship bias, which remains unresolved.",
        ),
        (
            "Identity and status coverage",
            "NIC/GLEIF parent chains were deferred in M2. Reviewed names, entity relationships, and FDIC history are shown without inferring missing parents. The active-action filter conservatively includes pending litigation and post-order/post-judgment statuses. Current status summaries cannot establish whether every order remains active.",
        ),
        (
            "Ethics and screening indicators",
            "Named companies are real. Complaint signals and HMDA denial rates do not establish misconduct or discrimination. Political context and dismissals are presented factually without attributing motives. Live Model A rankings make no enforcement accuracy claim.",
        ),
        (
            "Operational limits",
            "The CCDB API can return HTML with status 200 and silently ignore parameters. Ingestion validates JSON and filter bounds, and fails loudly. Exposure and reviewed identity sources are archived; daily complaint refreshes do not replace the separate FDIC/HMDA release-review process. Few events, source layout changes, missing exposure data, and model performance below baselines remain project risks.",
        ),
    ]:
        st.subheader(title)
        st.write(text)
    st.link_button(
        "Read full project limitations",
        "https://github.com/calebyhan/cdc26/blob/main/docs/10_risks_limitations.md",
    )


def run():
    started = time.perf_counter()
    st.set_page_config(
        page_title="Mortgage complaint screening", page_icon="◈", layout="wide"
    )
    st.html("""<style>
    .screening-table{border-collapse:collapse;width:100%;font-size:12px;background:white}
    .screening-table th{background:#EAF0F5;text-align:left;padding:12px;white-space:nowrap}
    .screening-table td{padding:10px 12px;border-bottom:1px solid #EAF0F5;min-width:90px;max-width:280px}
    .screening-table td:nth-child(2){min-width:220px;font-weight:600}
    .screening-table td:nth-child(8){min-width:250px}.table-scroll{overflow-x:auto;max-height:600px}
    .tier{border-radius:10px;padding:3px 9px;white-space:nowrap}.low{background:#EAF0F5}.elevated{background:#F5EAD3}.high{background:#EDDCE1}
    </style>""")
    st.sidebar.title("Mortgage screening")
    initial = st.query_params.get("view", VIEWS[0])
    view = st.sidebar.radio(
        "View", VIEWS, index=VIEWS.index(initial) if initial in VIEWS else 0
    )
    st.query_params["view"] = view
    st.info(BANNER + " [Read limitations](?view=Limitations).")
    st.warning(REGIME)
    if not (BUNDLE / "manifest.json").exists():
        st.error(
            "M4 dashboard bundle missing. Run python -m ews.app.precompute after M4."
        )
        st.stop()
    info = manifest()
    meta = info.get("ccdb_meta", {})
    st.sidebar.caption(f"CCDB last indexed: {meta.get('last_indexed','Unavailable')}")
    st.sidebar.caption(
        f"Last successful refresh: {info.get('last_successful_refresh') or 'Not yet recorded'}"
    )
    st.sidebar.caption(f"Bundle built: {info['built_at']}")
    if meta.get("is_data_stale") or meta.get("has_data_issue"):
        st.warning(
            "CCDB reports stale data or a data issue. Interpret freshness and recent trends with care."
        )
    if not meta:
        st.warning(
            "CCDB freshness metadata unavailable; bundle build time does not establish source freshness."
        )
    {
        VIEWS[0]: leaderboard,
        VIEWS[1]: company_detail,
        VIEWS[2]: enforcement_timeline,
        VIEWS[3]: backtest_results,
        VIEWS[4]: limitations,
    }[view]()
    elapsed = time.perf_counter() - started
    st.caption(
        f"View prepared in {elapsed:.2f}s · Precomputed Parquet marts via DuckDB"
    )
    st.session_state["render_seconds"] = elapsed
