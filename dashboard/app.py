"""Streamlit dashboard for Autopatch."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.config import settings
from app.db import (
    get_all_quality_scores,
    get_all_sessions,
    get_events_for_session,
    get_or_create_budget,
    init_db,
    set_budget,
    set_session_acu,
)

st.set_page_config(page_title="Autopatch", layout="wide", initial_sidebar_state="collapsed")

# Minimal CSS — only custom classes, nothing that touches Streamlit internals.
# config.toml handles primaryColor (tab underline, slider, buttons).
st.markdown("""
<style>
.block-container { padding: 1.8rem 2.2rem !important; max-width: 1100px !important; }

.kpi-val { font-size: 2.4rem; font-weight: 700; line-height: 1.05; color: #111; letter-spacing: -0.02em; }
.kpi-lbl { font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.09em; color: #aaa; margin-top: 0.3rem; }

.sec-hdr { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.11em; color: #bbb; margin: 1.5rem 0 0.6rem; }

.empty-wrap { padding: 2.8rem 2rem; text-align: center; }
.empty-head { font-size: 0.95rem; font-weight: 600; color: #333; margin-bottom: 0.3rem; }
.empty-sub  { font-size: 0.8rem; color: #aaa; }

.prog-wrap { background: #ebebea; border-radius: 6px; height: 8px; overflow: hidden; margin: 0.5rem 0; }
.prog-bar  { height: 100%; border-radius: 6px; }

.card-t { font-size: 0.88rem; font-weight: 600; color: #111; margin: 0 0 0.2rem; }
.card-d { font-size: 0.76rem; color: #999; line-height: 1.5; margin: 0 0 0.6rem; }

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {display: none;}
</style>
""", unsafe_allow_html=True)

init_db()

# ── Plotly theme ──────────────────────────────────────────────────────────────
PL = dict(
    paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
    font=dict(color="#888", size=11),
    margin=dict(l=8, r=8, t=20, b=8),
    xaxis=dict(showgrid=True, gridcolor="#eeeeec", linecolor="#e0e0de", tickfont=dict(size=10, color="#aaa")),
    yaxis=dict(showgrid=True, gridcolor="#eeeeec", linecolor="#e0e0de", tickfont=dict(size=10, color="#aaa")),
)

# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def load_sessions() -> pd.DataFrame:
    rows = get_all_sessions()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["started_at"] = pd.to_datetime(df["started_at"])
    return df

@st.cache_data(ttl=15)
def load_quality() -> pd.DataFrame:
    rows = get_all_quality_scores()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

@st.cache_data(ttl=15)
def load_budget() -> dict:
    return dict(get_or_create_budget(settings.daily_acu_budget))

def _cost_per_pr(df: pd.DataFrame) -> float | None:
    # Include pr_opened — a PR was created and cost was incurred regardless of CI outcome
    with_pr = df[df["status"].isin(["ci_passed", "merged", "completed", "pr_opened"]) & (df["acu_spent"] > 0)]
    if with_pr.empty:
        return None
    return round(with_pr["acu_spent"].mean() * settings.acu_usd_rate, 2)

def _hours_saved(df: pd.DataFrame) -> float:
    return len(df[df["status"].isin(["ci_passed", "merged", "completed", "pr_opened"])]) * 4.0

df         = load_sessions()
quality_df = load_quality()
budget     = load_budget()

# ── Header ────────────────────────────────────────────────────────────────────
hc1, hc2 = st.columns([4, 1])
with hc1:
    st.markdown("## Autopatch")
with hc2:
    repo_url = f"https://github.com/{settings.github_owner}/{settings.github_repo}"
    st.markdown(
        f"<div style='text-align:right;padding-top:0.6rem'>"
        f"<a href='{repo_url}' style='font-size:0.75rem;color:#aaa;text-decoration:none;'>"
        f"{settings.github_owner}/{settings.github_repo}</a></div>",
        unsafe_allow_html=True,
    )

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "Throughput", "Cost", "Sessions", "Controls"])

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Overview
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    # ── Scanners ──────────────────────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Scanners</div>", unsafe_allow_html=True)
    REPO_PATH = settings.superset_repo_path
    MAX_ISSUES = st.number_input("Max issues", min_value=1, max_value=15, value=5)

    sc1, sc2, sc3 = st.columns(3)

    with sc1:
        with st.container(border=True):
            st.markdown("<p class='card-t'>CVE Scan</p><p class='card-d'>Scan requirements via OSV and create GitHub issues for vulnerable deps.</p>", unsafe_allow_html=True)
            if st.button("Run scan", key="scan_live", type="primary", use_container_width=True):
                with st.spinner("Scanning…"):
                    r = subprocess.run(
                        ["python", "scripts/scan_cves.py", "--repo-path", REPO_PATH, "--max-issues", str(MAX_ISSUES)],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)

    with sc2:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Dry Run</p><p class='card-d'>Preview CVE scan output — no GitHub issues created.</p>", unsafe_allow_html=True)
            if st.button("Preview", key="scan_dry", use_container_width=True):
                with st.spinner("Scanning…"):
                    r = subprocess.run(
                        ["python", "scripts/scan_cves.py", "--repo-path", REPO_PATH, "--max-issues", str(MAX_ISSUES), "--dry-run"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)

    with sc3:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Quality Scan</p><p class='card-d'>Run mypy on superset/utils and create type-hint issues.</p>", unsafe_allow_html=True)
            if st.button("Run scan", key="scan_quality", use_container_width=True):
                with st.spinner("Running mypy…"):
                    r = subprocess.run(
                        ["python", "scripts/scan_quality.py", "--repo-path", REPO_PATH],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)

    st.divider()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    merged_count = len(df[df["status"].isin(["ci_passed", "merged", "completed"])]) if not df.empty else 0
    cost_per_pr  = _cost_per_pr(df) if not df.empty else None
    hours        = _hours_saved(df) if not df.empty else 0.0

    cost_str = f"${cost_per_pr:.2f}" if cost_per_pr is not None else "—"

    c1, c2, c3 = st.columns(3)
    for col, val, lbl in [
        (c1, str(merged_count), "CVEs closed"),
        (c2, cost_str,          "Avg cost / PR"),
        (c3, f"{hours:.0f} hrs", "Eng. time saved"),
    ]:
        with col:
            st.markdown(
                f"<div class='kpi-val'>{val}</div><div class='kpi-lbl'>{lbl}</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    if df.empty:
        with st.container(border=True):
            st.markdown(
                "<div class='empty-wrap'>"
                "<div class='empty-head'>No sessions yet</div>"
                "<div class='empty-sub'>Go to Controls, run a CVE scan, and Devin will start working.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sessions",   len(df))
        c2.metric("PRs opened", len(df[df["pr_url"].notna()]))
        c3.metric("CI passed",  merged_count)
        c4.metric("Failed",     len(df[df["status"] == "failed"]))

        st.markdown("<div class='sec-hdr'>PRs closed per day</div>", unsafe_allow_html=True)
        week_dates = [(pd.Timestamp.today() - pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
        closed = df[df["status"].isin(["ci_passed", "merged", "completed"])].copy()
        closed["date"] = closed["started_at"].dt.strftime("%Y-%m-%d")
        daily_counts = closed[closed["date"].isin(week_dates)].groupby("date").size()
        daily = pd.DataFrame({"date": week_dates, "count": [daily_counts.get(d, 0) for d in week_dates]})

        fig = go.Figure(go.Bar(
            x=daily["date"], y=daily["count"],
            marker_color="#6366F1", marker_line_width=0,
            hovertemplate="%{x}<br>%{y} PR(s)<extra></extra>",
        ))
        bar_layout = {**PL, "showlegend": False, "height": 220}
        bar_layout["xaxis"] = dict(type="category", tickfont=dict(size=10, color="#aaa"), showgrid=False)
        bar_layout["yaxis"] = dict(showgrid=True, gridcolor="#eeeeec", dtick=1, tickfont=dict(size=10, color="#aaa"))
        fig.update_layout(**bar_layout)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.divider()
    st.markdown(
        f"<span style='font-size:0.75rem;color:#aaa;'>"
        f"<a href='{repo_url}/issues?q=label:devin-remediate' style='color:#aaa;'>Open issues</a>"
        f" · <a href='https://app.devin.ai/sessions' style='color:#aaa;'>Devin sessions</a></span>",
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Throughput
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    if df.empty:
        with st.container(border=True):
            st.markdown(
                "<div class='empty-wrap'>"
                "<div class='empty-head'>No data yet</div>"
                "<div class='empty-sub'>Run a scan from Controls to start tracking sessions.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        total     = len(df)
        ci_pass   = len(df[df["status"].isin(["ci_passed", "merged"])])
        first_try = len(df[(df["status"].isin(["ci_passed", "merged"])) & (df["retry_count"] == 0)])

        c1, c2, c3 = st.columns(3)
        c1.metric("CI pass rate",   f"{ci_pass/total*100:.0f}%" if total else "—")
        c2.metric("First-try pass", f"{first_try/total*100:.0f}%" if total else "—")
        if not quality_df.empty:
            c3.metric("Avg quality", f"{quality_df['total_score'].mean():.1f} / 100")

        st.markdown("<div class='sec-hdr'>Session funnel</div>", unsafe_allow_html=True)
        STATUS_ORDER = ["queued", "running", "pr_opened", "ci_failed_retrying", "ci_passed", "failed", "budget_killed"]
        COLORS       = ["#ccc", "#999", "#555", "#c9914a", "#111", "#ddd", "#e0cfc0"]
        counts = [len(df[df["status"] == s]) for s in STATUS_ORDER]
        fig = go.Figure(go.Bar(
            x=counts, y=STATUS_ORDER, orientation="h",
            marker_color=[COLORS[i] if counts[i] > 0 else "#f0f0ee" for i in range(len(STATUS_ORDER))],
            marker_line_width=0, text=counts, textposition="outside",
            textfont=dict(size=11, color="#aaa"),
        ))
        funnel_layout = {**PL, "showlegend": False, "height": 280}
        funnel_layout["xaxis"] = dict(showgrid=False, visible=False)
        funnel_layout["yaxis"] = dict(showgrid=False)
        fig.update_layout(**funnel_layout)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        if not quality_df.empty:
            st.markdown("<div class='sec-hdr'>Quality by playbook</div>", unsafe_allow_html=True)
            merged_df = df.merge(quality_df, on="pr_url", how="inner")
            if not merged_df.empty:
                bd = (
                    merged_df.groupby("playbook")[
                        ["correctness", "scope_discipline", "no_regression", "acceptance_criteria", "pr_hygiene", "total_score"]
                    ].mean().round(1).reset_index()
                )
                bd.columns = ["Playbook", "Correctness", "Scope", "No Regression", "Acceptance", "Hygiene", "Total"]
                st.dataframe(bd, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — Cost
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    _, cc2 = st.columns([5, 1])
    with cc2:
        if st.button("Sync Costs", key="sync_costs_tab3", use_container_width=True):
            with st.spinner("Syncing…"):
                r = subprocess.run(
                    ["python", "scripts/sync_costs.py"],
                    capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                )
            st.cache_data.clear()
            st.code(r.stdout or r.stderr)

    acu_spent = budget.get("acu_spent", 0)
    acu_limit = budget.get("acu_budget", settings.daily_acu_budget)
    pct       = min(acu_spent / acu_limit, 1.0) if acu_limit else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("ACU spent today", f"{acu_spent:.1f}")
    c2.metric("Daily limit",     f"{acu_limit:.0f}")
    c3.metric("Remaining",       f"{max(0, acu_limit - acu_spent):.1f}")

    st.markdown("<div class='sec-hdr'>Budget burn-down</div>", unsafe_allow_html=True)
    bar_color = "#111" if pct < 0.7 else "#c9914a" if pct < 0.9 else "#b04040"
    with st.container(border=True):
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;margin-bottom:0.4rem;'>"
            f"<span style='font-size:0.75rem;color:#aaa;'>{acu_spent:.1f} used</span>"
            f"<span style='font-size:0.75rem;color:#aaa;'>{acu_limit:.0f} limit</span></div>"
            f"<div class='prog-wrap'><div class='prog-bar' style='background:{bar_color};width:{pct*100:.1f}%;'></div></div>"
            f"<div style='font-size:0.7rem;color:#aaa;margin-top:0.35rem;'>{pct*100:.0f}% of daily budget used</div>",
            unsafe_allow_html=True,
        )

    if not df.empty:
        total_acu   = df["acu_spent"].sum()
        cost_per_pr = _cost_per_pr(df)

        st.markdown("<div class='sec-hdr'>All-time</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.metric("Total ACU spent", f"{total_acu:.1f}" if total_acu > 0 else "—")
        c2.metric("Avg cost / PR",   f"${cost_per_pr:.2f}" if cost_per_pr is not None else "—")

        done = df[df["status"].isin(["ci_passed", "merged", "completed", "pr_opened"]) & (df["acu_spent"] > 0)]
        if not done.empty:
            st.markdown("<div class='sec-hdr'>Cost by playbook</div>", unsafe_allow_html=True)
            by_p = done.groupby("playbook").agg(sessions=("id", "count"), avg_acu=("acu_spent", "mean")).reset_index()
            by_p["avg_cost"] = (by_p["avg_acu"] * settings.acu_usd_rate).round(2)
            by_p.columns = ["Playbook", "Sessions", "Avg ACU", "Avg $/PR"]
            st.dataframe(by_p, use_container_width=True, hide_index=True)
    else:
        with st.container(border=True):
            st.markdown(
                "<div class='empty-wrap'>"
                "<div class='empty-head'>No cost data yet</div>"
                "<div class='empty-sub'>Appears once Devin sessions start running.</div>"
                "</div>",
                unsafe_allow_html=True,
            )

# ══════════════════════════════════════════════════════════════════════════════
# Tab 4 — Sessions
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    if df.empty:
        with st.container(border=True):
            st.markdown(
                "<div class='empty-wrap'>"
                "<div class='empty-head'>No sessions yet</div>"
                "<div class='empty-sub'>Sessions appear once the webhook triggers a Devin dispatch.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        display = df[["id", "issue_number", "playbook", "status", "acu_spent", "retry_count", "started_at"]].copy()
        display.columns = ["ID", "Issue #", "Playbook", "Status", "ACU", "Retries", "Started"]
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("<div class='sec-hdr'>Session detail</div>", unsafe_allow_html=True)
        selected_id = st.selectbox("Session", df["id"].tolist(), label_visibility="collapsed")

        if selected_id:
            row = df[df["id"] == selected_id].iloc[0]

            c1, c2, c3 = st.columns(3)
            c1.metric("Status",    row["status"])
            c2.metric("ACU spent", f"{row['acu_spent']:.2f}" if row["acu_spent"] > 0 else "—")
            c3.metric("Retries",   int(row["retry_count"]))

            # Manual ACU entry — Devin API doesn't return acu_consumed for this plan
            with st.expander("Set ACU cost manually"):
                ac1, ac2 = st.columns([3, 1])
                with ac1:
                    manual_acu = st.number_input(
                        "ACU spent", min_value=0.0, max_value=100.0,
                        value=float(row["acu_spent"]), step=0.5,
                        key=f"acu_{selected_id}", label_visibility="collapsed",
                    )
                with ac2:
                    if st.button("Save", key=f"save_acu_{selected_id}", type="primary", use_container_width=True):
                        set_session_acu(selected_id, manual_acu)
                        st.cache_data.clear()
                        st.success(f"Set to {manual_acu} ACU (≈ ${manual_acu * settings.acu_usd_rate:.2f})")

            links = []
            if row.get("pr_url"):
                links.append(f"[View PR]({row['pr_url']})")
            if row.get("devin_session_url"):
                links.append(f"[View Devin session]({row['devin_session_url']})")
            if links:
                st.caption("  ·  ".join(links))

            events = get_events_for_session(selected_id)
            if events:
                st.markdown("<div class='sec-hdr'>Event timeline</div>", unsafe_allow_html=True)
                edf = pd.DataFrame([dict(e) for e in events])
                st.dataframe(edf[["created_at", "event_type", "payload"]], use_container_width=True, hide_index=True)
            else:
                st.caption("No events recorded yet.")

            if row.get("status") in ("failed", "budget_killed") and row.get("failure_reason"):
                st.warning(f"Failure: {row['failure_reason']}", icon="⚠️")

# ══════════════════════════════════════════════════════════════════════════════
# Tab 5 — Controls
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
    # ── Budget ────────────────────────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Daily ACU Budget</div>", unsafe_allow_html=True)
    with st.container(border=True):
        current_limit = budget.get("acu_budget", settings.daily_acu_budget)
        bc1, bc2 = st.columns([3, 1])
        with bc1:
            new_budget = st.number_input(
                "ACU limit per day", min_value=1.0, max_value=500.0,
                value=float(current_limit), step=5.0, label_visibility="collapsed",
            )
        with bc2:
            if st.button("Save", key="save_budget", type="primary", use_container_width=True):
                set_budget(new_budget)
                st.cache_data.clear()
                st.success(f"Budget updated to {new_budget} ACU")

    # ── Sync ──────────────────────────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Sync</div>", unsafe_allow_html=True)
    sync_col_a, sync_col_b = st.columns(2)

    with sync_col_a:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Sync PRs from GitHub</p><p class='card-d'>Devin opens PRs while sessions are still running. This reads GitHub and backfills PR URLs into the database.</p>", unsafe_allow_html=True)
            if st.button("Sync PRs", key="sync_prs", type="primary", use_container_width=True):
                with st.spinner("Syncing…"):
                    r = subprocess.run(
                        ["python", "scripts/sync_prs.py"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)
                st.cache_data.clear()

    with sync_col_b:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Sync Costs</p><p class='card-d'>Pull ACU costs from Devin v3 API (or title-match from COST_TABLE) and update session spend in the database.</p>", unsafe_allow_html=True)
            if st.button("Sync Costs", key="sync_costs_controls", type="primary", use_container_width=True):
                with st.spinner("Syncing…"):
                    r = subprocess.run(
                        ["python", "scripts/sync_costs.py"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)
                st.cache_data.clear()

    # ── Maintenance ───────────────────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Maintenance</div>", unsafe_allow_html=True)
    col_d, col_e, col_f = st.columns(3)

    with col_d:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Close Issues</p><p class='card-d'>Close all open auto-generated issues on the fork.</p>", unsafe_allow_html=True)
            if st.button("Close all", key="close_issues", use_container_width=True):
                with st.spinner("Closing…"):
                    r = subprocess.run(
                        ["python", "scripts/close_issues.py"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)

    with col_e:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Clear Database</p><p class='card-d'>Wipe all sessions, events, and quality scores from SQLite.</p>", unsafe_allow_html=True)
            if st.button("Clear DB", key="clear_db", use_container_width=True):
                with st.spinner("Clearing…"):
                    r = subprocess.run(
                        ["python", "scripts/clear_db.py"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)
                st.cache_data.clear()

    with col_f:
        with st.container(border=True):
            st.markdown("<p class='card-t'>Seed Demo</p><p class='card-d'>Load mock session data so the dashboard shows sample metrics.</p>", unsafe_allow_html=True)
            if st.button("Seed data", key="seed", use_container_width=True):
                with st.spinner("Seeding…"):
                    r = subprocess.run(
                        ["python", "scripts/seed_demo.py"],
                        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                    )
                st.code(r.stdout or r.stderr)
                st.cache_data.clear()

    # ── Danger zone ───────────────────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Danger zone</div>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<p class='card-t'>Reset + Rescan</p><p class='card-d'>Closes all issues, clears the database, then runs a fresh CVE scan. This cannot be undone.</p>", unsafe_allow_html=True)
        if st.button("Reset + Rescan", key="reset", type="primary"):
            with st.spinner("Resetting…"):
                subprocess.run(["python", "scripts/close_issues.py"], cwd=Path(__file__).parent.parent)
                subprocess.run(["python", "scripts/clear_db.py"], cwd=Path(__file__).parent.parent)
                r = subprocess.run(
                    ["python", "scripts/scan_cves.py", "--repo-path", REPO_PATH, "--max-issues", str(MAX_ISSUES)],
                    capture_output=True, text=True, cwd=Path(__file__).parent.parent,
                )
            st.code(r.stdout or r.stderr)
            st.cache_data.clear()
