from pathlib import Path
from datetime import date

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
    satellite_with_polygon,
    ndvi_with_polygon,
    landcover_with_polygon,
    forest_loss_with_polygon,
    vegetation_change_with_polygon,
    image_thumb_url,
    landsat_annual_ndvi_collection,
    annual_rain_collection,
    annual_lst_collection,
    forest_loss_by_year_collection,
    water_history_collection,
)
from utils.scoring import build_risk_and_recommendations


st.set_page_config(page_title="EagleNatureInsight", layout="wide")

APP_TITLE = "EagleNatureInsight™"
APP_SUBTITLE = "Nature Intelligence Dashboard for SMEs"
APP_TAGLINE = "Locate • Evaluate • Assess • Prepare"

CURRENT_YEAR = date.today().year
LAST_FULL_YEAR = CURRENT_YEAR - 1

LOGO_PATH = Path("assets/logo.png")

PRESET_TO_CATEGORY = {
    "Panuka AgriBiz Hub": "Agriculture / Agribusiness",
    "BL Turner Group": "Water / Circular economy",
}

PRESET_TO_LOCATION = {
    "Panuka AgriBiz Hub": {"lat": -15.3875, "lon": 28.3228, "buffer_m": 1500, "zoom": 12},
    "BL Turner Group": {"lat": -29.9167, "lon": 31.0218, "buffer_m": 1000, "zoom": 13},
}

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


def init_state():
    defaults = {
        "preset_selector": "Select Business / Area",
        "active_preset": "Select Business / Area",
        "category_selector": "General SME",
        "lat_input": "",
        "lon_input": "",
        "buffer_input": 1000,
        "map_center": [-25.0, 24.0],
        "map_zoom": 5,
        "draw_mode": "Draw polygon",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def apply_preset(preset: str):
    st.session_state["active_preset"] = preset

    if preset in PRESET_TO_CATEGORY:
        st.session_state["category_selector"] = PRESET_TO_CATEGORY[preset]

    if preset in PRESET_TO_LOCATION:
        loc = PRESET_TO_LOCATION[preset]
        st.session_state["lat_input"] = str(loc["lat"])
        st.session_state["lon_input"] = str(loc["lon"])
        st.session_state["buffer_input"] = int(loc["buffer_m"])
        st.session_state["map_center"] = [loc["lat"], loc["lon"]]
        st.session_state["map_zoom"] = loc["zoom"]


def preset_changed():
    preset = st.session_state["preset_selector"]
    st.session_state["active_preset"] = preset
    if preset != "Select Business / Area":
        apply_preset(preset)


def build_map(center, zoom):
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        control_scale=True,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Satellite"
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


def extract_drawn_geometry(map_data):
    if not map_data:
        return None
    drawings = map_data.get("all_drawings") or []
    if not drawings:
        return None
    return drawings[-1]


def get_geometry_payload(drawn_geojson, lat, lon, buffer_m, mode):
    if mode == "Draw polygon":
        if drawn_geojson:
            return "Polygon captured from map drawing.", drawn_geojson, geojson_to_ee_geometry(drawn_geojson)
        return "No polygon drawn yet.", None, None

    try:
        lat_val = float(lat)
        lon_val = float(lon)
        geom = point_buffer_to_ee_geometry(lat_val, lon_val, float(buffer_m))
        payload = {
            "type": "PointBuffer",
            "lat": lat_val,
            "lon": lon_val,
            "buffer_m": float(buffer_m),
        }
        return (
            f"Point entered at ({lat_val:.5f}, {lon_val:.5f}) with {buffer_m} m buffer.",
            payload,
            geom,
        )
    except (TypeError, ValueError):
        return "Please enter valid latitude and longitude.", None, None


def fc_to_dataframe(fc) -> pd.DataFrame:
    info = fc.getInfo()
    rows = []
    for feature in info.get("features", []):
        props = feature.get("properties", {})
        rows.append(props)
    return pd.DataFrame(rows)


def prep_year_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "value" in df.columns:
        df = df[df["value"].notna()].copy()
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df = df[df["year"].notna()].copy()
        df["year"] = df["year"].astype(int)
    return df.sort_values("year")


def metric_card(label: str, value: str):
    st.markdown(
        f"""
        <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;">
            <div style="font-size:12px;color:#6b7280;">{label}</div>
            <div style="font-size:26px;font-weight:700;color:#111827;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


init_state()

try:
    initialize_ee_from_secrets(st)
except Exception as e:
    st.error("Earth Engine initialization failed. Check your Streamlit secrets and Google Cloud permissions.")
    st.exception(e)
    st.stop()

header_left, header_right = st.columns([2, 6])
with header_left:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)

with header_right:
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.markdown(f"**{APP_TAGLINE}**")

st.markdown("---")

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

st.markdown("---")

left_col, right_col = st.columns(2)
with left_col:
    st.selectbox(
        "Select business or assessment area",
        PRESETS,
        key="preset_selector",
        on_change=preset_changed,
    )

with right_col:
    focus1, focus2 = st.columns(2)
    with focus1:
        if st.button("Focus Panuka", use_container_width=True):
            apply_preset("Panuka AgriBiz Hub")
            st.rerun()
    with focus2:
        if st.button("Focus BL Turner", use_container_width=True):
            apply_preset("BL Turner Group")
            st.rerun()

st.selectbox(
    "Business category",
    CATEGORIES,
    key="category_selector",
)

mode_col1, mode_col2 = st.columns([1, 1])
with mode_col1:
    st.radio(
        "Site definition method",
        ["Draw polygon", "Enter coordinates"],
        key="draw_mode",
        horizontal=True,
    )

with mode_col2:
    st.number_input(
        "Buffer radius (metres)",
        min_value=100,
        max_value=50000,
        step=100,
        key="buffer_input",
        disabled=(st.session_state.draw_mode == "Draw polygon"),
    )

if st.session_state.draw_mode == "Enter coordinates":
    lat_col, lon_col = st.columns(2)
    with lat_col:
        st.text_input("Latitude", key="lat_input", placeholder="-29.9167")
    with lon_col:
        st.text_input("Longitude", key="lon_input", placeholder="31.0218")

hist1, hist2 = st.columns(2)
with hist1:
    hist_start = st.number_input("Historical start year", min_value=1981, max_value=LAST_FULL_YEAR, value=2001, step=1)
with hist2:
    hist_end = st.number_input("Historical end year", min_value=1981, max_value=LAST_FULL_YEAR, value=LAST_FULL_YEAR, step=1)

st.markdown("### Site Selection")
m = build_map(
    center=st.session_state.map_center,
    zoom=st.session_state.map_zoom,
)

map_data = st_folium(
    m,
    width=None,
    height=520,
    returned_objects=["all_drawings"],
    key="eaglenatureinsight_map",
)

drawn_geojson = extract_drawn_geometry(map_data)
summary_text, geometry_payload, ee_geom = get_geometry_payload(
    drawn_geojson=drawn_geojson,
    lat=st.session_state.lat_input,
    lon=st.session_state.lon_input,
    buffer_m=st.session_state.buffer_input,
    mode=st.session_state.draw_mode,
)

st.markdown("### Current Selection")
st.write(summary_text)

with st.expander("Show geometry payload"):
    if geometry_payload is None:
        st.write("No valid geometry available yet.")
    else:
        st.json(geometry_payload)

run = st.button("Run Assessment", use_container_width=True)

if run:
    if ee_geom is None:
        st.warning("Please draw a polygon or enter valid coordinates first.")
        st.stop()

    if hist_start > hist_end:
        st.warning("Historical start year must be earlier than or equal to end year.")
        st.stop()

    preset = st.session_state.active_preset
    category = st.session_state.category_selector

    with st.spinner("Running assessment..."):
        metrics = compute_metrics(
            geom=ee_geom,
            hist_start=int(hist_start),
            hist_end=int(hist_end),
            last_full_year=LAST_FULL_YEAR,
        )
        risk = build_risk_and_recommendations(
            preset=preset,
            category=category,
            metrics=metrics,
        )

        satellite_url = image_thumb_url(
            satellite_with_polygon(ee_geom, LAST_FULL_YEAR), ee_geom, 1400
        )
        ndvi_url = image_thumb_url(
            ndvi_with_polygon(ee_geom, LAST_FULL_YEAR), ee_geom, 1400
        )
        landcover_url = image_thumb_url(
            landcover_with_polygon(ee_geom), ee_geom, 1400
        )
        forest_loss_url = image_thumb_url(
            forest_loss_with_polygon(ee_geom), ee_geom, 1400
        )
        veg_change_url = image_thumb_url(
            vegetation_change_with_polygon(ee_geom, int(hist_start), int(hist_end)), ee_geom, 1400
        )

        ndvi_hist_df = prep_year_df(fc_to_dataframe(
            landsat_annual_ndvi_collection(ee_geom, max(int(hist_start), 1984), int(hist_end))
        ))
        rain_hist_df = prep_year_df(fc_to_dataframe(
            annual_rain_collection(ee_geom, max(int(hist_start), 1981), int(hist_end))
        ))
        lst_hist_df = prep_year_df(fc_to_dataframe(
            annual_lst_collection(ee_geom, max(int(hist_start), 2001), int(hist_end))
        ))
        forest_hist_df = prep_year_df(fc_to_dataframe(
            forest_loss_by_year_collection(ee_geom, int(hist_start), int(hist_end))
        ))
        water_hist_df = prep_year_df(fc_to_dataframe(
            water_history_collection(ee_geom, max(int(hist_start), 1984), int(hist_end))
        ))

    st.success("Assessment complete.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Overview", "LEAP", "Images", "Trends", "Detailed Results"]
    )

    with tab1:
        st.markdown("## EagleNatureInsight™ Overview")
        st.write(f"**Business preset:** {preset}")
        st.write(f"**Business category:** {category}")

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            metric_card("Nature Risk", f'{risk["score"]}/100 ({risk["band"]})')
        with mc2:
            metric_card("Current NDVI", f'{metrics.get("ndvi_current", 0):.3f}' if metrics.get("ndvi_current") is not None else "—")
        with mc3:
            metric_card("Rainfall Anomaly", f'{metrics.get("rain_anom_pct", 0):.1f}%' if metrics.get("rain_anom_pct") is not None else "—")

        mc4, mc5, mc6 = st.columns(3)
        with mc4:
            metric_card("Tree Cover", f'{metrics.get("tree_pct", 0):.1f}%' if metrics.get("tree_pct") is not None else "—")
        with mc5:
            metric_card("Built-up", f'{metrics.get("built_pct", 0):.1f}%' if metrics.get("built_pct") is not None else "—")
        with mc6:
            metric_card("Surface Water", f'{metrics.get("water_occ", 0):.1f}' if metrics.get("water_occ") is not None else "—")

    with tab2:
        st.markdown("## LEAP Outputs")

        st.markdown("### Locate")
        st.write("The selected area has been defined and screened for land cover, visible nature context, and surrounding landscape conditions.")
        st.write(f'Area of interest: {metrics.get("area_ha", 0):.1f} ha' if metrics.get("area_ha") is not None else "Area of interest: —")
        st.write(f'Tree cover: {metrics.get("tree_pct", 0):.1f}%' if metrics.get("tree_pct") is not None else "Tree cover: —")
        st.write(f'Cropland: {metrics.get("cropland_pct", 0):.1f}%' if metrics.get("cropland_pct") is not None else "Cropland: —")
        st.write(f'Built-up: {metrics.get("built_pct", 0):.1f}%' if metrics.get("built_pct") is not None else "Built-up: —")
        st.write(f'Surface water occurrence: {metrics.get("water_occ", 0):.1f}' if metrics.get("water_occ") is not None else "Surface water occurrence: —")

        st.markdown("### Evaluate")
        st.write("Current and historical environmental conditions have been reviewed using the dashboard indicators.")
        st.write(f'Current NDVI: {metrics.get("ndvi_current", 0):.3f}' if metrics.get("ndvi_current") is not None else "Current NDVI: —")
        st.write(f'Historical NDVI trend: {metrics.get("ndvi_trend", 0):.3f}' if metrics.get("ndvi_trend") is not None else "Historical NDVI trend: —")
        st.write(f'Rainfall anomaly: {metrics.get("rain_anom_pct", 0):.1f}%' if metrics.get("rain_anom_pct") is not None else "Rainfall anomaly: —")
        st.write(f'Recent LST mean: {metrics.get("lst_mean", 0):.1f} °C' if metrics.get("lst_mean") is not None else "Recent LST mean: —")
        st.write(f'Forest loss % of baseline forest: {metrics.get("forest_loss_pct", 0):.1f}%' if metrics.get("forest_loss_pct") is not None else "Forest loss % of baseline forest: —")

        st.markdown("### Assess")
        st.write("The dashboard interprets the evidence into a business-facing nature risk signal and identifies the most relevant issues.")
        st.write(f'Nature risk score: {risk["score"]} / 100')
        st.write(f'Risk band: {risk["band"]}')
        if risk["flags"]:
            for flag in risk["flags"]:
                st.write(f"• {flag}")
        else:
            st.write("• No major automated flags triggered in the current rule set.")

        st.markdown("### Prepare")
        st.write("The dashboard provides category-specific next actions based on the current signals and business context.")
        for rec in risk["recs"]:
            st.write(f"• {rec}")

    with tab3:
        st.markdown("## Image Outputs")
        img1, img2 = st.columns(2)
        with img1:
            st.image(satellite_url, caption="Satellite image with polygon", use_container_width=True)
            st.image(ndvi_url, caption="NDVI vegetation health", use_container_width=True)
            st.image(veg_change_url, caption="Vegetation change map", use_container_width=True)
        with img2:
            st.image(landcover_url, caption="Land cover classification", use_container_width=True)
            st.image(forest_loss_url, caption="Forest loss map", use_container_width=True)

    with tab4:
        st.markdown("## Historical Trends")

        if not ndvi_hist_df.empty:
            fig = px.line(ndvi_hist_df, x="year", y="value", title="Historical NDVI (Landsat)")
            st.plotly_chart(fig, use_container_width=True)
        if not rain_hist_df.empty:
            fig = px.line(rain_hist_df, x="year", y="value", title="Historical Rainfall (CHIRPS)")
            st.plotly_chart(fig, use_container_width=True)
        if not lst_hist_df.empty:
            fig = px.line(lst_hist_df, x="year", y="value", title="Historical Land Surface Temperature (MODIS)")
            st.plotly_chart(fig, use_container_width=True)
        if not forest_hist_df.empty:
            fig = px.bar(forest_hist_df, x="year", y="value", title="Historical Forest Loss by Year (Hansen)")
            st.plotly_chart(fig, use_container_width=True)
        if not water_hist_df.empty:
            fig = px.line(water_hist_df, x="year", y="value", title="Historical Water Presence (JRC)")
            st.plotly_chart(fig, use_container_width=True)

    with tab5:
        st.markdown("## Detailed Results")
        detail_df = pd.DataFrame(
            {
                "Metric": [
                    "Business preset",
                    "Business category",
                    "Selected range",
                    "Area (ha)",
                    "Current NDVI",
                    "Tree cover (%)",
                    "Cropland (%)",
                    "Built-up (%)",
                    "Surface water occurrence",
                    "Recent LST mean (°C)",
                    "Forest loss (ha)",
                    "Forest loss (%)",
                    "Biome context proxy",
                ],
                "Value": [
                    preset,
                    category,
                    f"{hist_start} to {hist_end}",
                    metrics.get("area_ha"),
                    metrics.get("ndvi_current"),
                    metrics.get("tree_pct"),
                    metrics.get("cropland_pct"),
                    metrics.get("built_pct"),
                    metrics.get("water_occ"),
                    metrics.get("lst_mean"),
                    metrics.get("forest_loss_ha"),
                    metrics.get("forest_loss_pct"),
                    metrics.get("bio_proxy"),
                ],
            }
        )
        st.dataframe(detail_df, use_container_width=True)
