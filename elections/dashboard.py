"""dashboard.py – Italian Electoral Data Interactive Dashboard

Run with:
    streamlit run dashboard.py
"""

import json
import re
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Italian Elections Dashboard",
    page_icon="🗳",
    layout="wide",
)

GOLD = Path("data_parquet/gold")
GEOJSON_URL = (
    "https://raw.githubusercontent.com/openpolis/geojson-italy"
    "/master/geojson/limits_IT_regions.geojson"
)
GEOJSON_PATH = Path("italy_regions.geojson")

# ── region name normalisation ─────────────────────────────────────────────────
# Maps source-data UPPERCASE variants → GeoJSON reg_name (Title Case / bilingual).
_REGION_MAP: dict[str, str] = {
    "ABRUZZI":                    "Abruzzo",
    "ABRUZZO":                    "Abruzzo",
    "BASILICATA":                 "Basilicata",
    "CALABRIA":                   "Calabria",
    "CAMPANIA":                   "Campania",
    "EMILIA ROMAGNA":             "Emilia-Romagna",
    "EMILIA-ROMAGNA":             "Emilia-Romagna",
    "FRIULI - VENEZIA GIULIA":    "Friuli-Venezia Giulia",
    "FRIULI-VENEZIA GIULIA":      "Friuli-Venezia Giulia",
    "LAZIO":                      "Lazio",
    "LIGURIA":                    "Liguria",
    "LOMBARDIA":                  "Lombardia",
    "MARCHE":                     "Marche",
    "MOLISE":                     "Molise",
    "PIEMONTE":                   "Piemonte",
    "PUGLIA":                     "Puglia",
    "SARDEGNA":                   "Sardegna",
    "SICILIA":                    "Sicilia",
    "TOSCANA":                    "Toscana",
    "TRENTINO - ALTO ADIGE":      "Trentino-Alto Adige/Südtirol",
    "TRENTINO-ALTO ADIGE":        "Trentino-Alto Adige/Südtirol",
    "TRENTINO-ALTO ADIGE/SUDTIROL":    "Trentino-Alto Adige/Südtirol",
    "TRENTINO-ALTO ADIGE/S_DTIROL":    "Trentino-Alto Adige/Südtirol",
    "UMBRIA":                     "Umbria",
    "VALLE D'AOSTA":              "Valle d'Aosta/Vallée d'Aoste",
    "VENETO":                     "Veneto",
}

# Constituency names encode region as prefix + number, e.g. "CAMPANIA 1 - 02".
# Strip the trailing number to recover the base region.
_CONSTITUENCY_PREFIX_RE = re.compile(r"^(.+?)\s+\d+\s*-\s*", re.IGNORECASE)
_CONSTITUENCY_SIMPLE_RE = re.compile(r"^(.+?)\s*-\s*\d")


def _norm_region(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    u = raw.strip().upper()
    return _REGION_MAP.get(u)


def _region_from_constituency(name: str | None) -> str | None:
    if not name or not isinstance(name, str):
        return None
    # "CAMPANIA 1 - 02" → "CAMPANIA 1" → strip trailing " 1" → "CAMPANIA"
    m = _CONSTITUENCY_PREFIX_RE.match(name)
    if not m:
        m = _CONSTITUENCY_SIMPLE_RE.match(name)
    if not m:
        return None
    prefix = m.group(1).strip().upper()
    # Remove trailing number (e.g. "CAMPANIA 1" → "CAMPANIA")
    prefix_clean = re.sub(r"\s+\d+$", "", prefix).strip()
    return _REGION_MAP.get(prefix_clean)


# ── data loading (cached for the session) ─────────────────────────────────────
@st.cache_data(show_spinner="Loading election data…")
def _load_all() -> dict[str, pd.DataFrame]:
    return {
        "elections": pd.read_parquet(GOLD / "dim_election"),
        "geo":       pd.read_parquet(GOLD / "dim_geography"),
        "turnout":   pd.read_parquet(GOLD / "fact_turnout"),
        "lv":        pd.read_parquet(GOLD / "fact_list_votes"),
        "dim_list":  pd.read_parquet(GOLD / "dim_list"),
        "cv":        pd.read_parquet(GOLD / "fact_candidate_votes"),
        "dim_cand":  pd.read_parquet(GOLD / "dim_candidate"),
    }


@st.cache_resource(show_spinner="Loading Italy map…")
def _load_geojson() -> dict:
    if not GEOJSON_PATH.exists():
        with urllib.request.urlopen(GEOJSON_URL) as r:
            GEOJSON_PATH.write_bytes(r.read())
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _build_province_region_map(geo: pd.DataFrame) -> dict[str, str]:
    """Derive province → normalised-region-name from rows where both are set."""
    pairs = (
        geo[geo["region"].notna() & geo["province"].notna()]
        [["province", "region"]]
        .drop_duplicates()
    )
    result: dict[str, str] = {}
    for _, row in pairs.iterrows():
        norm = _norm_region(row["region"])
        if norm:
            result[str(row["province"]).upper().strip()] = norm
    return result


# ── region resolution ─────────────────────────────────────────────────────────
def _resolve_region(df: pd.DataFrame, prov_map: dict[str, str]) -> pd.Series:
    """
    Return a Series of GeoJSON-compatible region names for every row in df.
    Resolution order:
      1. region column (if present and in map)
      2. province column → prov_map lookup
      3. constituency column → prefix extraction
      4. electoral_district column → direct lookup then prefix extraction
         (Chamber elections store the region name here, e.g. "EMILIA-ROMAGNA",
         "SICILIA 1", "PIEMONTE 1" — municipality and region columns are null)
    """
    out = df["region"].apply(_norm_region)

    # Fill via province
    needs_fill = out.isna() & df["province"].notna()
    if needs_fill.any():
        out[needs_fill] = df.loc[needs_fill, "province"].str.upper().str.strip().map(prov_map)

    # Fill via constituency prefix
    if "constituency" in df.columns:
        needs_fill = out.isna() & df["constituency"].notna()
        if needs_fill.any():
            out[needs_fill] = df.loc[needs_fill, "constituency"].apply(_region_from_constituency)

    # Fill via electoral_district (Chamber elections: "LIGURIA", "SICILIA 1", etc.)
    if "electoral_district" in df.columns:
        needs_fill = out.isna() & df["electoral_district"].notna()
        if needs_fill.any():
            out[needs_fill] = df.loc[needs_fill, "electoral_district"].apply(
                lambda x: _norm_region(x) or _region_from_constituency(x)
            )

    return out


# ── scope deduplication ───────────────────────────────────────────────────────
def _pick_scope(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """
    Elections like the 2018 Chamber store the same votes at multiple geo_scopes
    (e.g. DISTRICT for circoscrizioni and CONSTITUENCY for uninominal seats).
    Summing across all scopes double-counts. This function keeps only the scope
    whose aggregate total is smallest while still representing at least 25% of
    the maximum-scope total — that's the most granular non-duplicated level.
    """
    if df.empty or "geo_scope" not in df.columns:
        return df
    scopes = [s for s in df["geo_scope"].dropna().unique() if s != "COUNTRY"]
    if len(scopes) <= 1:
        return df
    scope_sums = df[df["geo_scope"].isin(scopes)].groupby("geo_scope")[value_col].sum()
    max_total = scope_sums.max()
    valid = scope_sums[scope_sums >= 0.25 * max_total]
    if valid.empty:
        return df
    best = valid.idxmin()
    return df[df["geo_scope"] == best]


# ── formatting helpers ────────────────────────────────────────────────────────
def _fmt_num(n) -> str:
    return "N/A" if pd.isna(n) else f"{int(n):,}"


def _fmt_pct(v) -> str:
    return "N/A" if pd.isna(v) else f"{v:.1f}%"


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    d = _load_all()
    geojson = _load_geojson()

    elections = d["elections"].copy()
    elections["election_date"] = pd.to_datetime(elections["election_date"]).dt.date
    geo = d["geo"]
    prov_map = _build_province_region_map(geo)

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Filters")

        etype = st.selectbox("Election type", ["CHAMBER", "MUNICIPAL"])

        dates = sorted(
            elections.loc[elections["election_type"] == etype, "election_date"].unique(),
            reverse=True,
        )
        sel_date = st.selectbox("Election date", dates, format_func=str)

        row = elections[
            (elections["election_type"] == etype) & (elections["election_date"] == sel_date)
        ]
        sel_eid = row["election_id"].iloc[0]

        metric = st.selectbox("Map metric", ["Turnout %", "Top-party vote share %"])

        t_election = d["turnout"][d["turnout"]["election_id"] == sel_eid]
        rounds = sorted(t_election["round"].dropna().unique())
        sel_round = (
            st.selectbox("Round", rounds, format_func=lambda r: f"Round {int(r)}")
            if len(rounds) > 1
            else (rounds[0] if rounds else 1.0)
        )

    # ── page header ───────────────────────────────────────────────────────────
    label = "Chamber of Deputies" if etype == "CHAMBER" else "Municipal"
    st.title("🗳 Italian Electoral Dashboard")
    st.subheader(f"{label} election — {sel_date}")

    # ── prepare turnout data ──────────────────────────────────────────────────
    # Some elections store no round value (all NaN) — skip round filter in that case.
    t_filtered = (
        t_election[t_election["round"] == sel_round]
        if rounds else t_election
    )
    t_sel = t_filtered.merge(geo, on="geo_id", how="left")
    t_dom = _pick_scope(t_sel[t_sel["geo_scope"] != "COUNTRY"].copy(), "registered_voters")
    t_dom["reg_name"] = _resolve_region(t_dom, prov_map)

    reg_turn = pd.DataFrame(columns=["reg_name", "registered", "turnout", "turnout_pct"])
    if not t_dom.empty and t_dom["reg_name"].notna().any():
        reg_turn = (
            t_dom[t_dom["reg_name"].notna()]
            .groupby("reg_name")
            .agg(registered=("registered_voters", "sum"), turnout=("turnout_total", "sum"))
            .reset_index()
        )
        reg_turn["turnout_pct"] = (
            reg_turn["turnout"] / reg_turn["registered"] * 100
        ).round(2)

    # ── prepare list votes data ───────────────────────────────────────────────
    lv_sel = (
        d["lv"][d["lv"]["election_id"] == sel_eid]
        .merge(geo, on="geo_id", how="left")
    )
    lv_dom = _pick_scope(lv_sel[lv_sel["geo_scope"] != "COUNTRY"].copy(), "list_votes")
    lv_named = lv_dom.merge(d["dim_list"][["list_id", "list_name"]], on="list_id", how="left")
    lv_named["reg_name"] = _resolve_region(lv_named, prov_map)

    lv_winners = pd.DataFrame()
    if not lv_named.empty and lv_named["reg_name"].notna().any():
        lv_reg = (
            lv_named[lv_named["reg_name"].notna()]
            .groupby(["reg_name", "list_name"])["list_votes"]
            .sum()
            .reset_index()
        )
        if not lv_reg.empty:
            reg_total = lv_reg.groupby("reg_name")["list_votes"].sum().rename("total_votes")
            lv_winners = (
                lv_reg.sort_values("list_votes", ascending=False)
                .groupby("reg_name", as_index=False)
                .first()
                .merge(reg_total, on="reg_name")
            )
            lv_winners["top_party_share"] = (
                lv_winners["list_votes"] / lv_winners["total_votes"] * 100
            ).round(2)
            lv_winners = lv_winners.rename(
                columns={"list_name": "top_party", "list_votes": "top_party_votes"}
            )

    # ── summary stats ─────────────────────────────────────────────────────────
    # For elections where multiple geo_scopes exist (e.g. 2018 Chamber has both
    # CONSTITUENCY and DISTRICT rows covering the same voters), pick the scope
    # whose registered_voters total is smallest while still ≥ 30M — that's the
    # non-duplicated national total.
    def _national_totals(df):
        scope_sums = (
            df.groupby("geo_scope")["registered_voters"].sum()
            .pipe(lambda s: s[s >= 30_000_000])
            .sort_values()
        )
        if scope_sums.empty:
            best_scope = df  # fall back to all rows
        else:
            best_scope = df[df["geo_scope"] == scope_sums.index[0]]
        return best_scope

    col_map, col_stats = st.columns([3, 1])

    with col_stats:
        st.markdown("### Summary")
        if not t_dom.empty:
            t_nat      = _national_totals(t_dom)
            total_reg  = t_nat["registered_voters"].sum()
            total_turn = t_nat["turnout_total"].sum()
            total_blank = t_nat["blank_ballots"].sum()
            nat_pct    = (total_turn / total_reg * 100) if total_reg else 0.0
            st.metric("Registered voters", _fmt_num(total_reg))
            st.metric("National turnout",  _fmt_pct(nat_pct))
            if total_blank > 0:
                st.metric("Blank ballots", _fmt_num(total_blank))
        else:
            st.info("Turnout data not available for this election.", icon="ℹ")

        if etype == "MUNICIPAL":
            st.info(
                "Municipal elections cover only cities that voted on this date — "
                "some regions may appear grey.",
                icon="ℹ",
            )

    # ── choropleth map ────────────────────────────────────────────────────────
    with col_map:
        if metric == "Turnout %":
            map_df    = reg_turn
            color_col = "turnout_pct"
            hover     = {"registered": ":,", "turnout": ":,", "turnout_pct": ":.1f"}
            clabel    = "Turnout %"
            cscale    = "Blues"
        else:
            map_df    = lv_winners
            color_col = "top_party_share"
            hover     = {"top_party": True, "top_party_votes": ":,", "top_party_share": ":.1f"}
            clabel    = "Top-party share %"
            cscale    = "Reds"

        if map_df.empty or color_col not in map_df.columns:
            st.warning(
                f"No regional data available for '{metric}' with this election. "
                "Try switching to another metric or selecting a different election date."
            )
        else:
            fig = px.choropleth_map(
                map_df,
                geojson=geojson,
                locations="reg_name",
                featureidkey="properties.reg_name",
                color=color_col,
                hover_name="reg_name",
                hover_data=hover,
                color_continuous_scale=cscale,
                map_style="carto-positron",
                zoom=4.5,
                center={"lat": 42.0, "lon": 12.5},
                opacity=0.75,
                labels={color_col: clabel},
                height=520,
            )
            fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
            st.plotly_chart(fig, width="stretch")

    st.divider()

    # ── tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["📊 Top parties", "📋 Region breakdown", "👥 Gender"])

    # ── tab 1: top parties bar chart ──────────────────────────────────────────
    with tab1:
        party_totals = (
            lv_named.groupby("list_name")["list_votes"]
            .sum()
            .nlargest(15)
            .reset_index()
            .rename(columns={"list_votes": "votes"})
        )
        if party_totals.empty:
            st.info("No list-vote data for this election.")
        else:
            fig2 = px.bar(
                party_totals,
                x="list_name",
                y="votes",
                labels={"list_name": "Party / List", "votes": "Total votes"},
                title=f"Top 15 parties — {label} {sel_date}",
                color="votes",
                color_continuous_scale="Blues",
            )
            fig2.update_layout(xaxis_tickangle=-35, coloraxis_showscale=False)
            st.plotly_chart(fig2, width="stretch")

    # ── tab 2: region breakdown table ────────────────────────────────────────
    with tab2:
        if reg_turn.empty and lv_winners.empty:
            st.info("No regional data available for this election.")
        else:
            base = reg_turn if not reg_turn.empty else pd.DataFrame({"reg_name": []})
            reg_table = base.merge(
                lv_winners[["reg_name", "top_party", "top_party_votes", "top_party_share"]]
                if not lv_winners.empty
                else pd.DataFrame(columns=["reg_name", "top_party", "top_party_votes", "top_party_share"]),
                on="reg_name",
                how="outer",
            ).rename(columns={
                "reg_name":        "Region",
                "registered":      "Registered voters",
                "turnout_pct":     "Turnout %",
                "top_party":       "Top party",
                "top_party_votes": "Top party votes",
                "top_party_share": "Top party share %",
            })
            if "Turnout %" in reg_table.columns:
                reg_table = reg_table.sort_values("Turnout %", ascending=False, na_position="last")
            st.dataframe(reg_table, width="stretch", hide_index=True)

    # ── tab 3: gender among elected ───────────────────────────────────────────
    with tab3:
        cv_sel = d["cv"][d["cv"]["election_id"] == sel_eid]
        elected = cv_sel[cv_sel["elected"]].merge(
            d["dim_cand"][["candidate_id", "sex"]], on="candidate_id", how="left"
        )
        gender_counts = elected["sex"].value_counts().reset_index()
        gender_counts.columns = ["sex", "count"]

        if gender_counts.empty:
            st.info("No elected-candidate data available for this election.")
        else:
            total_elected = int(gender_counts["count"].sum())
            female_count  = int(gender_counts.loc[gender_counts["sex"] == "F", "count"].sum())
            male_count    = int(gender_counts.loc[gender_counts["sex"] == "M", "count"].sum())
            female_pct    = female_count / total_elected * 100 if total_elected else 0.0

            g1, g2, g3 = st.columns(3)
            g1.metric("Total elected",  _fmt_num(total_elected))
            g2.metric("Female elected", f"{_fmt_num(female_count)}  ({_fmt_pct(female_pct)})")
            g3.metric("Male elected",   _fmt_num(male_count))

            fig3 = px.pie(
                gender_counts,
                names="sex",
                values="count",
                title="Elected candidates by gender",
                color="sex",
                color_discrete_map={"F": "#e377c2", "M": "#1f77b4"},
                hole=0.4,
            )
            st.plotly_chart(fig3, width="stretch")


main()
