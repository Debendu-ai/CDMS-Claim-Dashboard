"""
pdf_report.py
=============
Builds PDF versions of the dashboard's reports (distributor-wise tables +
pie charts), using matplotlib for the charts and reportlab for page
layout. Pure functions, no Streamlit dependency, so they're testable
standalone.
"""

import io

import matplotlib
matplotlib.use("Agg")  # headless backend, safe for server-side rendering
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

BRAND_BLUE = colors.HexColor("#1F4E78")
LIGHT_BLUE = colors.HexColor("#D9E1F2")
RED = colors.HexColor("#FFC7CE")
GREEN = colors.HexColor("#E2EFDA")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontSize=18, leading=22,
                               textColor=BRAND_BLUE, spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="ReportSubtitle", fontSize=10, leading=14,
                               textColor=colors.grey, spaceAfter=12))
    styles.add(ParagraphStyle(name="SectionHeading", fontSize=13, leading=16,
                               textColor=BRAND_BLUE, spaceBefore=14, spaceAfter=6,
                               fontName="Helvetica-Bold"))
    return styles


def _pie_chart_image(labels, values, title, max_slices=12):
    """Returns a reportlab Image flowable of a matplotlib pie chart.
    Groups small slices beyond max_slices into 'Others' to keep it readable.
    """
    data = list(zip(labels, values))
    data = [d for d in data if d[1] and d[1] > 0]
    data.sort(key=lambda x: x[1], reverse=True)
    if len(data) > max_slices:
        top = data[:max_slices]
        others_sum = sum(v for _, v in data[max_slices:])
        if others_sum > 0:
            top.append(("Others", others_sum))
        data = top

    if not data:
        return None

    labels_p = [d[0] for d in data]
    values_p = [d[1] for d in data]

    fig, ax = plt.subplots(figsize=(6, 5))
    colors_list = plt.cm.tab20.colors
    ax.pie(
        values_p, labels=labels_p, autopct="%1.1f%%", startangle=90,
        colors=colors_list, textprops={"fontsize": 8},
    )
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.axis("equal")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=11 * cm, height=9 * cm)


def _df_to_table(df: pd.DataFrame, money_cols=None, highlight_rows=None, col_widths=None):
    """Build a styled reportlab Table from a DataFrame.
    highlight_rows: dict {row_index_in_df: color} for conditional row highlighting.
    """
    money_cols = money_cols or []
    highlight_rows = highlight_rows or {}

    header = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        formatted = []
        for c in header:
            v = row[c]
            if c in money_cols and isinstance(v, (int, float)):
                formatted.append(f"{v:,.2f}")
            else:
                formatted.append(str(v))
        rows.append(formatted)

    table_data = [header] + rows
    t = Table(table_data, repeatRows=1, colWidths=col_widths)

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FC")]),
    ]
    for idx, color in highlight_rows.items():
        r = idx + 1  # +1 for header row
        style.append(("BACKGROUND", (0, r), (-1, r), color))

    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------- Stage 1 --

def build_working_pdf(summary_df: pd.DataFrame, depot_df: pd.DataFrame = None,
                       title: str = "CDMS Working — Distributor-wise Prc Off Claim & DB Margin Amt") -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                             leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    story = []

    story.append(Paragraph(title, styles["ReportTitle"]))
    story.append(Paragraph(
        f"{summary_df.shape[0]} distributors — "
        f"Total Prc Off Claim: Rs {summary_df['Working_Prc_Off_Claim'].sum():,.2f} | "
        f"Total DB Margin Amt: Rs {summary_df['Working_DB_Margin_Amt'].sum():,.2f} | "
        f"Total Claim: Rs {summary_df['Working_DB_Tot_Claim'].sum():,.2f}",
        styles["ReportSubtitle"],
    ))

    pie = _pie_chart_image(
        summary_df["Distributor Name"].tolist(),
        summary_df["Working_DB_Tot_Claim"].tolist(),
        "Share of Total Claim by Distributor",
    )
    if pie:
        story.append(pie)

    story.append(Paragraph("Distributor-wise Working", styles["SectionHeading"]))
    display_cols = ["DB Code", "Distributor Name", "Rows",
                     "Working_Prc_Off_Claim", "Working_DB_Margin_Amt", "Working_DB_Tot_Claim"]
    display_cols = [c for c in display_cols if c in summary_df.columns]
    money_cols = ["Working_Prc_Off_Claim", "Working_DB_Margin_Amt", "Working_DB_Tot_Claim"]
    table = _df_to_table(summary_df[display_cols], money_cols=money_cols)
    story.append(table)

    if depot_df is not None and not depot_df.empty:
        story.append(PageBreak())
        story.append(Paragraph("Depot-wise Working", styles["SectionHeading"]))
        depot_cols = ["Depot Code", "Depot Name", "Rows",
                      "Working_Prc_Off_Claim", "Working_DB_Margin_Amt", "Working_DB_Tot_Claim"]
        depot_cols = [c for c in depot_cols if c in depot_df.columns]
        depot_table = _df_to_table(depot_df[depot_cols], money_cols=money_cols)
        story.append(depot_table)

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- Stage 2 --

def build_claim_accuracy_pdf(comparison_df: pd.DataFrame, score: dict,
                              title: str = "CDMS Promo Claim Accuracy Report") -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                             leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    story = []

    story.append(Paragraph(title, styles["ReportTitle"]))
    story.append(Paragraph(
        f"Accuracy: {score['Accuracy %']}% ({score['Matched']}/{score['Distributors Checked']} distributors matched) | "
        f"Working Total: Rs {score['Total Working Claim']:,.2f} | "
        f"Actual Total: Rs {score['Total Actual Claim']:,.2f} | "
        f"Variance: Rs {score['Total Variance']:,.2f}",
        styles["ReportSubtitle"],
    ))

    status_counts = comparison_df["Status"].value_counts()
    pie = _pie_chart_image(
        status_counts.index.tolist(), status_counts.values.tolist(),
        "Distributors by Status",
    )
    if pie:
        story.append(pie)

    story.append(Paragraph("Distributor-wise Comparison", styles["SectionHeading"]))
    display_cols = ["DB Code", "Distributor Name",
                     "Working_DB_Tot_Claim", "Actual_DB_Tot_Claim", "Diff_DB_Tot_Claim", "Status"]
    display_cols = [c for c in display_cols if c in comparison_df.columns]
    money_cols = ["Working_DB_Tot_Claim", "Actual_DB_Tot_Claim", "Diff_DB_Tot_Claim"]

    highlight_rows = {}
    for i, status in enumerate(comparison_df["Status"]):
        if status == "MATCH":
            highlight_rows[i] = GREEN
        elif status != "MATCH":
            highlight_rows[i] = RED

    table = _df_to_table(comparison_df[display_cols], money_cols=money_cols, highlight_rows=highlight_rows)
    story.append(table)

    doc.build(story)
    return buf.getvalue()
