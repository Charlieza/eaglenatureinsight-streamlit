from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium

from utils.ee_helpers import (
    initialize_ee_from_secrets,
    geojson_to_ee_geometry,
    point_buffer_to_ee_geometry,
    compute_metrics,
    landsat_annual_ndvi_collection,
    annual_rain_collection,
    annual_lst_collection,
    forest_loss_by_year_collection,
    water_history_collection,
    satellite_with_polygon,
    ndvi_with_polygon,
    landcover_with_polygon,
    forest_loss_with_polygon,
    image_thumb_url,
)
from utils.scoring import build_risk_and_recommendations


# =====================================================
# 1. APP CONFIG
# =====================================================
st.set_page_config(
    page_title="EagleNatureInsight™",
    layout="wide"
)

LOGO_PATH = Path("assets/logo.png")

APP_TITLE = "EagleNatureInsight™"
APP_SUBTITLE = "Nature Intelligence Dashboard for SMEs"
APP_TAGLINE = "Locate • Evaluate • Assess • Prepare"

CURRENT_YEAR = pd.Timestamp.now().year
LAST_FULL_YEAR = CURRENT_YEAR - 1

PANUKA_COORDS = {"lon": 28.3228, "lat": -15.3875, "buffer_m": 1500, "zoom": 12}
BLTURNER_COORDS = {"lon": 31.0218, "lat": -29.9167, "buffer_m": 1000, "zoom": 13}

PRESETS = [
    "Select Business / Area",
    "Panuka AgriBiz Hub",
    "BL Turner Group",
]

CATEGORIES = [
    "Agriculture / Agribusiness",
    "Food processing / Supply chain",
    "Manufacturing / Industrial",
    "Water / Circular economy",
    "Energy / Infrastructure",
    "Property / Built environment",
    "General SME",
]

PRESET_TO_CATEGORY = {
    "Panuka AgriBiz Hub": "Agriculture / Agribusiness",
    "BL Turner Group": "Water / Circular economy",
}

PRESET_TO_LOCATION = {
    "Panuka AgriBiz Hub": PANUKA_COORDS,
    "BL Turner Group": BLTURNER_COORDS,
}


# =====================================================
# 2. HELPERS
# =====================================================
def init_state() -> None:
    defaults = {
        "preset_selector": "Select Business / Area",
        "category_selector": "General SME",
        "draw_mode": "Draw polygon",
        "lat_input": "",
        "lon_input": "",
        "buffer_input": 1000,
        "hist_start": 2001,
        "hist_end": LAST_FULL_YEAR,
        "map_center": [-25.0, 24.0],
        "map_zoom": 5,
        "last_geometry_payload": None,
        "assessment_complete": False,
        "assessment_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def preset_changed() -> None:
    preset = st.session_state.preset_selector
    if preset in PRESET_TO_CATEGORY:
        st.session_state.category_selector = PRESET_TO_CATEGORY[preset]

    if preset in PRESET_TO_LOCATION:
        loc = PRESET_TO_LOCATION[preset]
        st.session_state.lat_input = str(loc["lat"])
        st.session_state.lon_input = str(loc["lon"])
        st.session_state.buffer_input = int(loc["buffer_m"])
        st.session_state.map_center = [loc["lat"], loc["lon"]]
        st.session_state.map_zoom = int(loc["zoom"])


def focus_preset(preset_name: str) -> None:
    st.session_state.preset_selector = preset_name
    preset_changed()


def build_map(center: list[float], zoom: int) -> folium.Map:
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        control_scale=True,
        tiles="OpenStreetMap"
    )

    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "rectangle": True,
            "polygon": True,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)

    return m


def extract_drawn_geometry(map_data: dict | None) -> dict | None:
    if not map_data:
        return None
    drawings = map_data.get("all_drawings") or []
    if not drawings:
        return None
    return drawings[-1]


def get_geometry_payload() -> tuple[str, dict | None]:
    mode = st.session_state.draw_mode

    if mode == "Draw polygon":
        geojson_obj = st.session_state.get("drawn_geojson")
        if geojson_obj:
            return "Polygon captured from map drawing.", geojson_obj
        return "No polygon drawn yet.", None

    try:
        lat_val = float(st.session_state.lat_input)
        lon_val = float(st.session_state.lon_input)
        buffer_m = int(st.session_state.buffer_input)

        return (
            f"Point entered at ({lat_val:.5f}, {lon_val:.5f}) with {buffer_m} m buffer.",
            {
                "type": "PointBuffer",
                "lat": lat_val,
                "lon": lon_val,
                "buffer_m": buffer_m,
            },
        )
    except (TypeError, ValueError):
        return "Please enter valid latitude and longitude.", None


def payload_to_ee_geometry(payload: dict):
    if payload.get("type") == "PointBuffer":
        return point_buffer_to_ee_geometry(
            lat=float(payload["lat"]),
            lon=float(payload["lon"]),
            buffer_m=float(payload["buffer_m"]),
        )
    return geojson_to_ee_geometry(payload)


def ee_fc_to_dataframe(fc) -> pd.DataFrame:
    data = fc.getInfo()
    features = data.get("features", [])
    rows = []
    for f in features:
        props = f.get("properties", {})
        rows.append(props)
    df = pd.DataFrame(rows)
    if not df.empty and "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df = df.sort_values("year")
    if not df.empty and "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def landcover_table_from_metrics(metrics: dict) -> pd.DataFrame:
    rows = [
        {"Class": "Tree cover", "Percent": metrics.get("tree_pct")},
        {"Class": "Cropland", "Percent": metrics.get("cropland_pct")},
        {"Class": "Built-up", "Percent": metrics.get("built_pct")},
    ]
    df = pd.DataFrame(rows)
    df["Percent"] = pd.to_numeric(df["Percent"], errors="coerce")
    return df


def safe_fmt(value, digits=1, suffix=""):
    try:
        if value is None:
            return "—"
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return "—"


def render_leap_boxes() -> None:
    st.markdown("### LEAP Process")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.info("**Locate**\n\nDefine the site and understand the local nature context.")
    with c2:
        st.info("**Evaluate**\n\nReview current conditions and historical environmental change.")
    with c3:
        st.info("**Assess**\n\nInterpret key risks and opportunities for the business.")
    with c4:
        st.info("**Prepare**\n\nTranslate findings into practical next actions.")


def render_image_card(title: str, explanation: str, url: str, legend_items: list[tuple[str, str]]) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(explanation)
        st.image(url, use_container_width=True)
        if legend_items:
            st.markdown("**Legend**")
            for color, label in legend_items:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>"
                    f"<div style='width:14px;height:14px;background:{color};border:1px solid #ccc;'></div>"
                    f"<div style='font-size:0.92rem;'>{label}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.markdown(f"[Open larger image]({url})")


# =====================================================
# 3. INIT + EE AUTH
# =====================================================
init_state()
initialize_ee_from_secrets(st)


# =====================================================
# 4. HEADER
# =====================================================
header_left, header_right = st.columns([2, 6])

with header_left:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)

with header_right:
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.markdown(f"**{APP_TAGLINE}**")

st.markdown(
    "Define the site, review nature-related signals, and receive category-specific recommendations."
)

st.markdown("---")
render_leap_boxes()
st.markdown("---")


# =====================================================
# 5. CONTROLS
# =====================================================
c1, c2 = st.columns(2)

with c1:
    st.selectbox(
        "Select business or assessment area",
        PRESETS,
        key="preset_selector",
        on_change=preset_changed,
    )

with c2:
    st.selectbox(
        "Business category",
        CATEGORIES,
        key="category_selector",
    )

f1, f2 = st.columns(2)
with f1:
    if st.button("Focus Panuka", use_container_width=True):
        focus_preset("Panuka AgriBiz Hub")
        st.rerun()

with f2:
    if st.button("Focus BL Turner", use_container_width=True):
        focus_preset("BL Turner Group")
        st.rerun()

m1, m2, m3 = st.columns([2, 1, 1])

with m1:
    st.radio(
        "Site definition method",
        ["Draw polygon", "Enter coordinates"],
        key="draw_mode",
        horizontal=True,
    )

with m2:
    st.number_input(
        "Historical start year",
        min_value=1981,
        max_value=LAST_FULL_YEAR,
        key="hist_start",
        step=1,
    )

with m3:
    st.number_input(
        "Historical end year",
        min_value=1981,
        max_value=LAST_FULL_YEAR,
        key="hist_end",
        step=1,
    )

if st.session_state.draw_mode == "Enter coordinates":
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        st.text_input("Latitude", key="lat_input", placeholder="-29.9167")
    with cc2:
        st.text_input("Longitude", key="lon_input", placeholder="31.0218")
    with cc3:
        st.number_input(
            "Buffer radius (metres)",
            min_value=100,
            max_value=50000,
            step=100,
            key="buffer_input",
        )


# =====================================================
# 6. MAP
# =====================================================
st.markdown("### Site Selection")

folium_map = build_map(
    center=st.session_state.map_center,
    zoom=st.session_state.map_zoom,
)

map_data = st_folium(
    folium_map,
    width=None,
    height=520,
    returned_objects=["all_drawings"],
    key="eaglenatureinsight_map",
)

st.session_state.drawn_geojson = extract_drawn_geometry(map_data)

selection_text, geometry_payload = get_geometry_payload()
st.session_state.last_geometry_payload = geometry_payload

st.markdown("### Current Selection")
st.write(selection_text)

with st.expander("Show geometry payload"):
    if geometry_payload is None:
        st.write("No valid geometry available yet.")
    else:
        st.json(geometry_payload)


# =====================================================
# 7. RUN ASSESSMENT
# =====================================================
run_clicked = st.button("Run Assessment", use_container_width=True)

if run_clicked:
    if geometry_payload is None:
        st.warning("Please draw a polygon or enter valid coordinates first.")
        st.session_state.assessment_complete = False
        st.session_state.assessment_result = None
    else:
        if st.session_state.hist_start > st.session_state.hist_end:
            st.warning("Historical start year must be less than or equal to end year.")
            st.stop()

        with st.spinner("Running EagleNatureInsight assessment..."):
            geom = payload_to_ee_geometry(geometry_payload)

            metrics = compute_metrics(
                geom=geom,
                hist_start=int(st.session_state.hist_start),
                hist_end=int(st.session_state.hist_end),
                last_full_year=LAST_FULL_YEAR,
            )

            risk = build_risk_and_recommendations(
                preset=st.session_state.preset_selector,
                category=st.session_state.category_selector,
                metrics=metrics,
            )

            ndvi_hist_fc = landsat_annual_ndvi_collection(
                geom,
                max(int(st.session_state.hist_start), 1984),
                int(st.session_state.hist_end),
            )
            rain_hist_fc = annual_rain_collection(
                geom,
                max(int(st.session_state.hist_start), 1981),
                int(st.session_state.hist_end),
            )
            lst_hist_fc = annual_lst_collection(
                geom,
                max(int(st.session_state.hist_start), 2001),
                int(st.session_state.hist_end),
            )
            forest_hist_fc = forest_loss_by_year_collection(
                geom,
                int(st.session_state.hist_start),
                int(st.session_state.hist_end),
            )
            water_hist_fc = water_history_collection(
                geom,
                max(int(st.session_state.hist_start), 1984),
                int(st.session_state.hist_end),
            )

            ndvi_hist_df = ee_fc_to_dataframe(ndvi_hist_fc)
            rain_hist_df = ee_fc_to_dataframe(rain_hist_fc)
            lst_hist_df = ee_fc_to_dataframe(lst_hist_fc)
            forest_hist_df = ee_fc_to_dataframe(forest_hist_fc)
            water_hist_df = ee_fc_to_dataframe(water_hist_fc)

            satellite_img = satellite_with_polygon(geom, LAST_FULL_YEAR)
            ndvi_img = ndvi_with_polygon(geom, LAST_FULL_YEAR)
            landcover_img = landcover_with_polygon(geom)
            forest_loss_img = forest_loss_with_polygon(geom)

            satellite_url = image_thumb_url(satellite_img, geom, dimensions=1400)
            ndvi_url = image_thumb_url(ndvi_img, geom, dimensions=1400)
            landcover_url = image_thumb_url(landcover_img, geom, dimensions=1400)
            forest_loss_url = image_thumb_url(forest_loss_img, geom, dimensions=1400)

            st.session_state.assessment_result = {
                "metrics": metrics,
                "risk": risk,
                "ndvi_hist_df": ndvi_hist_df,
                "rain_hist_df": rain_hist_df,
                "lst_hist_df": lst_hist_df,
                "forest_hist_df": forest_hist_df,
                "water_hist_df": water_hist_df,
                "landcover_df": landcover_table_from_metrics(metrics),
                "image_urls": {
                    "satellite": satellite_url,
                    "ndvi": ndvi_url,
                    "landcover": landcover_url,
                    "forest_loss": forest_loss_url,
                },
            }
            st.session_state.assessment_complete = True


# =====================================================
# 8. OUTPUTS
# =====================================================
if st.session_state.assessment_complete and st.session_state.assessment_result is not None:
    result = st.session_state.assessment_result
    metrics = result["metrics"]
    risk = result["risk"]

    st.markdown("---")
    st.markdown("## EagleNatureInsight™ Overview")

    st.write(f"**Business preset:** {st.session_state.preset_selector}")
    st.write(f"**Business category:** {st.session_state.category_selector}")

    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("Nature Risk", f'{risk["score"]}/100', risk["band"])
    with s2:
        st.metric("Current NDVI", safe_fmt(metrics.get("ndvi_current"), 3))
    with s3:
        st.metric("Rainfall Anomaly", safe_fmt(metrics.get("rain_anom_pct"), 1, "%"))

    s4, s5, s6 = st.columns(3)
    with s4:
        st.metric("Tree Cover", safe_fmt(metrics.get("tree_pct"), 1, "%"))
    with s5:
        st.metric("Built-up", safe_fmt(metrics.get("built_pct"), 1, "%"))
    with s6:
        st.metric("Surface Water", safe_fmt(metrics.get("water_occ"), 1))

    st.markdown("### Risk Gauge")
    st.progress(min(max(risk["score"] / 100.0, 0.0), 1.0))

    st.markdown("---")
    st.markdown("## LEAP Outputs")

    leap1, leap2 = st.columns(2)

    with leap1:
        with st.container(border=True):
            st.markdown("### Locate")
            st.write("The selected area has been defined and screened for land cover, visible nature context, and surrounding landscape conditions.")
            st.write(f'**Area of interest:** {safe_fmt(metrics.get("area_ha"), 1, " ha")}')
            st.write(f'**Tree cover:** {safe_fmt(metrics.get("tree_pct"), 1, "%")}')
            st.write(f'**Cropland:** {safe_fmt(metrics.get("cropland_pct"), 1, "%")}')
            st.write(f'**Built-up:** {safe_fmt(metrics.get("built_pct"), 1, "%")}')
            st.write(f'**Surface water occurrence:** {safe_fmt(metrics.get("water_occ"), 1)}')

        with st.container(border=True):
            st.markdown("### Evaluate")
            st.write("Current and historical environmental conditions have been reviewed using the dashboard indicators.")
            st.write(f'**Current NDVI:** {safe_fmt(metrics.get("ndvi_current"), 3)}')
            st.write(f'**Historical NDVI trend:** {safe_fmt(metrics.get("ndvi_trend"), 3)}')
            st.write(f'**Rainfall anomaly:** {safe_fmt(metrics.get("rain_anom_pct"), 1, "%")}')
            st.write(f'**Recent LST mean:** {safe_fmt(metrics.get("lst_mean"), 1, " °C")}')
            st.write(f'**Forest loss % of baseline forest:** {safe_fmt(metrics.get("forest_loss_pct"), 1, "%")}')

    with leap2:
        with st.container(border=True):
            st.markdown("### Assess")
            st.write("The dashboard interprets the evidence into a business-facing nature risk signal and identifies the most relevant issues.")
            st.write(f'**Nature risk score:** {risk["score"]} / 100')
            st.write(f'**Risk band:** {risk["band"]}')
            if risk["flags"]:
                for flag in risk["flags"]:
                    st.write(f"• {flag}")
            else:
                st.write("• No major automated flags triggered in the current rule set.")

        with st.container(border=True):
            st.markdown("### Prepare")
            st.write("The dashboard provides category-specific next actions based on the current signals and business context.")
            for rec in risk["recs"]:
                st.write(f"• {rec}")

    st.markdown("---")
    st.markdown("## Image Outputs")

    ic1, ic2 = st.columns(2)
    with ic1:
        render_image_card(
            "Satellite image with polygon",
            "Natural-colour satellite view with the selected assessment boundary outlined in red.",
            result["image_urls"]["satellite"],
            [("#ff0000", "Assessment boundary")],
        )
        render_image_card(
            "Land-cover image with polygon",
            "Current land-cover composition of the assessed area.",
            result["image_urls"]["landcover"],
            [
                ("#006400", "Tree cover"),
                ("#ffff4c", "Cropland / grass-dominant areas"),
                ("#fa0000", "Built-up"),
                ("#0064c8", "Water"),
                ("#b4b4b4", "Bare / sparse vegetation"),
                ("#ff0000", "Assessment boundary"),
            ],
        )

    with ic2:
        render_image_card(
            "NDVI image with polygon",
            "Current vegetation condition across the selected area.",
            result["image_urls"]["ndvi"],
            [
                ("#d73027", "Low vegetation greenness / stressed vegetation"),
                ("#fee08b", "Moderate vegetation condition"),
                ("#1a9850", "High vegetation greenness / healthier vegetation"),
                ("#ff0000", "Assessment boundary"),
            ],
        )
        render_image_card(
            "Forest loss map with polygon",
            "Areas where forest loss has been detected historically.",
            result["image_urls"]["forest_loss"],
            [
                ("#dc2626", "Detected forest loss"),
                ("#ff0000", "Assessment boundary"),
            ],
        )

    st.markdown("---")
    st.markdown("## Detailed Results")

    d1, d2 = st.columns(2)

    with d1:
        with st.container(border=True):
            st.markdown("### Summary metrics")
            st.write(f'**Selected range:** {st.session_state.hist_start} to {st.session_state.hist_end}')
            st.write(f'**Area:** {safe_fmt(metrics.get("area_ha"), 1, " ha")}')
            st.write(f'**Current NDVI:** {safe_fmt(metrics.get("ndvi_current"), 3)}')
            st.write(f'**Tree cover:** {safe_fmt(metrics.get("tree_pct"), 1, "%")}')
            st.write(f'**Cropland:** {safe_fmt(metrics.get("cropland_pct"), 1, "%")}')
            st.write(f'**Built-up:** {safe_fmt(metrics.get("built_pct"), 1, "%")}')
            st.write(f'**Surface water occurrence:** {safe_fmt(metrics.get("water_occ"), 1)}')
            st.write(f'**Recent LST mean:** {safe_fmt(metrics.get("lst_mean"), 1, " °C")}')

    with d2:
        with st.container(border=True):
            st.markdown("### Current land cover chart")
            landcover_df = result["landcover_df"].dropna()
            if not landcover_df.empty:
                fig_lc = px.bar(
                    landcover_df,
                    x="Class",
                    y="Percent",
                    title="Land Cover Composition (%)",
                )
                fig_lc.update_layout(height=350)
                st.plotly_chart(fig_lc, use_container_width=True)
            else:
                st.info("No land-cover composition available.")

    st.markdown("### Historical Plots")

    hc1, hc2 = st.columns(2)
    hc3, hc4 = st.columns(2)
    hc5, _ = st.columns(2)

    with hc1:
        ndvi_df = result["ndvi_hist_df"].dropna(subset=["year", "value"])
        if not ndvi_df.empty:
            fig = px.line(ndvi_df, x="year", y="value", markers=True, title="Historical NDVI (Landsat)")
            fig.update_layout(height=350, xaxis_title="Year", yaxis_title="NDVI")
            st.plotly_chart(fig, use_container_width=True)

    with hc2:
        rain_df = result["rain_hist_df"].dropna(subset=["year", "value"])
        if not rain_df.empty:
            fig = px.line(rain_df, x="year", y="value", markers=True, title="Historical Rainfall (CHIRPS)")
            fig.update_layout(height=350, xaxis_title="Year", yaxis_title="mm")
            st.plotly_chart(fig, use_container_width=True)

    with hc3:
        lst_df = result["lst_hist_df"].dropna(subset=["year", "value"])
        if not lst_df.empty:
            fig = px.line(lst_df, x="year", y="value", markers=True, title="Historical Land Surface Temperature (MODIS)")
            fig.update_layout(height=350, xaxis_title="Year", yaxis_title="°C")
            st.plotly_chart(fig, use_container_width=True)

    with hc4:
        forest_df = result["forest_hist_df"].dropna(subset=["year", "value"])
        if not forest_df.empty:
            fig = px.bar(forest_df, x="year", y="value", title="Historical Forest Loss by Year (Hansen)")
            fig.update_layout(height=350, xaxis_title="Year", yaxis_title="ha lost")
            st.plotly_chart(fig, use_container_width=True)

    with hc5:
        water_df = result["water_hist_df"].dropna(subset=["year", "value"])
        if not water_df.empty:
            fig = px.line(water_df, x="year", y="value", markers=True, title="Historical Water Presence (JRC)")
            fig.update_layout(height=350, xaxis_title="Year", yaxis_title="% water pixels")
            st.plotly_chart(fig, use_container_width=True)
