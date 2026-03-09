import streamlit as st

st.set_page_config(
    page_title="EagleNatureInsight",
    layout="wide"
)

st.title("EagleNatureInsight™")
st.subheader("Nature Intelligence Dashboard for SMEs")

st.markdown("### LEAP Process")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.info("**Locate**\n\nDefine the site and assessment area.")
with c2:
    st.info("**Evaluate**\n\nReview current and historical environmental conditions.")
with c3:
    st.info("**Assess**\n\nInterpret nature-related risks and opportunities.")
with c4:
    st.info("**Prepare**\n\nTranslate findings into practical actions.")

st.markdown("---")

preset = st.selectbox(
    "Select Business / Area",
    ["Select Business / Area", "Panuka AgriBiz Hub", "BL Turner Group"]
)

category = st.selectbox(
    "Business Category",
    [
        "Agriculture / Agribusiness",
        "Food processing / Supply chain",
        "Manufacturing / Industrial",
        "Water / Circular economy",
        "Energy / Infrastructure",
        "Property / Built environment",
        "General SME"
    ]
)

st.write("Selected preset:", preset)
st.write("Selected category:", category)

if st.button("Run Assessment"):
    st.success("Dashboard shell is working. Next step is to connect Earth Engine.")
