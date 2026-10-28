"""Readable PDF report generation for RootCause AI."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


def build_readable_pdf(title, sections):
    """Create a readable, paginated PDF from (heading, body) sections."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm, title=str(title),
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RootCauseTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=20, leading=25, textColor=colors.HexColor("#183153"),
        alignment=TA_LEFT, spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "RootCauseHeading", parent=styles["Heading2"], fontSize=12,
        leading=16, textColor=colors.HexColor("#24558a"),
        spaceBefore=10, spaceAfter=5, keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "RootCauseBody", parent=styles["BodyText"], fontSize=9,
        leading=13, textColor=colors.HexColor("#263445"), spaceAfter=5,
        splitLongWords=True,
    )
    story = [
        Paragraph(escape(str(title)), title_style),
        Paragraph("ROOTCAUSE AI | Evidence-linked incident investigation", body_style),
        Spacer(1, 5 * mm),
    ]
    for heading, body in sections or []:
        story.append(Paragraph(escape(str(heading or "Details")), heading_style))
        lines = body if isinstance(body, (list, tuple)) else str(body or "").splitlines()
        if not lines:
            lines = ["Not available."]
        for line in lines:
            line = str(line).strip()
            story.append(Spacer(1, 2 * mm) if not line else Paragraph(escape(line), body_style))

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d6deea"))
        canvas.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#65758b"))
        canvas.drawString(18 * mm, 8 * mm, "Heuristic analysis only - verify before confirming a cause.")
        canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()
