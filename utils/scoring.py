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
        "Current vegetation condition is low.",
        "Prioritise restoration or greening in the lowest-vegetation zones."
    )

    add_flag(
        ndvi_trend is not None and ndvi_trend < -0.03,
        15,
        "Historical vegetation trend is declining.",
        "Investigate whether land-use pressure, water stress, or operational practices are driving vegetation decline."
    )

    add_flag(
        rain_anom_pct is not None and rain_anom_pct < -10,
        12,
        "Recent rainfall is below long-term baseline.",
        "Strengthen climate resilience and water-efficiency planning."
    )

    add_flag(
        forest_loss_pct is not None and forest_loss_pct > 5,
        15,
        "Forest loss has been detected within the assessed landscape.",
        "Avoid further encroachment into tree-covered areas and consider restoration buffers."
    )

    if category == "Agriculture / Agribusiness":
        add_flag(
            tree_pct is not None and tree_pct < 10,
            10,
            "Tree cover is limited for an agribusiness landscape.",
            "Consider agroforestry, shade planting, or shelterbelt interventions to improve resilience."
        )
        recs.extend([
            "Use the dashboard to monitor vegetation condition seasonally across production areas.",
            "Review whether water access and rainfall variability could affect productivity or climate resilience.",
            "Prioritise land parcels with declining vegetation for field verification and soil-health review.",
        ])

    elif category == "Food processing / Supply chain":
        add_flag(
            rain_anom_pct is not None and rain_anom_pct < -10,
            8,
            "Climate variability may affect upstream agricultural supply areas.",
            "Engage suppliers on climate resilience, sourcing stability, and land stewardship practices."
        )
        recs.extend([
            "Map priority sourcing landscapes to identify potential supply-chain nature risks.",
            "Use vegetation and land-cover change signals as early-warning indicators for supplier stress.",
            "Consider nature-related sourcing criteria in supplier engagement.",
        ])

    elif category == "Manufacturing / Industrial":
        add_flag(
            built_pct is not None and built_pct > 30,
            10,
            "The site is highly built-up.",
            "Explore green buffers, site greening, and land rehabilitation options where feasible."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "Land surface temperature is elevated.",
            "Target heat-reduction measures such as shading, reflective surfaces, and cooling vegetation."
        )
        recs.extend([
            "Review opportunities for green infrastructure around operational areas.",
            "Assess whether heat and low vegetation may affect worker comfort, site resilience, or compliance.",
            "Track surrounding land-use change as part of environmental risk screening.",
        ])

    elif category == "Water / Circular economy":
        add_flag(
            water_occ is not None and water_occ < 5,
            15,
            "Surface-water context appears limited.",
            "Strengthen water security planning and review reuse, storage, and alternative water sources."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            10,
            "Elevated land surface temperature may increase water stress.",
            "Treat water efficiency and site cooling measures as linked resilience priorities."
        )
        recs.extend([
            "Use water and vegetation indicators together to track local water-stress context.",
            "Prioritise interventions that improve local water efficiency and ecological condition together.",
            "Review opportunities for circular water use and site greening.",
        ])

    elif category == "Energy / Infrastructure":
        add_flag(
            built_pct is not None and built_pct > 25,
            10,
            "Infrastructure footprint may increase local environmental pressure.",
            "Assess whether buffers, greening, or habitat-sensitive siting measures can reduce impact."
        )
        add_flag(
            bio_proxy is not None and bio_proxy > 10,
            12,
            "Ecological context may be sensitive.",
            "Apply greater caution for expansion or disturbance in environmentally sensitive areas."
        )
        recs.extend([
            "Use the site boundary and surrounding land-cover context to support screening before expansion.",
            "Prioritise avoidance and minimisation where sensitive habitats or vegetation loss are visible.",
            "Track local heat, vegetation, and land-cover change around infrastructure assets.",
        ])

    elif category == "Property / Built environment":
        add_flag(
            built_pct is not None and built_pct > 35,
            12,
            "Built-up intensity is high.",
            "Identify opportunities for tree planting, shading, and permeable or green surfaces."
        )
        add_flag(
            lst_mean is not None and lst_mean > 30,
            15,
            "Urban heat conditions appear elevated.",
            "Prioritise heat mitigation through vegetation, material choices, and site design improvements."
        )
        recs.extend([
            "Use the dashboard to identify where greening interventions could have the most visible effect.",
            "Review whether low vegetation and high heat coincide with built-up zones needing retrofit.",
            "Use the land-cover view to support site planning discussions.",
        ])

    else:
        recs.extend([
            "Use the dashboard as a screening tool to identify where nature-related conditions may need closer review.",
            "Track changes in vegetation, land cover, water context, and forest loss over time.",
            "Prioritise any flagged areas for internal review or external specialist follow-up if needed.",
        ])

    if preset == "Panuka AgriBiz Hub":
        recs.extend([
            "Use this output to support agribusiness incubation, training, and investment-readiness discussions.",
            "Consider linking site-level environmental signals to enterprise support, resilience planning, and financial inclusion narratives.",
        ])

    if preset == "BL Turner Group":
        recs.extend([
            "Use this output to prioritise water, greening, and site rehabilitation opportunities.",
            "Consider integrating environmental restoration and cooling measures into the sustainability value proposition.",
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
