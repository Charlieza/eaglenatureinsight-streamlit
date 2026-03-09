import json
from pathlib import Path

import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium

st.set_page_config(
    page_title="EagleNatureInsight",
    layout="wide"
)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
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

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def init_state() -> None:
    defaults = {
        "preset_selector": "Select Business / Area",
        "category_selector": "General SME",
        "lat_input": "",
        "lon_input": "",
        "buffer_input": 1000,
        "map_center": [-25.0, 24.0],
        "map_zoom": 5,
        "draw_mode": "Draw polygon",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_preset(preset: str) -> None:
    if preset in PRESET_TO_CATEGORY:
        st.session_state.category_selector = PRESET_TO_CATEGORY[preset]

    if preset in PRESET_TO_LOCATION:
        loc = PRESET_TO_LOCATION[preset]
        st.session_state.lat_input = str(loc["lat"])
        st.session_state.lon_input = str(loc["lon"])
        st.session_state.buffer_input = int(loc["buffer_m"])
        st.session_state.map_center = [loc["lat"], loc["lon"]]
        st.session_state.map_zoom = loc["zoom"]


def preset_changed() -> None:
    preset = st.session_state.preset_selector
    if preset != "Select Business / Area":
        apply_preset(preset)


def build_map(center: list[float], zoom: int) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, control_scale=True, tiles="OpenStreetMap")

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

    # Use the most recent drawing
    return drawings[-1]


def get_geometry_summary(drawn_geojson: dict | None, lat: str, lon: str, buffer_m: int, mode: str) -> tuple[str, dict | None]:
    if mode == "Draw polygon":
        if drawn_geojson:
            return "Polygon captured from map drawing.", drawn_geojson
        return "No polygon drawn yet.", None

    # Enter coordinates mode
    try:
        lat_val = float(lat)
        lon_val = float(lon)
        return f"Point entered at ({lat_val:.5f}, {lon_val:.5f}) with {buffer_m} m buffer.", {
            "type": "PointBuffer",
            "lat": lat_val,
            "lon": lon_val,
            "buffer_m": buffer_m,
        }
    except (TypeError, ValueError):
        return "Please enter valid latitude and longitude.", None


# --------------------------------------------------
# INIT
# --------------------------------------------------
init_state()

# --------------------------------------------------
# HEADER
# --------------------------------------------------
header_left, header_right = st.columns([2, 6])

with header_left:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)

with header_right:
    st.title("EagleNatureInsight™")
    st.caption("Nature Intelligence Dashboard for SMEs")
    st.markdown("**Locate • Evaluate • Assess • Prepare**")

st.markdown("---")

# --------------------------------------------------
# LEAP OVERVIEW
# --------------------------------------------------
st.markdown("### LEAP Process")
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.info("**Locate**\n\nDefine the business site or assessment area.")
with c2:
    st.info("**Evaluate**\n\nReview current and historical environmental conditions.")
with c3:
    st.info("**Assess**\n\nInterpret nature-related risks and opportunities.")
with c4:
    st.info("**Prepare**\n\nTurn findings into practical next actions.")

st.markdown("---")

# --------------------------------------------------
# CONTROLS
# --------------------------------------------------
left_col, right_col = st.columns([1, 1])

with left_col:
    st.selectbox(
        "Select Business / Area",
        PRESETS,
        key="preset_selector",
        on_change=preset_changed,
    )

with right_col:
    st.selectbox(
        "Business Category",
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

# --------------------------------------------------
# MAP
# --------------------------------------------------
st.markdown("### Site Selection")

map_center = st.session_state.map_center
map_zoom = st.session_state.map_zoom
m = build_map(map_center, map_zoom)

map_data = st_folium(
    m,
    width=None,
    height=520,
    returned_objects=["all_drawings", "last_object_clicked"],
    key="eaglenatureinsight_map",
)

drawn_geojson = extract_drawn_geometry(map_data)

summary_text, geometry_payload = get_geometry_summary(
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

# --------------------------------------------------
# CURRENT STATE SUMMARY
# --------------------------------------------------
st.markdown("### Current Dashboard State")
sum1, sum2, sum3 = st.columns(3)

with sum1:
    st.metric("Preset", st.session_state.preset_selector)

with sum2:
    st.metric("Category", st.session_state.category_selector)

with sum3:
    st.metric("Mode", st.session_state.draw_mode)

# --------------------------------------------------
# ACTION
# --------------------------------------------------
if st.button("Run Assessment", use_container_width=True):
    if geometry_payload is None:
        st.warning("Please draw a polygon or enter valid coordinates first.")
    else:
        st.success("Assessment shell is working. Next step is to connect Earth Engine and the scoring logic.")

        st.markdown("### Assessment Preview")
        a1, a2, a3 = st.columns(3)
        with a1:
            st.metric("Nature Risk", "Pending")
        with a2:
            st.metric("Current NDVI", "Pending")
        with a3:
            st.metric("Rainfall Anomaly", "Pending")

        st.markdown("### LEAP Output Preview")

        st.markdown("**Locate**")
        st.write("The assessment area has been captured and is ready for screening.")

        st.markdown("**Evaluate**")
        st.write("Environmental indicators will be computed once Earth Engine is connected.")

        st.markdown("**Assess**")
        st.write("Category-specific risks and opportunities will be generated from the analysis.")

        st.markdown("**Prepare**")
        st.write("Multiple recommendations will be produced based on the selected business category and site conditions.")
