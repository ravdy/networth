"""Word (.docx) export of the full portfolio."""
import io
from datetime import date

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import portfolio, recommendations

ACCENT = RGBColor(0x2A, 0x78, 0xD6)
MUTED = RGBColor(0x52, 0x51, 0x4E)
UP = RGBColor(0x00, 0x63, 0x00)
DOWN = RGBColor(0xD0, 0x3B, 0x3B)


def inr(v, decimals=0):
    """Indian digit grouping: 12,34,56,789."""
    if v is None:
        return "—"
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return ("-" if neg else "") + "₹" + whole + ("." + frac if frac else "")


def pct(v):
    if v is None:
        return "—"
    v = round(v, 1) + 0.0  # avoid "-0.0%"
    return f"{v:+.1f}%" if v else "0.0%"


def fdate(s):
    return date.fromisoformat(s[:10]).strftime("%d %b %Y") if s else "—"


def _shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _table(doc, headers, rows, num_cols=(), widths=None, total_row=None, color_cols=()):
    """rows: list of lists of str; color_cols: column indexes whose value sign sets the colour."""
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = MUTED
        _shade(c, "F3F2EE")
        if i in num_cols:
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for row in rows + ([total_row] if total_row else []):
        cells = t.add_row().cells
        for i, val in enumerate(row):
            p = cells[i].paragraphs[0]
            run = p.add_run(str(val))
            run.font.size = Pt(9)
            if row is total_row:
                run.bold = True
            if i in num_cols:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if i in color_cols and isinstance(val, str) and val not in ("—", ""):
                if val.lstrip("₹+").startswith("-") or val.startswith("-"):
                    run.font.color.rgb = DOWN
                elif val.strip("₹+0.,%") != "":
                    run.font.color.rgb = UP
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def build_docx(con) -> bytes:
    settings = portfolio.get_settings(con)
    assets = portfolio.load_assets(con)
    liabs = portfolio.load_liabilities(con)
    summ = portfolio.summary(con)
    recs = recommendations.build(settings, assets, liabs, summ)

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(1.8))
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    title = doc.add_heading("Net Worth Statement", level=0)
    title.runs[0].font.color.rgb = ACCENT
    sub = doc.add_paragraph()
    who = settings.get("name")
    r = sub.add_run((f"{who} · " if who else "") + f"Generated on {date.today().strftime('%d %b %Y')}")
    r.font.color.rgb = MUTED

    # ---- summary ----
    doc.add_heading("Summary", level=1)
    gain_pct = summ["total_gain"] / summ["total_invested"] * 100 if summ["total_invested"] > 0 else None
    _table(doc, ["Measure", "Amount"], [
        ["Net worth", inr(summ["net_worth"])],
        ["Total assets (current value)", inr(summ["total_assets"])],
        ["Total liabilities (outstanding)", inr(summ["total_liabilities"])],
        ["Net invested in assets", inr(summ["total_invested"])],
        ["Unrealised gain", f"{inr(summ['total_gain'])} ({pct(gain_pct)})"],
        ["Monthly EMIs", inr(summ["monthly_emi"])],
        ["Number of assets / liabilities", f"{summ['asset_count']} / {summ['liability_count']}"],
    ], num_cols=(1,), widths=(8, 6))

    # ---- allocation ----
    doc.add_heading("Allocation by segment", level=1)
    cats = [c for c in summ["by_category"] if c["value"] > 0]
    _table(doc, ["Segment", "Current value", "% of assets"],
           [[c["label"], inr(c["value"]), f"{c['pct']:.1f}%"] for c in cats],
           num_cols=(1, 2), widths=(7, 5, 3))

    # ---- assets, one table per group (Real Estate, Mutual Funds, ...) ----
    doc.add_heading("Assets", level=1)
    tot_inv = sum(a["invested"] for a in assets)
    tot_cur = sum(a["current_value"] for a in assets)
    if assets:
        _table(doc, ["Group", "Assets", "Net invested", "Current value", "Gain", "Gain %", "% of assets"],
               [[g["group"], str(g["count"]), inr(g["invested"]), inr(g["value"]), inr(g["gain"]), pct(g["gain_pct"]), f"{g['pct']:.1f}%"]
                for g in summ["by_group"]],
               num_cols=(1, 2, 3, 4, 5, 6), color_cols=(4, 5), widths=(5, 1.6, 3.2, 3.2, 3, 2, 2),
               total_row=["Total", str(len(assets)), inr(tot_inv), inr(tot_cur), inr(tot_cur - tot_inv),
                          pct((tot_cur - tot_inv) / tot_inv * 100) if tot_inv > 0 else "—", "100%"])
    for g in summ["by_group"]:
        items = sorted((a for a in assets if a["group"] == g["group"]), key=lambda x: -x["current_value"])
        doc.add_heading(f"{g['group']} ({g['count']})", level=2)
        _table(doc, ["Asset", "Type", "Purchase date", "Net invested", "Current value", "Gain", "Gain %", "XIRR", "Value as of"],
               [[a["name"], a["type_label"], fdate(a["first_date"]), inr(a["invested"]), inr(a["current_value"]),
                 inr(a["gain"]), pct(a["gain_pct"]), pct(a["xirr"]), fdate(a["value_date"])] for a in items],
               num_cols=(3, 4, 5, 6, 7), color_cols=(5, 6, 7),
               widths=(5, 5.5, 2.4, 2.8, 2.8, 2.6, 1.7, 1.6, 2.4),
               total_row=[f"{g['group']} total", "", "", inr(g["invested"]), inr(g["value"]), inr(g["gain"]),
                          pct(g["gain_pct"]), "", ""])

    # ---- liabilities ----
    doc.add_heading("Liabilities", level=1)
    if liabs:
        _table(doc, ["Liability", "Type", "Start date", "Tenure", "End date", "Original", "Outstanding", "Rate", "EMI", "Repaid"],
               [[l["name"], l["type_label"], fdate(l["start_date"]),
                 f"{l['tenure_months']} mo" if l["tenure_months"] else "—", fdate(l["end_date"]),
                 inr(l["principal"]), inr(l["outstanding"]),
                 f"{l['interest_rate']}%" if l["interest_rate"] is not None else "—",
                 inr(l["emi"]) if l["emi"] else "—",
                 f"{l['repaid_pct']}%" if l["repaid_pct"] is not None else "—"] for l in liabs],
               num_cols=(5, 6, 7, 8, 9), widths=(4.5, 4, 2.4, 1.6, 2.4, 2.8, 2.8, 1.4, 2.4, 1.6))
    else:
        doc.add_paragraph("No liabilities recorded.")

    # ---- recommendations ----
    doc.add_heading("Recommendations", level=1)
    label = {"high": "Act", "medium": "Review", "info": "Tip", "good": "Good"}
    for it in recs["items"]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"[{label[it['severity']]}] {it['title']}. ")
        r.bold = True
        p.add_run(it["detail"])
    d = doc.add_paragraph()
    r = d.add_run(recs["disclaimer"])
    r.italic = True
    r.font.size = Pt(8)
    r.font.color.rgb = MUTED

    # ---- per-asset detail ----
    if assets:
        doc.add_page_break()
        doc.add_heading("Asset details", level=1)
    for a in assets:
        doc.add_heading(a["name"], level=2)
        meta = doc.add_paragraph()
        meta_run = meta.add_run(
            f"{a['type_label']} · Net invested {inr(a['invested'])} · Current {inr(a['current_value'])} · "
            f"Gain {inr(a['gain'])} ({pct(a['gain_pct'])})" + (f" · XIRR {a['xirr']:.1f}%" if a["xirr"] is not None else "")
            + (f" · {a['units']:g} units" if a["units"] else ""))
        meta_run.font.color.rgb = MUTED
        if a["notes"]:
            doc.add_paragraph(f"Notes: {a['notes']}")

        txs = con.execute("SELECT * FROM transactions WHERE asset_id=? ORDER BY date, id", (a["id"],)).fetchall()
        if txs:
            _table(doc, ["Date", "Type", "Amount", "Units", "Note"],
                   [[fdate(t["date"]), "Buy" if t["kind"] == "BUY" else "Sell", inr(t["amount"]),
                     f"{t['units']:g}" if t["units"] else "", t["note"] or ""] for t in txs],
                   num_cols=(2, 3), widths=(3, 2, 3.5, 2.5, 8))

        growth = [p for p in portfolio.growth_series(con, a["id"]) if p["value_update"]]
        if growth:
            doc.add_paragraph().add_run("Market value updates").bold = True
            _table(doc, ["Date", "Invested till date", "Market value", "Gain", "Growth %"],
                   [[fdate(p["date"]), inr(p["invested"]), inr(p["value"]), inr(p["gain"]), pct(p["gain_pct"])]
                    for p in growth],
                   num_cols=(1, 2, 3, 4), color_cols=(3, 4), widths=(3, 4, 4, 3.5, 2.5))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
