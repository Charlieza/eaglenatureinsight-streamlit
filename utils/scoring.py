def build_risk_and_recommendations(preset: str, category: str, metrics: dict) -> dict:
    score = 0
    flags = []
    streamlit_recs = []
    ee_recs = []

    def add_flag(condition, pts, flag_text, rec_text):
        nonlocal score
        if condition:
            score += pts
            flags.append(flag_text)
            streamlit_recs.append(rec_text)

    ndvi_current = metrics.get("ndvi_current")
    ndvi_trend = metrics.get("ndvi_trend")
    rain_anom_pct = metrics.get("rain_anom_pct")
    forest_loss_pct = metrics.get("forest_loss_pct")
    tree_pct = metrics.get("tree_pct")
    built_pct = metrics.get("built_pct")
    lst_mean = metrics.get("lst_mean")
    water_occ = metrics.get("water_occ")
    bio_proxy = metrics.get("bio_proxy")

    # -------------------------------------------------
    # Shared Streamlit risk logic
    # -------------------------------------------------
    add_flag(
        ndvi_current is not None and ndvi_current < 0.25,
        15,
        "Vegetation cover looks weak in the selected area.",
        "Look at low-vegetation parts of the site for possible greening, restoration, or better land management."
    )

    add_flag(
        ndvi_trend is not None and ndvi_trend < -0.03,
        15,
        "Vegetation condition has been getting worse over time.",
        "Check whether this decline may be linked to land pressure, poor drainage, overuse, or lack of site maintenance."
    )

    add_flag(
        rain_anom_pct is not None and rain_anom_pct < -10,
        12,
        "Recent rainfall is below the long-term average.",
        "Plan for water stress by improving water efficiency, storage, and drought readiness."
    )

    add_flag(
        forest_loss_pct is not None and forest_loss_pct > 5,
        15,
        "Tree loss has been detected in the surrounding landscape.",
        "Avoid further disturbance in tree-covered areas and consider planting or restoring buffer zones."
    )

    # -------------------------------------------------
    # Streamlit category logic
    # -------------------------------------------------
    if category == "Agriculture / Agribusiness":
        add_flag(
            tree_pct is not None and tree_pct < 10,
            10,
            "Tree cover is limited for an agricultural landscape.",
            "Consider shade trees, windbreaks, or agroforestry to improve resilience and reduce exposure."
        )
        streamlit_recs.extend([
            "Use the vegetation maps to spot fields or sites that may need attention first.",
            "Review whether low rainfall or weak vegetation could affect production or crop reliability.",
            "Use tree planting or shelterbelts where practical to improve resilience over time.",
        ])

    elif category == "Food processing / Supply chain":
        add_flag(
            rain_anom_pct is not None and rain_anom_pct < -10,
            8,
            "Dry conditions may affect upstream supplier areas.",
            "Review whether climate stress in sourcing areas could affect supply reliability."
        )
        streamlit_recs.extend([
            "Use this screening to identify supplier areas that may face environmental pressure.",
            "Use vegetation and land-cover change as an early warning signal for supply chain stress.",
            "Consider adding simple nature-related checks into supplier engagement.",
        ])

    elif category == "Manufacturing / Industrial":
        add_flag(
            built_pct is not None and built_pct > 30,
            10,
            "A large share of the site is built-up.",
            "Look for practical opportunities for greening, shading, or improved site design."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "Surface temperatures are high.",
            "Prioritise heat reduction through shade, trees, reflective materials, and cooler surfaces."
        )
        streamlit_recs.extend([
            "Use the site outputs to identify where greening can improve comfort and resilience.",
            "Check whether heat and low vegetation overlap with key work or storage areas.",
            "Track land-cover and heat patterns around the site over time.",
        ])

    elif category == "Water / Circular economy":
        add_flag(
            water_occ is not None and water_occ < 5,
            15,
            "There is little visible surface water in the surrounding area.",
            "Strengthen water planning through reuse, storage, efficiency, and backup options."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            10,
            "High land temperatures may increase water pressure.",
            "Treat heat reduction and water efficiency as linked site priorities."
        )
        streamlit_recs.extend([
            "Use the water and vegetation outputs together to understand local water stress.",
            "Look at greening options that also support cooling and site condition.",
            "Review water reuse, storage, and circular water opportunities where practical.",
        ])

    elif category == "Energy / Infrastructure":
        add_flag(
            built_pct is not None and built_pct > 25,
            10,
            "Infrastructure footprint may be putting pressure on the surrounding environment.",
            "Review whether buffers, greening, or better siting can reduce local impact."
        )
        add_flag(
            bio_proxy is not None and bio_proxy > 10,
            12,
            "The surrounding ecological setting may be sensitive.",
            "Use extra caution when planning expansion or disturbance in the area."
        )
        streamlit_recs.extend([
            "Use the maps to support early screening before expansion or new site activity.",
            "Prioritise avoiding sensitive areas where possible.",
            "Track land-cover, vegetation, and heat around infrastructure assets over time.",
        ])

    elif category == "Property / Built environment":
        add_flag(
            built_pct is not None and built_pct > 35,
            12,
            "The site is heavily built-up.",
            "Look for opportunities for trees, shade, and cooler surfaces."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "The site shows signs of high heat exposure.",
            "Use greening and site design changes to reduce heat where possible."
        )
        streamlit_recs.extend([
            "Use the outputs to identify where greening could make the biggest visible difference.",
            "Focus on areas where high heat and low vegetation occur together.",
            "Use the land-cover results to support simple site improvement planning.",
        ])

    else:
        streamlit_recs.extend([
            "Use this dashboard as a first screening tool to spot possible environmental risks and opportunities.",
            "Pay attention to places showing low vegetation, high heat, or visible land-cover change.",
            "Use flagged areas as a starting point for follow-up review or action.",
        ])

    # -------------------------------------------------
    # Streamlit preset-specific logic
    # -------------------------------------------------
    if preset == "Panuka AgriBiz Hub":
        streamlit_recs.extend([
            "Use these outputs to support business support, incubation, and investment-readiness discussions.",
            "Link site condition findings to resilience planning and practical support for agribusiness users.",
        ])

    if preset == "BL Turner Group":
        streamlit_recs.extend([
            "Use these outputs to support water, greening, and site rehabilitation priorities.",
            "Link the findings to practical environmental improvement actions that strengthen the business case.",
        ])

    # -------------------------------------------------
    # Earth Engine recommendation logic
    # Keeps Streamlit recommendations and adds these too.
    # -------------------------------------------------
    def add_ee_flag(condition, pts, flag_text, rec_text):
        nonlocal score
        if condition:
            score += pts
            if flag_text not in flags:
                flags.append(flag_text)
            ee_recs.append(rec_text)

    add_ee_flag(
        ndvi_current is not None and ndvi_current < 0.25,
        15,
        "Current vegetation condition is low.",
        "Prioritise restoration or greening in the lowest-vegetation zones."
    )

    add_ee_flag(
        ndvi_trend is not None and ndvi_trend < -0.03,
        15,
        "Historical vegetation trend is declining.",
        "Investigate whether land-use pressure, water stress, or operational practices are driving vegetation decline."
    )

    add_ee_flag(
        rain_anom_pct is not None and rain_anom_pct < -10,
        12,
        "Recent rainfall is below long-term baseline.",
        "Strengthen climate resilience and water-efficiency planning."
    )

    add_ee_flag(
        forest_loss_pct is not None and forest_loss_pct > 5,
        15,
        "Forest loss has been detected within the assessed landscape.",
        "Avoid further encroachment into tree-covered areas and consider restoration buffers."
    )

    if category == "Agriculture / Agribusiness":
        add_ee_flag(
            tree_pct is not None and tree_pct < 10,
            10,
            "Tree cover is limited for an agribusiness landscape.",
            "Consider agroforestry, shade planting, or shelterbelt interventions to improve resilience."
        )
        ee_recs.extend([
            "Use the dashboard to monitor vegetation condition seasonally across production areas.",
            "Review whether water access and rainfall variability could affect productivity or climate resilience.",
            "Prioritise land parcels with declining vegetation for field verification and soil-health review.",
        ])

    elif category == "Food processing / Supply chain":
        add_ee_flag(
            rain_anom_pct is not None and rain_anom_pct < -10,
            8,
            "Climate variability may affect upstream agricultural supply areas.",
            "Engage suppliers on climate resilience, sourcing stability, and land stewardship practices."
        )
        ee_recs.extend([
            "Map priority sourcing landscapes to identify potential supply-chain nature risks.",
            "Use vegetation and land-cover change signals as early-warning indicators for supplier stress.",
            "Consider nature-related sourcing criteria in supplier engagement.",
        ])

    elif category == "Manufacturing / Industrial":
        add_ee_flag(
            built_pct is not None and built_pct > 30,
            10,
            "The site is highly built-up.",
            "Explore green buffers, site greening, and land rehabilitation options where feasible."
        )
        add_ee_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "Land surface temperature is elevated.",
            "Target heat-reduction measures such as shading, reflective surfaces, and cooling vegetation."
        )
        ee_recs.extend([
            "Review opportunities for green infrastructure around operational areas.",
            "Assess whether heat and low vegetation may affect worker comfort, site resilience, or compliance.",
            "Track surrounding land-use change as part of environmental risk screening.",
        ])

    elif category == "Water / Circular economy":
        add_ee_flag(
            water_occ is not None and water_occ < 5,
            15,
            "Surface-water context appears limited.",
            "Strengthen water security planning and review reuse, storage, and alternative water sources."
        )
        add_ee_flag(
            lst_mean is not None and lst_mean > 30,
            10,
            "Elevated land surface temperature may increase water stress.",
            "Treat water efficiency and site cooling measures as linked resilience priorities."
        )
        ee_recs.extend([
            "Use water and vegetation indicators together to track local water-stress context.",
            "Prioritise interventions that improve local water efficiency and ecological condition together.",
            "Review opportunities for circular water use and site greening.",
        ])

    elif category == "Energy / Infrastructure":
        add_ee_flag(
            built_pct is not None and built_pct > 25,
            10,
            "Infrastructure footprint may increase local environmental pressure.",
            "Assess whether buffers, greening, or habitat-sensitive siting measures can reduce impact."
        )
        add_ee_flag(
            bio_proxy is not None and bio_proxy > 10,
            12,
            "Ecological context may be sensitive.",
            "Apply greater caution for expansion or disturbance in environmentally sensitive areas."
        )
        ee_recs.extend([
            "Use the site boundary and surrounding land-cover context to support screening before expansion.",
            "Prioritise avoidance and minimisation where sensitive habitats or vegetation loss are visible.",
            "Track local heat, vegetation, and land-cover change around infrastructure assets.",
        ])

    elif category == "Property / Built environment":
        add_ee_flag(
            built_pct is not None and built_pct > 35,
            12,
            "Built-up intensity is high.",
            "Identify opportunities for tree planting, shading, and permeable or green surfaces."
        )
        add_ee_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "Urban heat conditions appear elevated.",
            "Prioritise heat mitigation through vegetation, material choices, and site design improvements."
        )
        ee_recs.extend([
            "Use the dashboard to identify where greening interventions could have the most visible effect.",
            "Review whether low vegetation and high heat coincide with built-up zones needing retrofit.",
            "Use the land-cover view to support site planning discussions.",
        ])

    else:
        ee_recs.extend([
            "Use the dashboard as a screening tool to identify where nature-related conditions may need closer review.",
            "Track changes in vegetation, land cover, water context, and forest loss over time.",
            "Prioritise any flagged areas for internal review or external specialist follow-up if needed.",
        ])

    if preset == "Panuka AgriBiz Hub":
        ee_recs.extend([
            "Use this output to support agribusiness incubation, training, and investment-readiness discussions.",
            "Consider linking site-level environmental signals to enterprise support, resilience planning, and financial inclusion narratives.",
        ])

    if preset == "BL Turner Group":
        ee_recs.extend([
            "Use this output to prioritise water, greening, and site rehabilitation opportunities.",
            "Consider integrating environmental restoration and cooling measures into the sustainability value proposition.",
        ])

    # -------------------------------------------------
    # Merge and de-duplicate recommendations
    # -------------------------------------------------
    combined_recs = []
    seen = set()

    for rec in streamlit_recs + ee_recs:
        if rec and rec not in seen:
            combined_recs.append(rec)
            seen.add(rec)

    # De-duplicate flags while preserving order
    unique_flags = []
    seen_flags = set()
    for flag in flags:
        if flag and flag not in seen_flags:
            unique_flags.append(flag)
            seen_flags.add(flag)

    score = min(score, 100)
    band = "Low"
    if score >= 60:
        band = "High"
    elif score >= 30:
        band = "Moderate"

    return {
        "score": score,
        "band": band,
        "flags": unique_flags,
        "recs": combined_recs[:12],
    }
