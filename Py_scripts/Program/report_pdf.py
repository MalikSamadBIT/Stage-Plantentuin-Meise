import io
import math
import os
from datetime import datetime

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

import gap_analysis

# Same status vocabulary as gap_analysis.py recolored for a white page

STATUS_COLORS = {
    "no_sequences": colors.HexColor("#b91c1c"),
    "partial": colors.HexColor("#b45309"),
    "complete": colors.HexColor("#15803d"),
    "no_data": colors.HexColor("#6b7280"),
}


_FONT_DIR = r"C:\Windows\Fonts"
try:
    pdfmetrics.registerFont(
        TTFont("TimesNewRoman", os.path.join(_FONT_DIR, "times.ttf")))
    pdfmetrics.registerFont(
        TTFont("TimesNewRoman-Bold", os.path.join(_FONT_DIR, "timesbd.ttf")))
    pdfmetrics.registerFont(
        TTFont("TimesNewRoman-Italic", os.path.join(_FONT_DIR, "timesi.ttf")))
    pdfmetrics.registerFont(
        TTFont("TimesNewRoman-BoldItalic", os.path.join(_FONT_DIR, "timesbi.ttf")))
    pdfmetrics.registerFontFamily(
        "TimesNewRoman", normal="TimesNewRoman", bold="TimesNewRoman-Bold",
        italic="TimesNewRoman-Italic", boldItalic="TimesNewRoman-BoldItalic"
    )
    FONT_REGULAR = "TimesNewRoman"
    FONT_BOLD = "TimesNewRoman-Bold"
    FONT_ITALIC = "TimesNewRoman-Italic"
except Exception:
    FONT_REGULAR = "Times-Roman"
    FONT_BOLD = "Times-Bold"
    FONT_ITALIC = "Times-Italic"

_styles = getSampleStyleSheet()

TITLE_STYLE = ParagraphStyle(
    "ReportTitle", parent=_styles["Title"], fontName=FONT_BOLD,
    fontSize=20, alignment=TA_CENTER, spaceAfter=4
)
META_STYLE = ParagraphStyle(
    "ReportMeta", parent=_styles["Normal"], fontName=FONT_ITALIC,
    fontSize=10, alignment=TA_CENTER, textColor=colors.HexColor("#555555")
)
ABSTRACT_STYLE = ParagraphStyle(
    "Abstract", parent=_styles["Normal"], fontName=FONT_REGULAR,
    fontSize=10.5, leading=15, alignment=TA_JUSTIFY, spaceBefore=14, spaceAfter=10
)
SECTION_STYLE = ParagraphStyle(
    "Section", parent=_styles["Heading2"], fontName=FONT_BOLD,
    fontSize=13, spaceBefore=16, spaceAfter=4
)
CAPTION_STYLE = ParagraphStyle(
    "Caption", parent=_styles["Normal"], fontName=FONT_ITALIC,
    fontSize=9, textColor=colors.HexColor("#555555"), spaceAfter=6
)
CELL_STYLE = ParagraphStyle(
    "TableCell", parent=_styles["Normal"], fontName=FONT_REGULAR, fontSize=9
)
HEADER_STYLE = ParagraphStyle(
    "TableHeader", parent=CELL_STYLE, fontName=FONT_BOLD, alignment=TA_CENTER
)


def _status_paragraph(status_label, status_key):
    color = STATUS_COLORS.get(status_key, colors.black)
    text = status_label
    if status_key == "no_sequences":
        text = f"<b>{text}</b>"
    elif status_key == "partial":
        text = f"<i>{text}</i>"
    style = ParagraphStyle("Status", parent=CELL_STYLE, textColor=color)
    return Paragraph(text, style)


def _page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT_ITALIC, 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawCentredString(doc.pagesize[0] / 2, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _scaled_image(image_source, max_width):
    img = Image(image_source)
    if img.imageWidth > max_width:
        ratio = max_width / img.imageWidth
        img.drawWidth = max_width
        img.drawHeight = img.imageHeight * ratio
    return img


def _split_wide_image(image_path, available_width, target_dpi=150, row_gap=6):
    """
    MSA alignment images get wider with more sequence columns, but a plain
    "scale the whole thing to fit the page" shrinks long alignments into an
    unreadable strip. This instead crops the image into several width-
    limited horizontal strips (keeping full height, i.e. all sequence rows)
    and returns them as separate flowables to stack vertically - each strip
    lands at roughly target_dpi when displayed at the page's available
    width, so readability stays consistent no matter how wide the original
    alignment is.
    """
    img = PILImage.open(image_path)
    native_width, native_height = img.size

    # how many source pixels fit across the page's available width while
    # staying at (roughly) target_dpi - 72pt = 1 inch
    max_px_per_strip = (available_width / 72) * target_dpi

    if native_width <= max_px_per_strip:
        return [_scaled_image(image_path, available_width)]

    num_strips = math.ceil(native_width / max_px_per_strip)
    strip_width = math.ceil(native_width / num_strips)

    flowables = []
    for i in range(num_strips):
        left = i * strip_width
        right = min(left + strip_width, native_width)
        strip = img.crop((left, 0, right, native_height))

        buf = io.BytesIO()
        strip.save(buf, format="PNG")
        buf.seek(0)

        display_height = available_width * (strip.height / strip.width)
        flowables.append(
            Image(buf, width=available_width, height=display_height))

        if i < num_strips - 1:
            flowables.append(Spacer(1, row_gap))

    return flowables


def _gap_table_col_widths(num_markers, available_width):
    # Species/Observations/Status get a fixed share of the page
    species_w = available_width * 0.26
    obs_w = available_width * 0.13
    status_w = available_width * 0.17
    marker_total = max(available_width - species_w - obs_w - status_w, 1 * cm)
    marker_w = marker_total / num_markers if num_markers else 0

    col_widths = [species_w, obs_w] + [marker_w] * num_markers + [status_w]

    total = sum(col_widths)
    if total > available_width:
        scale = available_width / total
        col_widths = [w * scale for w in col_widths]

    return col_widths


def _build_gap_table(rows, target_markers, available_width):
    header = (
        [Paragraph("Species", HEADER_STYLE), Paragraph(
            "Observations", HEADER_STYLE)]
        + [Paragraph(m, HEADER_STYLE) for m in target_markers]
        + [Paragraph("Status", HEADER_STYLE)]
    )
    data = [header]

    for row in rows:
        obs = "-" if row["observations"] is None else f"{row['observations']:,}"
        line = [Paragraph(row["species"], CELL_STYLE), obs]
        for marker in target_markers:
            value = row[marker]
            line.append("-" if value is None else str(value))
        line.append(_status_paragraph(row["status_label"], row["status"]))
        data.append(line)

    col_widths = _gap_table_col_widths(len(target_markers), available_width)
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_commands = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#dddddd")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    # thin colored accent bar on the left edge of each data row, matching its status
    for i, row in enumerate(rows, start=1):
        color = STATUS_COLORS.get(row["status"], colors.black)
        style_commands.append(("LINEBEFORE", (0, i), (0, i), 3, color))

    table.setStyle(TableStyle(style_commands))
    return table


def _build_marker_coverage_table(coverage_stats):
    data = [["Marker", "Species covered", "Coverage"]]
    for marker, covered, assessed, percentage in coverage_stats:
        data.append([marker, f"{covered} / {assessed}", f"{percentage:.0f}%"])

    table = Table(data, colWidths=[5 * cm, 4 * cm, 4 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_score_table(scores):
    data = [["Metric", "Value"]]
    for label, value in scores.items():
        if "% of max possible" in label:
            formatted = f"{value:.2f}%"
        elif isinstance(value, float):
            formatted = f"{value:.4f}"
        else:
            formatted = str(value)
        data.append([label, formatted])

    table = Table(data, colWidths=[9 * cm, 4 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_synonyms_table(synonym_results):
    data = [["Species", "Synonyms"]]
    for species, synonyms in synonym_results.items():
        parts = [f"{name} ({lang})" for lang, name in synonyms.items() if name]
        data.append([
            Paragraph(species, CELL_STYLE),
            Paragraph(", ".join(parts) if parts else "-", CELL_STYLE),
        ])

    table = Table(data, colWidths=[4.5 * cm, 9.5 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_report_pdf(
    path, rows, target_markers, meta, report_items, status_chart_bytes=None
):
    """
    path: output .pdf file path
    rows: gap_analysis.build_gap_rows() output - the required "Gap analysis"
        section
    target_markers: the markers used for that gap analysis run
    meta: {"site": str, "start_date": date, "end_date": date}
    report_items: optional sections pushed from the Retrieval Rate/MSA/
        Synonym search tabs' "Add to Report" buttons - see their item
        shapes in gap_tab.py's build_gap_tab docstring
    status_chart_bytes: optional PNG bytes from
        gap_analysis.build_status_chart_png(rows) - a user-toggleable
        summary figure placed right after the gap analysis table
    """

    pagesize = landscape(A4) if len(target_markers) > 4 else A4

    doc = SimpleDocTemplate(
        path, pagesize=pagesize,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm
    )

    story = [
        Paragraph("Gap analysis report", TITLE_STYLE),
        Paragraph(
            f"Flora Fetch - generated "
            f"{datetime.now().strftime('%d %B %Y')}",
            META_STYLE
        ),
        Paragraph(
            f"Site: {meta['site']} - period {meta['start_date']} to "
            f"{meta['end_date']} - markers: {', '.join(target_markers)}",
            META_STYLE
        ),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1, color=colors.black),
    ]

    counts = {"no_sequences": 0, "partial": 0, "complete": 0, "no_data": 0}
    for row in rows:
        counts[row["status"]] += 1

    no_data_note = (
        f" ({counts['no_data']} could not be checked against the "
        f"observation site)." if counts["no_data"] else "."
    )
    abstract = (
        f"Of the {len(rows)} species surveyed, {counts['no_sequences']} lack "
        f"any sequence data on file, {counts['partial']} show partial marker "
        f"coverage, and {counts['complete']} are fully represented in the "
        f"local reference database{no_data_note} Within each coverage "
        "category, species are ranked by field-observation count, so the "
        "highest-value near-term sequencing targets appear first."
    )
    story.append(Paragraph(abstract, ABSTRACT_STYLE))

    story.append(Paragraph("1. Gap analysis", SECTION_STYLE))
    story.append(Paragraph(
        "Table 1. Sequence coverage per species, ranked by observation "
        "count within status.", CAPTION_STYLE
    ))
    story.append(_build_gap_table(rows, target_markers, doc.width))

    coverage_stats = gap_analysis.build_marker_coverage_stats(
        rows, target_markers)
    story.append(Paragraph(
        "Table 2. Marker coverage across surveyed species (of those "
        "successfully checked against the observation site).",
        CAPTION_STYLE
    ))
    story.append(_build_marker_coverage_table(coverage_stats))

    figure_num = 1
    if status_chart_bytes:
        story.append(_scaled_image(io.BytesIO(status_chart_bytes), doc.width))
        story.append(Paragraph(
            f"Figure {figure_num}. Gap analysis status summary.",
            CAPTION_STYLE
        ))
        figure_num += 1

    section_num = 2
    table_num = 3

    for item in report_items:
        if item["type"] == "retrieval_chart":
            story.append(
                Paragraph(f"{section_num}. Retrieval rate", SECTION_STYLE))
            story.append(_scaled_image(
                io.BytesIO(item["image_bytes"]), doc.width))
            story.append(Paragraph(f"Figure {figure_num}. {item['title']}.",
                                   CAPTION_STYLE))
            figure_num += 1
            section_num += 1

        elif item["type"] == "msa":
            story.append(Paragraph(
                f"{section_num}. Multiple sequence alignment", SECTION_STYLE))
            story.extend(_split_wide_image(item["image_path"], doc.width))
            story.append(Paragraph(f"Figure {figure_num}. {item['title']}.",
                                   CAPTION_STYLE))
            figure_num += 1

            if item.get("scores"):
                story.append(Paragraph(
                    f"Table {table_num}. Alignment quality scores.",
                    CAPTION_STYLE
                ))
                story.append(_build_score_table(item["scores"]))
                table_num += 1

            section_num += 1

        elif item["type"] == "barcode_gap":
            a = item["assessment"]
            story.append(Paragraph(
                f"{section_num}. Barcode gap - {a['species']}", SECTION_STYLE))

            verdict_label = gap_analysis.BARCODE_GAP_VERDICTS[a["verdict"]]
            method = a.get("distance_method",
                           gap_analysis.DEFAULT_DISTANCE_METHOD)
            if a["verdict"] == "insufficient_data":
                summary = f"Verdict: {verdict_label} - {a['reason']}"
            else:
                summary = (
                    f"Verdict: {verdict_label} ({method}). Max intraspecific "
                    f"distance {a['max_intraspecific']:.4f}, min interspecific "
                    f"distance {a['min_interspecific']:.4f} (nearest neighbor: "
                    f"{a['nearest_neighbor']}), gap {a['gap']:+.4f}."
                )
            story.append(Paragraph(summary, ABSTRACT_STYLE))

            if item.get("image_bytes"):
                story.append(_scaled_image(
                    io.BytesIO(item["image_bytes"]), doc.width))
                story.append(Paragraph(
                    f"Figure {figure_num}. {item['title']} - neighbor-joining "
                    "guide tree (p-distance, no bootstrap support - not a "
                    "rigorous phylogeny).", CAPTION_STYLE
                ))
                figure_num += 1

            section_num += 1

        elif item["type"] == "synonyms":
            story.append(Paragraph(f"{section_num}. Synonyms", SECTION_STYLE))
            story.append(Paragraph(
                f"Table {table_num}. Species and associated common names "
                "by language.", CAPTION_STYLE
            ))
            story.append(_build_synonyms_table(item["data"]))
            table_num += 1
            section_num += 1

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
