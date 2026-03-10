import json
import ee


def initialize_ee_from_secrets(st) -> None:
    if getattr(initialize_ee_from_secrets, "_initialized", False):
        return

    service_account_info = {
        "type": st.secrets["earthengine"]["type"],
        "project_id": st.secrets["earthengine"]["project_id"],
        "private_key_id": st.secrets["earthengine"]["private_key_id"],
        "private_key": st.secrets["earthengine"]["private_key"],
        "client_email": st.secrets["earthengine"]["client_email"],
        "client_id": st.secrets["earthengine"]["client_id"],
        "auth_uri": st.secrets["earthengine"]["auth_uri"],
        "token_uri": st.secrets["earthengine"]["token_uri"],
        "auth_provider_x509_cert_url": st.secrets["earthengine"]["auth_provider_x509_cert_url"],
        "client_x509_cert_url": st.secrets["earthengine"]["client_x509_cert_url"],
        "universe_domain": st.secrets["earthengine"]["universe_domain"],
    }

    credentials = ee.ServiceAccountCredentials(
        service_account_info["client_email"],
        key_data=json.dumps(service_account_info),
    )

    ee.Initialize(credentials)
    initialize_ee_from_secrets._initialized = True


def get_datasets():
    s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
    worldcover = ee.Image("ESA/WorldCover/v200/2021").select("Map")
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    gsw_yearly = ee.ImageCollection("JRC/GSW1_4/YearlyHistory")
    hansen = ee.Image("UMD/hansen/global_forest_change_2024_v1_12")
    modis_lst = ee.ImageCollection("MODIS/061/MOD11A2")

    lt05 = ee.ImageCollection("LANDSAT/LT05/C02/T1_L2")
    le07 = ee.ImageCollection("LANDSAT/LE07/C02/T1_L2")
    lc08 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
    lc09 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")

    bio_proxy = (
        ee.FeatureCollection("RESOLVE/ECOREGIONS/2017")
        .reduceToImage(properties=["BIOME_NUM"], reducer=ee.Reducer.first())
        .rename("bio_proxy")
    )

    return {
        "S2": s2,
        "CHIRPS": chirps,
        "WORLDCOVER": worldcover,
        "GSW": gsw,
        "GSW_YEARLY": gsw_yearly,
        "HANSEN": hansen,
        "MODIS_LST": modis_lst,
        "LT05": lt05,
        "LE07": le07,
        "LC08": lc08,
        "LC09": lc09,
        "BIO_PROXY": bio_proxy,
    }


def geojson_to_ee_geometry(geojson_obj: dict) -> ee.Geometry:
    geometry = geojson_obj.get("geometry", geojson_obj)
    return ee.Geometry(geometry)


def point_buffer_to_ee_geometry(lat: float, lon: float, buffer_m: float) -> ee.Geometry:
    return ee.Geometry.Point([lon, lat]).buffer(buffer_m)


def mask_s2_clouds(image: ee.Image) -> ee.Image:
    scl = image.select("SCL")
    mask = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )
    return image.updateMask(mask)


def current_sentinel_rgb(geom: ee.Geometry, last_full_year: int) -> ee.Image:
    ds = get_datasets()
    return (
        ds["S2"]
        .filterBounds(geom)
        .filterDate(f"{last_full_year}-01-01", f"{last_full_year}-12-31")
        .map(mask_s2_clouds)
        .median()
    )


def current_ndvi_image_and_mean(geom: ee.Geometry, last_full_year: int):
    img = current_sentinel_rgb(geom, last_full_year)
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    mean = ndvi.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom,
        scale=10,
        maxPixels=1e13
    ).get("NDVI")
    return ndvi, mean


def build_polygon_outline(geom: ee.Geometry) -> ee.Image:
    return ee.Image().byte().paint(
        ee.FeatureCollection([ee.Feature(geom)]), 1, 3
    ).visualize(palette=["#ff0000"])


def add_polygon_overlay(base_image: ee.Image, geom: ee.Geometry) -> ee.Image:
    return ee.ImageCollection([base_image, build_polygon_outline(geom)]).mosaic()


def satellite_with_polygon(geom: ee.Geometry, last_full_year: int) -> ee.Image:
    rgb = current_sentinel_rgb(geom, last_full_year).visualize(
        bands=["B4", "B3", "B2"],
        min=0,
        max=3000
    )
    return add_polygon_overlay(rgb, geom)


def ndvi_with_polygon(geom: ee.Geometry, last_full_year: int) -> ee.Image:
    ndvi, _ = current_ndvi_image_and_mean(geom, last_full_year)
    vis = ndvi.visualize(
        min=0,
        max=0.8,
        palette=["#d73027", "#fee08b", "#1a9850"]
    )
    return add_polygon_overlay(vis, geom)


def landcover_with_polygon(geom: ee.Geometry) -> ee.Image:
    ds = get_datasets()
    vis = ds["WORLDCOVER"].visualize(
        min=10,
        max=100,
        palette=[
            "#006400", "#ffbb22", "#ffff4c", "#f096ff", "#fa0000",
            "#b4b4b4", "#f0f0f0", "#0064c8", "#0096a0", "#00cf75"
        ]
    )
    return add_polygon_overlay(vis, geom)


def forest_loss_with_polygon(geom: ee.Geometry) -> ee.Image:
    ds = get_datasets()
    vis = ds["HANSEN"].select("lossyear").gt(0).selfMask().visualize(
        palette=["#dc2626"]
    )
    return add_polygon_overlay(vis, geom)


def vegetation_change_with_polygon(geom: ee.Geometry, hist_start: int, hist_end: int) -> ee.Image:
    ds = get_datasets()
    start_year = max(hist_start, 2016)
    end_year = hist_end

    early_end_year = min(start_year + 1, end_year)
    late_start_year = max(end_year - 1, start_year)

    early = (
        ds["S2"]
        .filterBounds(geom)
        .filterDate(f"{start_year}-01-01", f"{early_end_year}-12-31")
        .map(mask_s2_clouds)
        .median()
        .normalizedDifference(["B8", "B4"])
        .rename("NDVI")
    )

    late = (
        ds["S2"]
        .filterBounds(geom)
        .filterDate(f"{late_start_year}-01-01", f"{end_year}-12-31")
        .map(mask_s2_clouds)
        .median()
        .normalizedDifference(["B8", "B4"])
        .rename("NDVI")
    )

    change = late.subtract(early).rename("NDVI_change")

    vis = change.visualize(
        min=-0.4,
        max=0.4,
        palette=[
            "#8b0000",
            "#d73027",
            "#f46d43",
            "#fdae61",
            "#ffffbf",
            "#a6d96a",
            "#66bd63",
            "#1a9850"
        ]
    )

    return add_polygon_overlay(vis, geom)


def image_thumb_url(image: ee.Image, geom: ee.Geometry, dimensions: int = 1200) -> str:
    return image.getThumbURL({
        "region": geom.bounds(),
        "dimensions": dimensions,
        "format": "png"
    })


def prep_l57(img: ee.Image) -> ee.Image:
    qa = img.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))

    sr = img.select(["SR_B3", "SR_B4"], ["RED", "NIR"]) \
        .multiply(0.0000275) \
        .add(-0.2)

    return sr.updateMask(mask).copyProperties(img, img.propertyNames())


def prep_l89(img: ee.Image) -> ee.Image:
    qa = img.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))

    sr = img.select(["SR_B4", "SR_B5"], ["RED", "NIR"]) \
        .multiply(0.0000275) \
        .add(-0.2)

    return sr.updateMask(mask).copyProperties(img, img.propertyNames())


def landsat_annual_ndvi_collection(geom: ee.Geometry, start_year: int, end_year: int) -> ee.FeatureCollection:
    ds = get_datasets()
    years = ee.List.sequence(start_year, end_year)

    def per_year(y):
        y = ee.Number(y)
        start = ee.Date.fromYMD(y, 1, 1)
        end = ee.Date.fromYMD(y, 12, 31)

        l5 = ds["LT05"].filterBounds(geom).filterDate(start, end).map(prep_l57)
        l7 = ds["LE07"].filterBounds(geom).filterDate(start, end).map(prep_l57)
        l8 = ds["LC08"].filterBounds(geom).filterDate(start, end).map(prep_l89)
        l9 = ds["LC09"].filterBounds(geom).filterDate(start, end).map(prep_l89)

        merged = l5.merge(l7).merge(l8).merge(l9)
        count = merged.size()

        mean_val = ee.Algorithms.If(
            count.gt(0),
            merged.median()
            .normalizedDifference(["NIR", "RED"])
            .rename("NDVI")
            .reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geom,
                scale=30,
                maxPixels=1e13
            ).get("NDVI"),
            None
        )

        return ee.Feature(None, {"year": y, "value": mean_val, "metric": "ndvi"})

    return ee.FeatureCollection(years.map(per_year))


def annual_rain_collection(geom: ee.Geometry, start_year: int, end_year: int) -> ee.FeatureCollection:
    ds = get_datasets()
    years = ee.List.sequence(start_year, end_year)

    def per_year(y):
        y = ee.Number(y)
        annual = (
            ds["CHIRPS"]
            .filterBounds(geom)
            .filterDate(ee.Date.fromYMD(y, 1, 1), ee.Date.fromYMD(y, 12, 31))
            .select("precipitation")
            .sum()
        )

        mean = annual.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=5566,
            maxPixels=1e13
        ).get("precipitation")

        return ee.Feature(None, {
            "year": y,
            "value": ee.Algorithms.If(mean, mean, None),
            "metric": "rain_mm"
        })

    return ee.FeatureCollection(years.map(per_year))


def annual_lst_collection(geom: ee.Geometry, start_year: int, end_year: int) -> ee.FeatureCollection:
    ds = get_datasets()
    years = ee.List.sequence(start_year, end_year)

    def per_year(y):
        y = ee.Number(y)
        annual = (
            ds["MODIS_LST"]
            .filterBounds(geom)
            .filterDate(ee.Date.fromYMD(y, 1, 1), ee.Date.fromYMD(y, 12, 31))
            .select("LST_Day_1km")
            .mean()
            .multiply(0.02)
            .subtract(273.15)
            .rename("LST_C")
        )

        mean = annual.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=1000,
            maxPixels=1e13
        ).get("LST_C")

        return ee.Feature(None, {
            "year": y,
            "value": ee.Algorithms.If(mean, mean, None),
            "metric": "lst_c"
        })

    return ee.FeatureCollection(years.map(per_year))


def forest_loss_by_year_collection(geom: ee.Geometry, start_year: int, end_year: int) -> ee.FeatureCollection:
    ds = get_datasets()
    s = max(start_year, 2001)
    e = min(end_year, 2024)
    years = ee.List.sequence(s, e)
    area_ha = ee.Image.pixelArea().divide(10000)
    loss_year = ds["HANSEN"].select("lossyear")

    def per_year(y):
        y = ee.Number(y)
        code = y.subtract(2000)
        loss_mask = loss_year.eq(code)

        loss_ha = area_ha.updateMask(loss_mask).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geom,
            scale=30,
            maxPixels=1e13
        ).get("area")

        return ee.Feature(None, {
            "year": y,
            "value": ee.Algorithms.If(loss_ha, loss_ha, 0),
            "metric": "forest_loss_ha"
        })

    return ee.FeatureCollection(years.map(per_year))


def water_history_collection(geom: ee.Geometry, start_year: int, end_year: int) -> ee.FeatureCollection:
    ds = get_datasets()
    coll = (
        ds["GSW_YEARLY"]
        .filterBounds(geom)
        .filterDate(ee.Date.fromYMD(start_year, 1, 1), ee.Date.fromYMD(end_year, 12, 31))
    )

    def per_img(img):
        year = ee.Date(img.get("system:time_start")).get("year")
        water_mask = img.select("waterClass").gte(2)

        water_pct = water_mask.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=30,
            maxPixels=1e13
        ).get("waterClass")

        safe_val = ee.Algorithms.If(water_pct, ee.Number(water_pct).multiply(100), None)

        return ee.Feature(None, {
            "year": year,
            "value": safe_val,
            "metric": "water_pct"
        })

    return ee.FeatureCollection(coll.map(per_img))


def landcover_pct(geom: ee.Geometry, cls: int):
    ds = get_datasets()
    total_area = ee.Number(
        ee.Image.pixelArea().reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geom,
            scale=10,
            maxPixels=1e13
        ).get("area")
    )

    class_area = ee.Number(
        ee.Image.pixelArea().updateMask(ds["WORLDCOVER"].eq(cls)).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geom,
            scale=10,
            maxPixels=1e13
        ).get("area")
    )

    return class_area.divide(total_area).multiply(100)


def landcover_feature_collection(geom: ee.Geometry) -> ee.FeatureCollection:
    ds = get_datasets()
    classes = [10, 20, 30, 40, 50, 60, 80, 90, 95, 100]
    class_names = {
        10: "Tree cover",
        20: "Shrubland",
        30: "Grassland",
        40: "Cropland",
        50: "Built-up",
        60: "Bare/sparse vegetation",
        80: "Permanent water",
        90: "Herbaceous wetland",
        95: "Mangroves",
        100: "Moss & lichen",
    }

    area_image = ee.Image.pixelArea().divide(10000)

    def per_class(cls):
        cls = ee.Number(cls)
        area = area_image.updateMask(ds["WORLDCOVER"].eq(cls)).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geom,
            scale=10,
            maxPixels=1e13
        ).get("area")

        return ee.Feature(None, {
            "class_value": cls,
            "class_name": class_names[int(cls.getInfo())],
            "area_ha": area
        })

    features = [per_class(cls) for cls in classes]
    return ee.FeatureCollection(features)


def forest_loss_summary(geom: ee.Geometry):
    ds = get_datasets()
    area_ha = ee.Image.pixelArea().divide(10000)
    tree2000 = ds["HANSEN"].select("treecover2000")
    forest_mask = tree2000.gte(30)

    forest_ha = area_ha.updateMask(forest_mask).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=geom,
        scale=30,
        maxPixels=1e13
    ).get("area")

    loss_mask = ds["HANSEN"].select("lossyear").gt(0)
    loss_ha = area_ha.updateMask(forest_mask.And(loss_mask)).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=geom,
        scale=30,
        maxPixels=1e13
    ).get("area")

    loss_pct = ee.Number(loss_ha).divide(ee.Number(forest_ha)).multiply(100)
    return {"forest_ha": forest_ha, "loss_ha": loss_ha, "loss_pct": loss_pct}


def surface_water_occurrence_mean(geom: ee.Geometry):
    ds = get_datasets()
    return ds["GSW"].reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom,
        scale=30,
        maxPixels=1e13
    ).get("occurrence")


def bio_proxy_mean(geom: ee.Geometry):
    ds = get_datasets()
    return ds["BIO_PROXY"].reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom,
        scale=250,
        maxPixels=1e13
    ).get("bio_proxy")


def series_recent_vs_early_delta(fc: ee.FeatureCollection):
    sorted_fc = ee.FeatureCollection(fc).sort("year").filter(ee.Filter.notNull(["value"]))
    count = ee.Number(sorted_fc.size())

    return ee.Algorithms.If(
        count.gte(6),
        ee.Number(ee.FeatureCollection(sorted_fc.toList(3, count.subtract(3))).aggregate_mean("value"))
        .subtract(ee.Number(ee.FeatureCollection(sorted_fc.toList(3, 0)).aggregate_mean("value"))),
        None
    )


def rainfall_anomaly_pct_from_range(geom: ee.Geometry, hist_start: int, hist_end: int):
    baseline = annual_rain_collection(geom, 1981, 2010)
    recent = annual_rain_collection(geom, max(hist_end - 2, hist_start), hist_end)
    baseline_mean = ee.Number(baseline.aggregate_mean("value"))
    recent_mean = ee.Number(recent.aggregate_mean("value"))
    return recent_mean.subtract(baseline_mean).divide(baseline_mean).multiply(100)


def lst_recent_mean_from_range(geom: ee.Geometry, hist_start: int, hist_end: int):
    s = max(hist_end - 2, max(hist_start, 2001))
    fc = annual_lst_collection(geom, s, hist_end)
    return ee.Number(fc.aggregate_mean("value"))


def compute_metrics(geom: ee.Geometry, hist_start: int, hist_end: int, last_full_year: int):
    _, ndvi_mean = current_ndvi_image_and_mean(geom, last_full_year)
    ndvi_hist = landsat_annual_ndvi_collection(geom, max(hist_start, 1984), hist_end)
    forest_summary = forest_loss_summary(geom)

    metrics = ee.Dictionary({
        "area_ha": ee.Image.pixelArea().divide(10000).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geom,
            scale=10,
            maxPixels=1e13
        ).get("area"),
        "ndvi_current": ndvi_mean,
        "ndvi_trend": series_recent_vs_early_delta(ndvi_hist),
        "rain_anom_pct": rainfall_anomaly_pct_from_range(geom, hist_start, hist_end),
        "lst_mean": lst_recent_mean_from_range(geom, hist_start, hist_end),
        "tree_pct": landcover_pct(geom, 10),
        "cropland_pct": landcover_pct(geom, 40),
        "built_pct": landcover_pct(geom, 50),
        "water_occ": surface_water_occurrence_mean(geom),
        "bio_proxy": bio_proxy_mean(geom),
        "forest_ha": forest_summary["forest_ha"],
        "forest_loss_ha": forest_summary["loss_ha"],
        "forest_loss_pct": forest_summary["loss_pct"]
    })

    return metrics.getInfo()
