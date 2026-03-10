from io import BytesIO
from datetime import date
from pathlib import Path

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
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader


def _fmt(val, digits=2, suffix=""):
    if val is None:
        return "—"
    try:
        return f"{float(val):.{digits}f}{suffix}"
    except Exception:
        return "—"


def _safe_rl_image(img_source, width_mm=None, height_mm=None):
    img_reader = ImageReader(img_source)
    orig_w, orig_h = img_reader.getSize()

    if width_mm is not None and height_mm is None:
        aspect = orig_h / orig_w
        height_mm = width_mm * aspect
    elif height_mm is not None and width_mm is None:
        aspect = orig_w / orig_h
        width_mm = height_mm * aspect
    elif width_mm is None and height_mm is None:
        width_mm = 60
        aspect = orig_h / orig_w
        height_mm = width_mm * aspect

    return Image(img_source, width=width_mm * mm, height=height_mm * mm)


def _section_with_optional_image(title, description, img_bytes, h_style, small_style, body_style):
    items = [Paragraph(title, h_style)]
    if description:
        items.append(Paragraph(description, small_style))

    if img_bytes is not None:
        try:
            items.append(_safe_rl_image(img_bytes, width_mm=175))
        except Exception:
            items.append(Paragraph("Image unavailable in this export.", body_style))
    else:
        items.append(Paragraph("Image unavailable in this export.", body_style))

    items.append(Spacer(1, 4 * mm))
    return KeepTogether(items)


def build_pdf_report(
    preset: str,
    category: str,
    hist_start: int,
    hist_end: int,
    metrics: dict,
    risk: dict,
    image_payloads: list,
    chart_payloads: list,
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
        spaceAfter=4,
        spaceBefore=8,
    )
    body_style = ParagraphStyle(
        "body_style",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=12,
        spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "small_style",
        parent=styles["BodyText"],
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=4,
    )

    story = []

    logo_path = Path("assets/logo.png")
    if logo_path.exists():
        try:
            story.append(_safe_rl_image(str(logo_path), width_mm=34))
            story.append(Spacer(1, 3 * mm))
        except Exception:
            pass

    story.append(Paragraph("EagleNatureInsight Report", title_style))
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

    story.append(Paragraph("Quick reading guide", h_style))
    story.append(Paragraph("Greener vegetation images usually suggest stronger plant cover. Redder vegetation images usually suggest lower or stressed vegetation.", body_style))
    story.append(Paragraph("Vegetation change maps use red for decline and green for improvement.", body_style))
    story.append(Paragraph("These outputs are screening outputs. They help identify where closer review may be useful.", body_style))

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

    if image_payloads:
        story.append(PageBreak())
        story.append(Paragraph("Image outputs", h_style))
        for item in image_payloads:
            story.append(
                _section_with_optional_image(
                    title=item.get("title", "Image"),
                    description=item.get("description", ""),
                    img_bytes=item.get("bytes"),
                    h_style=h_style,
                    small_style=small_style,
                    body_style=body_style,
                )
            )

    if chart_payloads:
        story.append(PageBreak())
        story.append(Paragraph("Historical plots and charts", h_style))
        for item in chart_payloads:
            story.append(
                _section_with_optional_image(
                    title=item.get("title", "Chart"),
                    description=item.get("description", ""),
                    img_bytes=item.get("bytes"),
                    h_style=h_style,
                    small_style=small_style,
                    body_style=body_style,
                )
            )

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
