from pathlib import Path
from datetime import date
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import matplotlib.pyplot as plt
import requests

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
    landcover_feature_collection,
)
from utils.scoring import build_risk_and_recommendations
from utils.pdf_report import build_pdf_report


st.set_page_config(page_title="EagleNatureInsight", layout="wide")

APP_TITLE = "EagleNatureInsight"
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
        "last_drawn_geojson": None,
        "report_payload": None,
        "results_payload": None,
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


def build_map(center, zoom, draw_mode, lat=None, lon=None, buffer_m=None, existing_geojson=None):
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        control_scale=True,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Satellite",
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

    if existing_geojson:
        folium.GeoJson(
            existing_geojson,
            style_function=lambda x: {
                "color": "#ff0000",
                "weight": 3,
                "fillOpacity": 0.05,
            },
        ).add_to(m)

    if draw_mode == "Enter coordinates":
        try:
            lat_val = float(lat)
            lon_val = float(lon)
            folium.Marker([lat_val, lon_val], tooltip="Selected point").add_to(m)
            if buffer_m:
                folium.Circle(
                    [lat_val, lon_val],
                    radius=float(buffer_m),
                    color="#ff0000",
                    weight=2,
                    fill=False,
                ).add_to(m)
        except (TypeError, ValueError):
            pass

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


def metric_card(label: str, value: str, subtext: str = ""):
    st.markdown(
        f"""
        <div style="padding:14px;border:1px solid #e5e7eb;border-radius:18px;background:#ffffff;height:116px;box-shadow:0 6px 18px rgba(17,24,39,0.06);">
            <div style="font-size:12px;color:#6b7280;">{label}</div>
            <div style="font-size:28px;font-weight:700;color:#111827;margin-top:6px;">{value}</div>
            <div style="font-size:11px;color:#6b7280;margin-top:5px;">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def fmt_num(val, digits=1, suffix=""):
    if val is None:
        return "—"
    try:
        return f"{float(val):.{digits}f}{suffix}"
    except Exception:
        return "—"


def build_overview_content(preset: str, category: str, metrics: dict, risk: dict) -> dict:
    ndvi_current = metrics.get("ndvi_current")
    ndvi_trend = metrics.get("ndvi_trend")
    rain_anom_pct = metrics.get("rain_anom_pct")
    tree_pct = metrics.get("tree_pct")
    built_pct = metrics.get("built_pct")
    water_occ = metrics.get("water_occ")
    forest_loss_pct = metrics.get("forest_loss_pct")
    lst_mean = metrics.get("lst_mean")

    narrative = (
        "This overview screens how the selected site interacts with nature and highlights the main "
        "conditions and trends a business should pay attention to first. It is designed as an early "
        "screening output, not a substitute for detailed field assessment."
    )

    findings = []
    if ndvi_trend is not None and ndvi_trend < -0.03:
        findings.append("Vegetation condition around the site has been declining over time.")
    if rain_anom_pct is not None and rain_anom_pct < -10:
        findings.append("Recent rainfall is below the long-term baseline, which may increase water stress.")
    if forest_loss_pct is not None and forest_loss_pct > 5:
        findings.append("Tree loss has been detected in the surrounding landscape.")
    if water_occ is not None and water_occ < 5:
        findings.append("Visible surface water is limited in the surrounding landscape.")
    if built_pct is not None and built_pct > 35:
        findings.append("A large share of the area is built-up, which can increase heat and reduce ecological function.")
    if tree_pct is not None and tree_pct < 10:
        findings.append("Tree cover is limited, which may reduce natural buffering and resilience.")
    if lst_mean is not None and lst_mean > 30:
        findings.append("Land surface temperatures are high, which may increase operational heat stress.")

    if not findings:
        findings.append("No major warning signal stands out immediately, but the site should still be monitored over time.")

    findings = findings[:3]

    if category == "Agriculture / Agribusiness":
        business_relevance = (
            "For an agribusiness, these conditions matter because vegetation, rainfall, tree cover, and water "
            "availability can influence productivity, soil protection, pollination, and resilience."
        )
    elif category == "Food processing / Supply chain":
        business_relevance = (
            "For a food or supply-chain business, these conditions matter because environmental pressure in "
            "sourcing landscapes can affect supply reliability, quality, and climate resilience."
        )
    elif category == "Manufacturing / Industrial":
        business_relevance = (
            "For a manufacturing or industrial site, these conditions matter because heat, low vegetation, and "
            "land-cover pressure can affect worker comfort, site resilience, and future compliance expectations."
        )
    elif category == "Water / Circular economy":
        business_relevance = (
            "For a water or circular-economy business, these conditions matter because local water context, heat, "
            "and ecological condition can affect water security and operational resilience."
        )
    elif category == "Energy / Infrastructure":
        business_relevance = (
            "For energy or infrastructure operations, these conditions matter because site expansion, ecological "
            "sensitivity, and surrounding land-cover change can create environmental and transition risks."
        )
    elif category == "Property / Built environment":
        business_relevance = (
            "For a built-environment or property site, these conditions matter because low vegetation, heat, and "
            "built-up intensity can affect site quality, comfort, and future retrofit needs."
        )
    else:
        business_relevance = (
            "These conditions matter because they provide an early view of how the site depends on and may be "
            "affected by surrounding ecological change."
        )

    return {
        "narrative": narrative,
        "findings": findings,
        "business_relevance": business_relevance,
    }


def build_locate_content(preset: str, category: str, metrics: dict) -> dict:
    tree_pct = metrics.get("tree_pct")
    cropland_pct = metrics.get("cropland_pct")
    built_pct = metrics.get("built_pct")
    water_occ = metrics.get("water_occ")
    area_ha = metrics.get("area_ha")

    narrative = (
        "This section shows where the business interfaces with nature by describing the assessment area, "
        "the surrounding land-cover setting, and visible ecological features in the local landscape."
    )

    context_points = []
    if tree_pct is not None:
        if tree_pct >= 30:
            context_points.append("The surrounding landscape includes a meaningful share of tree cover.")
        elif tree_pct < 10:
            context_points.append("Tree cover is limited in the surrounding landscape.")
    if cropland_pct is not None and cropland_pct >= 20:
        context_points.append("A notable portion of the area is used as cropland, which may shape the business-nature interface.")
    if built_pct is not None and built_pct >= 20:
        context_points.append("Built surfaces are an important part of the site context and may influence heat, runoff, and habitat quality.")
    if water_occ is not None and water_occ >= 5:
        context_points.append("Surface water is visible in or around the assessment area and may be relevant to business dependencies or impacts.")
    elif water_occ is not None and water_occ < 5:
        context_points.append("Visible surface water is limited, so the site may rely more strongly on rainfall, groundwater, or external supply.")

    if not context_points:
        context_points.append("The site has been located successfully and its land-cover setting can now be interpreted in relation to business activities.")

    if category == "Agriculture / Agribusiness":
        why_it_matters = (
            "For an agribusiness, location matters because nearby vegetation, cropland, and water context influence pollination, soil protection, and production resilience."
        )
    elif category == "Food processing / Supply chain":
        why_it_matters = (
            "For a food or supply-chain business, site context matters because sourcing landscapes and surrounding ecosystem condition can affect long-term supply reliability."
        )
    elif category == "Manufacturing / Industrial":
        why_it_matters = (
            "For a manufacturing or industrial site, location matters because built-up intensity, water context, and surrounding vegetation shape operational resilience and future environmental expectations."
        )
    elif category == "Water / Circular economy":
        why_it_matters = (
            "For a water or circular-economy business, the local nature context matters because visible water, vegetation, and land-cover setting shape water stewardship opportunities and risks."
        )
    elif category == "Energy / Infrastructure":
        why_it_matters = (
            "For energy or infrastructure operations, knowing where the site interfaces with nature helps identify sensitive areas, land pressure, and potential future constraints on expansion."
        )
    elif category == "Property / Built environment":
        why_it_matters = (
            "For the built environment, the local land-cover pattern matters because it influences heat, runoff, comfort, and the scope for greening and restoration."
        )
    else:
        why_it_matters = (
            "Understanding where the site interfaces with nature helps the business identify which environmental features may matter most in later risk and action planning."
        )

    return {
        "narrative": narrative,
        "context_points": context_points[:4],
        "why_it_matters": why_it_matters,
        "area_text": fmt_num(area_ha, 1, " ha"),
    }


def df_chart_to_png_bytes(df, x_col, y_col, title, kind="line", x_label="Year", y_label="Value"):
    if df is None or df.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 5.2))
    if kind == "bar":
        ax.bar(df[x_col], df[y_col])
    else:
        ax.plot(df[x_col], df[y_col], marker="o")

    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def landcover_bar_to_png_bytes(df):
    if df is None or df.empty:
        return None

    df2 = df.sort_values("area_ha", ascending=False).copy()

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(df2["class_name"], df2["area_ha"])
    ax.set_title("Current Land Cover Composition")
    ax.set_xlabel("Land-cover class")
    ax.set_ylabel("Area (ha)")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_landcover_bar(df):
    fig = px.bar(
        df.sort_values("area_ha", ascending=False),
        x="class_name",
        y="area_ha",
        title="Current Land Cover Composition",
    )
    fig.update_layout(
        xaxis_title="Land-cover class",
        yaxis_title="Area (ha)",
        showlegend=False,
        margin=dict(l=40, r=20, t=60, b=80),
    )
    return fig


def fetch_image_bytes(url: str, timeout: int = 60):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        buf = BytesIO(r.content)
        buf.seek(0)
        return buf
    except Exception:
        return None


def fetch_pdf_ee_image_bytes(image, geom, dimensions=900, retries=3):
    attempt_dims = [dimensions, 700, 500]

    for i in range(min(retries, len(attempt_dims))):
        try:
            url = image_thumb_url(image, geom, dimensions=attempt_dims[i])
            result = fetch_image_bytes(url, timeout=150)
            if result is not None:
                return result
        except Exception:
            pass

    return None


init_state()

try:
    initialize_ee_from_secrets(st)
except Exception as e:
    st.error("Earth Engine initialization failed. Check your Streamlit secrets and Google Cloud permissions.")
    st.exception(e)
    st.stop()

st.markdown(
    """
    <style>
    .top-hero {
        background: linear-gradient(135deg, #163d63 0%, #235784 55%, #2f6ea2 100%);
        border-radius: 24px;
        padding: 24px 28px;
        color: white;
        box-shadow: 0 10px 28px rgba(22,61,99,0.20);
        margin-bottom: 18px;
    }
    .top-sub {
        color: rgba(255,255,255,0.88);
        font-size: 0.98rem;
        margin-top: 2px;
    }
    .top-tag {
        display: inline-block;
        margin-top: 10px;
        padding: 7px 12px;
        border-radius: 999px;
        background: rgba(255,255,255,0.14);
        font-size: 0.88rem;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

hero_left, hero_right = st.columns([1.2, 5])

with hero_left:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=500)

with hero_right:
    st.markdown(
        f"""
        <div class="top-hero">
            <div style="font-size:2rem;font-weight:800;line-height:1.1;">{APP_TITLE}</div>
            <div class="top-sub">{APP_SUBTITLE}</div>
            <div class="top-tag">{APP_TAGLINE}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
        disabled=(st.session_state["draw_mode"] == "Draw polygon"),
    )

if st.session_state["draw_mode"] == "Enter coordinates":
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
    center=st.session_state["map_center"],
    zoom=st.session_state["map_zoom"],
    draw_mode=st.session_state["draw_mode"],
    lat=st.session_state["lat_input"],
    lon=st.session_state["lon_input"],
    buffer_m=st.session_state["buffer_input"],
    existing_geojson=st.session_state["last_drawn_geojson"],
)

map_data = st_folium(
    m,
    width=None,
    height=520,
    returned_objects=["all_drawings"],
    key="eaglenatureinsight_map",
)

drawn_geojson = extract_drawn_geometry(map_data)
if drawn_geojson is not None:
    st.session_state["last_drawn_geojson"] = drawn_geojson

summary_text, geometry_payload, ee_geom = get_geometry_payload(
    drawn_geojson=st.session_state["last_drawn_geojson"] if st.session_state["draw_mode"] == "Draw polygon" else None,
    lat=st.session_state["lat_input"],
    lon=st.session_state["lon_input"],
    buffer_m=st.session_state["buffer_input"],
    mode=st.session_state["draw_mode"],
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

    preset = st.session_state["active_preset"]
    category = st.session_state["category_selector"]

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

        satellite_img = satellite_with_polygon(ee_geom, LAST_FULL_YEAR)
        ndvi_img = ndvi_with_polygon(ee_geom, LAST_FULL_YEAR)
        landcover_img = landcover_with_polygon(ee_geom)
        forest_loss_img = forest_loss_with_polygon(ee_geom)
        veg_change_img = vegetation_change_with_polygon(ee_geom, int(hist_start), int(hist_end))

        satellite_url = image_thumb_url(satellite_img, ee_geom, 2200)
        ndvi_url = image_thumb_url(ndvi_img, ee_geom, 1400)
        landcover_url = image_thumb_url(landcover_img, ee_geom, 1400)
        forest_loss_url = image_thumb_url(forest_loss_img, ee_geom, 1400)
        veg_change_url = image_thumb_url(veg_change_img, ee_geom, 1400)

        ndvi_hist_df = prep_year_df(
            fc_to_dataframe(
                landsat_annual_ndvi_collection(ee_geom, max(int(hist_start), 1984), int(hist_end))
            )
        )
        rain_hist_df = prep_year_df(
            fc_to_dataframe(
                annual_rain_collection(ee_geom, max(int(hist_start), 1981), int(hist_end))
            )
        )
        lst_hist_df = prep_year_df(
            fc_to_dataframe(
                annual_lst_collection(ee_geom, max(int(hist_start), 2001), int(hist_end))
            )
        )
        forest_hist_df = prep_year_df(
            fc_to_dataframe(
                forest_loss_by_year_collection(ee_geom, int(hist_start), int(hist_end))
            )
        )
        water_hist_df = prep_year_df(
            fc_to_dataframe(
                water_history_collection(ee_geom, max(int(hist_start), 1984), int(hist_end))
            )
        )
        lc_df = fc_to_dataframe(landcover_feature_collection(ee_geom))
        if not lc_df.empty and "area_ha" in lc_df.columns:
            lc_df["area_ha"] = pd.to_numeric(lc_df["area_ha"], errors="coerce")
            lc_df = lc_df[lc_df["area_ha"].notna()].copy()
            lc_df = lc_df[lc_df["area_ha"] > 0].copy()

        chart_payloads = [
            {
                "title": "Historical NDVI",
                "description": "This plot shows how vegetation condition has changed over time. Rising values usually suggest stronger vegetation cover, while falling values may indicate declining vegetation condition.",
                "bytes": df_chart_to_png_bytes(ndvi_hist_df, "year", "value", "Historical NDVI (Landsat)", kind="line", y_label="NDVI"),
            },
            {
                "title": "Historical rainfall",
                "description": "This plot shows the rainfall pattern across the selected historical period. Lower rainfall over time can point to greater water stress.",
                "bytes": df_chart_to_png_bytes(rain_hist_df, "year", "value", "Historical Rainfall (CHIRPS)", kind="line", y_label="mm"),
            },
            {
                "title": "Historical land surface temperature",
                "description": "This plot shows how land surface temperature has changed over time. Higher values may suggest growing heat pressure across the site.",
                "bytes": df_chart_to_png_bytes(lst_hist_df, "year", "value", "Historical Land Surface Temperature (MODIS)", kind="line", y_label="°C"),
            },
            {
                "title": "Historical forest loss",
                "description": "This plot shows how much forest loss was detected each year. Larger bars indicate greater forest loss in that year.",
                "bytes": df_chart_to_png_bytes(forest_hist_df, "year", "value", "Historical Forest Loss by Year (Hansen)", kind="bar", y_label="ha"),
            },
            {
                "title": "Historical water presence",
                "description": "This plot shows how water presence has changed over time. Lower values may suggest reduced visible water in the landscape.",
                "bytes": df_chart_to_png_bytes(water_hist_df, "year", "value", "Historical Water Presence (JRC)", kind="line", y_label="% water pixels"),
            },
            {
                "title": "Current land-cover composition",
                "description": "This chart shows how the selected area is currently divided across land-cover classes such as tree cover, cropland, built-up land, and water.",
                "bytes": landcover_bar_to_png_bytes(lc_df),
            },
        ]

        image_payloads = [
            {
                "title": "Satellite image with polygon",
                "description": "This is a true-colour satellite view of the selected site. The red outline shows the assessment area.",
                "bytes": fetch_pdf_ee_image_bytes(satellite_img, ee_geom, dimensions=700),
            },
            {
                "title": "NDVI image with polygon",
                "description": "This image shows vegetation condition. Greener areas generally mean healthier or denser vegetation. Redder areas generally mean weaker vegetation.",
                "bytes": fetch_pdf_ee_image_bytes(ndvi_img, ee_geom, dimensions=700),
            },
            {
                "title": "Land-cover image with polygon",
                "description": "This image shows the main land-cover types in the selected area, such as tree cover, cropland, built-up land, and water.",
                "bytes": fetch_pdf_ee_image_bytes(landcover_img, ee_geom, dimensions=850),
            },
            {
                "title": "Vegetation change map with polygon",
                "description": "This image compares earlier and more recent vegetation condition. Redder areas suggest decline. Greener areas suggest improvement.",
                "bytes": fetch_pdf_ee_image_bytes(veg_change_img, ee_geom, dimensions=500),
            },
            {
                "title": "Forest loss map with polygon",
                "description": "This image highlights where forest loss has been detected in or around the selected area.",
                "bytes": fetch_pdf_ee_image_bytes(forest_loss_img, ee_geom, dimensions=850),
            },
        ]

        pdf_bytes = build_pdf_report(
            preset=preset,
            category=category,
            hist_start=int(hist_start),
            hist_end=int(hist_end),
            metrics=metrics,
            risk=risk,
            image_payloads=image_payloads,
            chart_payloads=chart_payloads,
        )

        st.session_state["report_payload"] = {
            "pdf_bytes": pdf_bytes,
            "file_name": f"EagleNatureInsight_Report_{date.today().isoformat()}.pdf",
        }

        st.session_state["results_payload"] = {
            "preset": preset,
            "category": category,
            "metrics": metrics,
            "risk": risk,
            "satellite_url": satellite_url,
            "ndvi_url": ndvi_url,
            "landcover_url": landcover_url,
            "forest_loss_url": forest_loss_url,
            "veg_change_url": veg_change_url,
            "ndvi_hist_df": ndvi_hist_df,
            "rain_hist_df": rain_hist_df,
            "lst_hist_df": lst_hist_df,
            "forest_hist_df": forest_hist_df,
            "water_hist_df": water_hist_df,
            "lc_df": lc_df,
        }

    st.success("Assessment complete.")

if st.session_state["report_payload"] is not None:
    st.download_button(
        label="Download PDF Report",
        data=st.session_state["report_payload"]["pdf_bytes"],
        file_name=st.session_state["report_payload"]["file_name"],
        mime="application/pdf",
        use_container_width=True,
    )

results = st.session_state["results_payload"]

if results is not None:
    preset = results["preset"]
    category = results["category"]
    metrics = results["metrics"]
    risk = results["risk"]
    satellite_url = results["satellite_url"]
    ndvi_url = results["ndvi_url"]
    landcover_url = results["landcover_url"]
    forest_loss_url = results["forest_loss_url"]
    veg_change_url = results["veg_change_url"]
    ndvi_hist_df = results["ndvi_hist_df"]
    rain_hist_df = results["rain_hist_df"]
    lst_hist_df = results["lst_hist_df"]
    forest_hist_df = results["forest_hist_df"]
    water_hist_df = results["water_hist_df"]
    lc_df = results["lc_df"]
    overview = build_overview_content(preset, category, metrics, risk)
    locate = build_locate_content(preset, category, metrics)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
        ["Overview", "Locate", "Evaluate", "Assess", "Prepare", "Images", "Trends", "Detailed Results"]
    )

    with tab1:
        st.markdown("## EagleNatureInsight Overview")
        st.write(f"**Business preset:** {preset}")
        st.write(f"**Business category:** {category}")
        st.write(overview["narrative"])

        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            metric_card("Area analysed", fmt_num(metrics.get("area_ha"), 1, " ha"), "Assessment area")
        with r1c2:
            metric_card("Current vegetation", fmt_num(metrics.get("ndvi_current"), 3), "NDVI")
        with r1c3:
            metric_card("Vegetation trend", fmt_num(metrics.get("ndvi_trend"), 3), "Historical change")

        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            metric_card("Rainfall context", fmt_num(metrics.get("rain_anom_pct"), 1, "%"), "vs 1981–2010")
        with r2c2:
            metric_card("Tree cover", fmt_num(metrics.get("tree_pct"), 1, "%"), "Current landscape")
        with r2c3:
            metric_card("Surface water", fmt_num(metrics.get("water_occ"), 1), "Occurrence")

        st.markdown("### Top findings")
        for finding in overview["findings"]:
            st.write(f"• {finding}")

        st.markdown("### Why this matters to the business")
        st.write(overview["business_relevance"])

    with tab2:
        st.markdown("## Locate")
        st.write(locate["narrative"])

        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Area analysed", locate["area_text"], "Assessment area")
        with c2:
            metric_card("Tree cover", fmt_num(metrics.get("tree_pct"), 1, "%"), "Landscape context")
        with c3:
            metric_card("Surface water", fmt_num(metrics.get("water_occ"), 1), "Occurrence")

        st.markdown("### Site context")
        st.write(f"**Business preset:** {preset}")
        st.write(f"**Business category:** {category}")
        st.write(f"**Cropland:** {fmt_num(metrics.get('cropland_pct'), 1, '%')}")
        st.write(f"**Built-up land:** {fmt_num(metrics.get('built_pct'), 1, '%')}")

        st.markdown("### What this landscape looks like")
        for point in locate["context_points"]:
            st.write(f"• {point}")

        st.markdown("### Why this matters")
        st.write(locate["why_it_matters"])

        st.markdown("### Current land-cover composition")
        if not lc_df.empty:
            fig = build_landcover_bar(lc_df)
            st.plotly_chart(fig, use_container_width=True, key="overview_landcover_chart")
            st.caption("This chart shows how the selected area is currently divided across land-cover classes such as tree cover, cropland, built-up land, and water.")

    with tab3:
        st.markdown("## Evaluate")
        st.write("Current and historical environmental conditions have been reviewed using the dashboard indicators.")
        st.write(f"Current NDVI: {fmt_num(metrics.get('ndvi_current'), 3)}")
        st.write(f"Historical NDVI trend: {fmt_num(metrics.get('ndvi_trend'), 3)}")
        st.write(f"Rainfall anomaly: {fmt_num(metrics.get('rain_anom_pct'), 1, '%')}")
        st.write(f"Recent LST mean: {fmt_num(metrics.get('lst_mean'), 1, ' °C')}")
        st.write(f"Forest loss % of baseline forest: {fmt_num(metrics.get('forest_loss_pct'), 1, '%')}")

    with tab4:
        st.markdown("## Assess")
        st.write("The dashboard interprets the evidence into a business-facing nature risk signal and identifies the most relevant issues.")
        st.write(f"Nature risk score: {risk['score']} / 100")
        st.write(f"Risk band: {risk['band']}")
        if risk["flags"]:
            for flag in risk["flags"]:
                st.write(f"• {flag}")
        else:
            st.write("• No major automated flags triggered in the current rule set.")

    with tab5:
        st.markdown("## Prepare")
        st.write("The dashboard provides category-specific next actions based on the current signals and business context.")
        for rec in risk["recs"]:
            st.write(f"• {rec}")

    with tab6:
        st.markdown("## Image outputs")
        st.write("**NDVI image:** greener usually means stronger vegetation; redder usually means weaker vegetation.")
        st.write("**Vegetation change map:** green usually means improvement; red usually means decline.")
        st.write("**Land-cover image:** colours represent classes such as tree cover, cropland, built-up land, and water.")
        st.write("**Forest loss map:** highlighted areas show detected forest loss.")

        img1, img2 = st.columns(2)
        with img1:
            st.image(satellite_url, caption="Satellite image with polygon", use_container_width=True)
            st.image(ndvi_url, caption="NDVI image with polygon", use_container_width=True)
            st.image(veg_change_url, caption="Vegetation change map with polygon", use_container_width=True)
        with img2:
            st.image(landcover_url, caption="Land-cover image with polygon", use_container_width=True)
            st.image(forest_loss_url, caption="Forest loss map with polygon", use_container_width=True)

    with tab7:
        st.markdown("## Historical plots")

        if not ndvi_hist_df.empty:
            fig = px.line(ndvi_hist_df, x="year", y="value", title="Historical NDVI (Landsat)")
            st.plotly_chart(fig, use_container_width=True, key="trend_ndvi_chart")
        if not rain_hist_df.empty:
            fig = px.line(rain_hist_df, x="year", y="value", title="Historical Rainfall (CHIRPS)")
            st.plotly_chart(fig, use_container_width=True, key="trend_rain_chart")
        if not lst_hist_df.empty:
            fig = px.line(lst_hist_df, x="year", y="value", title="Historical Land Surface Temperature (MODIS)")
            st.plotly_chart(fig, use_container_width=True, key="trend_lst_chart")
        if not forest_hist_df.empty:
            fig = px.bar(forest_hist_df, x="year", y="value", title="Historical Forest Loss by Year (Hansen)")
            st.plotly_chart(fig, use_container_width=True, key="trend_forest_chart")
        if not water_hist_df.empty:
            fig = px.line(water_hist_df, x="year", y="value", title="Historical Water Presence (JRC)")
            st.plotly_chart(fig, use_container_width=True, key="trend_water_chart")

    with tab8:
        st.markdown("## Detailed results")

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

        if not lc_df.empty:
            fig = build_landcover_bar(lc_df)
            st.plotly_chart(fig, use_container_width=True, key="details_landcover_chart")
