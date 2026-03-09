import json
import ee


# =====================================================
# 1. EARTH ENGINE AUTH
# =====================================================
def initialize_ee_from_secrets(st) -> None:
    """
    Initialize Earth Engine using Streamlit secrets.
    Expected secret:
    st.secrets["earthengine"]["service_account_json"]
    """
    if getattr(initialize_ee_from_secrets, "_initialized", False):
        return

    service_account_info = json.loads(
        st.secrets["earthengine"]["service_account_json"]
    )

    credentials = ee.ServiceAccountCredentials(
        service_account_info["client_email"],
        key_data=json.dumps(service_account_info),
    )

    ee.Initialize(credentials)
    initialize_ee_from_secrets._initialized = True


# =====================================================
# 2. DATASET FACTORY
# =====================================================
def get_datasets():
    return {
        "S2": ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED"),
        "CHIRPS": ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY"),
        "WORLDCOVER": ee.Image("ESA/WorldCover/v200/2021").select("Map"),
        "GSW": ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence"),
        "GSW_YEARLY": ee.ImageCollection("JRC/GSW1_4/YearlyHistory"),
        "HANSEN": ee.Image("UMD/hansen/global_forest_change_2024_v1_12"),
        "MODIS_LST": ee.ImageCollection("MODIS/061/MOD11A2"),
        "LT05": ee.ImageCollection("LANDSAT/LT05/C02/T1_L2"),
        "LE07": ee.ImageCollection("LANDSAT/LE07/C02/T1_L2"),
        "LC08": ee.ImageCollection("LANDSAT/LC08/C02/T1_L2"),
        "LC09": ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"),
        "BIO_PROXY": ee.FeatureCollection("RESOLVE/ECOREGIONS/2017")
        .reduceToImage(properties=["BIOME_NUM"], reducer=ee.Reducer.first())
        .rename("bio_proxy"),
    }


# =====================================================
# 3. GEOMETRY HELPERS
# =====================================================
def geojson_to_ee_geometry(geojson_obj: dict) -> ee.Geometry:
    geometry = geojson_obj.get("geometry", geojson_obj)
    return ee.Geometry(geometry)


def point_buffer_to_ee_geometry(lat: float, lon: float, buffer_m: float) -> ee.Geometry:
    return ee.Geometry.Point([lon, lat]).buffer(buffer_m)


# =====================================================
# 4. IMAGE HELPERS
# =====================================================
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


def image_thumb_url(image: ee.Image, geom: ee.Geometry, dimensions: int = 1200) -> str:
    return image.getThumbURL({
        "region": geom.bounds(),
        "dimensions": dimensions,
        "format": "png"
    })


# =====================================================
# 5. LANDSAT PREP
# =====================================================
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
            ds["CHIRPS"].filterBounds(geom)
            .filterDate(ee
