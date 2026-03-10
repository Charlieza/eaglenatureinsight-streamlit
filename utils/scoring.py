def build_risk_and_recommendations(preset: str, category: str, metrics: dict) -> dict:
    score = 0
    flags = []
    recs = []

    def add_flag(condition, pts, flag_text, rec_text):
        nonlocal score
        if condition:
            score += pts
            flags.append(flag_text)
            recs.append(rec_text)

    ndvi_current = metrics.get("ndvi_current")
    ndvi_trend = metrics.get("ndvi_trend")
    rain_anom_pct = metrics.get("rain_anom_pct")
    forest_loss_pct = metrics.get("forest_loss_pct")
    tree_pct = metrics.get("tree_pct")
    built_pct = metrics.get("built_pct")
    lst_mean = metrics.get("lst_mean")
    water_occ = metrics.get("water_occ")
    bio_proxy = metrics.get("bio_proxy")

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

    if category == "Agriculture / Agribusiness":
        add_flag(
            tree_pct is not None and tree_pct < 10,
            10,
            "Tree cover is limited for an agricultural landscape.",
            "Consider shade trees, windbreaks, or agroforestry to improve resilience and reduce exposure."
        )
        recs.extend([
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
        recs.extend([
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
        recs.extend([
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
        recs.extend([
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
        recs.extend([
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
        recs.extend([
            "Use the outputs to identify where greening could make the biggest visible difference.",
            "Focus on areas where high heat and low vegetation occur together.",
            "Use the land-cover results to support simple site improvement planning.",
        ])

    else:
        recs.extend([
            "Use this dashboard as a first screening tool to spot possible environmental risks and opportunities.",
            "Pay attention to places showing low vegetation, high heat, or visible land-cover change.",
            "Use flagged areas as a starting point for follow-up review or action.",
        ])

    if preset == "Panuka AgriBiz Hub":
        recs.extend([
            "Use these outputs to support business support, incubation, and investment-readiness discussions.",
            "Link site condition findings to resilience planning and practical support for agribusiness users.",
        ])

    if preset == "BL Turner Group":
        recs.extend([
            "Use these outputs to support water, greening, and site rehabilitation priorities.",
            "Link the findings to practical environmental improvement actions that strengthen the business case.",
        ])

    unique_recs = []
    seen = set()
    for rec in recs:
        if rec not in seen:
            unique_recs.append(rec)
            seen.add(rec)

    score = min(score, 100)
    band = "Low"
    if score >= 60:
        band = "High"
    elif score >= 30:
        band = "Moderate"

    return {
        "score": score,
        "band": band,
        "flags": flags,
        "recs": unique_recs[:8],
    }
