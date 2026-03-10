from io import BytesIO
from datetime import date
from pathlib import Path
import requests

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def _download_image(url: str) -> BytesIO | None:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return BytesIO(r.content)
    except Exception:
        return None


def _fmt(val, digits=2, suffix=""):
    if val is None:
        return "—"
    try:
        return f"{float(val):.{digits}f}{suffix}"
    except Exception:
        return "—"


def build_pdf_report(
    preset: str,
    category: str,
    hist_start: int,
    hist_end: int,
    metrics: dict,
    risk: dict,
    satellite_url: str,
    ndvi_url: str,
    landcover_url: str,
    forest_loss_url: str,
    vegetation_change_url: str,
    chart_images: dict | None = None,
) -> bytes:
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title_style",
        parent=styles["Title"],
        textColor=colors.HexColor("#163d63"),
        fontSize=20,
        leading=24,
        spaceAfter=8,
    )
    h_style = ParagraphStyle(
        "h_style",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#163d63"),
        fontSize=13,
        leading=16,
        spaceAfter=6,
        spaceBefore=8,
    )
    body_style = ParagraphStyle(
        "body_style",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=12,
        spaceAfter=4,
    )

    story = []

    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        story.append(Image(str(logo_path), width=38 * mm, height=38 * mm))
        story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("EagleNatureInsight™ Report", title_style))
    story.append(Paragraph(f"Assessment date: {date.today().isoformat()}", body_style))
    story.append(Paragraph(f"Business preset: {preset}", body_style))
    story.append(Paragraph(f"Business category: {category}", body_style))
    story.append(Paragraph(f"Historical range: {hist_start} to {hist_end}", body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Overview", h_style))
    summary_data = [
        ["Metric", "Value"],
        ["Nature Risk", f'{risk.get("score", "—")}/100 ({risk.get("band", "—")})'],
        ["Area (ha)", _fmt(metrics.get("area_ha"), 1)],
        ["Current NDVI", _fmt(metrics.get("ndvi_current"), 3)],
        ["Rainfall Anomaly", _fmt(metrics.get("rain_anom_pct"), 1, "%")],
        ["Tree Cover", _fmt(metrics.get("tree_pct"), 1, "%")],
        ["Built-up", _fmt(metrics.get("built_pct"), 1, "%")],
        ["Surface Water", _fmt(metrics.get("water_occ"), 1)],
        ["Recent LST Mean", _fmt(metrics.get("lst_mean"), 1, " °C")],
        ["Forest Loss (ha)", _fmt(metrics.get("forest_loss_ha"), 1)],
        ["Forest Loss (%)", _fmt(metrics.get("forest_loss_pct"), 1, "%")],
    ]
    summary_table = Table(summary_data, colWidths=[60 * mm, 110 * mm])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163d63")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEADING", (0, 0), (-1, -1), 11),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    story.append(summary_table)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Simple reading guide", h_style))
    story.append(Paragraph("Green or higher vegetation values usually suggest stronger plant cover. Redder or lower vegetation values can suggest stress or limited vegetation.", body_style))
    story.append(Paragraph("Rising heat, falling vegetation, or visible tree loss may point to higher environmental pressure around the site.", body_style))
    story.append(Paragraph("These outputs are for screening and discussion. They help identify where closer review may be useful.", body_style))

    story.append(Paragraph("LEAP Outputs", h_style))
    story.append(Paragraph("<b>Locate</b>: The selected area has been defined and checked against land cover and surrounding environmental context.", body_style))
    story.append(Paragraph("<b>Evaluate</b>: Current and historical environmental conditions have been reviewed.", body_style))
    story.append(Paragraph("<b>Assess</b>: The dashboard translates the evidence into simple risk signals.", body_style))
    story.append(Paragraph("<b>Prepare</b>: The dashboard gives practical next-step recommendations.", body_style))

    if risk.get("flags"):
        story.append(Paragraph("Key flags", h_style))
        for flag in risk["flags"]:
            story.append(Paragraph(f"• {flag}", body_style))

    if risk.get("recs"):
        story.append(Paragraph("Recommendations", h_style))
        for rec in risk["recs"]:
            story.append(Paragraph(f"• {rec}", body_style))

    story.append(PageBreak())

    image_specs = [
        ("Satellite image with polygon", satellite_url, "This is a true-colour satellite view of the selected site. The red outline shows the assessment area."),
        ("NDVI image with polygon", ndvi_url, "This image shows vegetation condition. Greener tones generally mean healthier or denser vegetation. Redder tones suggest weaker vegetation."),
        ("Land-cover image with polygon", landcover_url, "This image shows the main land-cover types in the selected area, such as tree cover, cropland, built-up land, and water."),
        ("Vegetation change map with polygon", vegetation_change_url, "This image compares earlier and more recent vegetation condition. Redder areas suggest decline. Greener areas suggest improvement."),
        ("Forest loss map with polygon", forest_loss_url, "This image highlights where forest loss has been detected in or around the selected area."),
    ]

    for title, url, expl in image_specs:
        img_data = _download_image(url)
        if img_data is not None:
            story.append(Paragraph(title, h_style))
            story.append(Paragraph(expl, body_style))
            img = Image(img_data, width=170 * mm, height=95 * mm)
            story.append(img)
            story.append(Spacer(1, 4 * mm))

    if chart_images:
        story.append(PageBreak())
        story.append(Paragraph("Historical plots", h_style))

        ordered = [
            ("ndvi", "Historical NDVI"),
            ("rain", "Historical rainfall"),
            ("lst", "Historical land surface temperature"),
            ("forest", "Historical forest loss"),
            ("water", "Historical water presence"),
            ("landcover", "Current land-cover composition"),
        ]

        for key, title in ordered:
            img_data = chart_images.get(key)
            if img_data is not None:
                story.append(Paragraph(title, h_style))
                story.append(Image(img_data, width=170 * mm, height=95 * mm))
                story.append(Spacer(1, 4 * mm))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
