"""Printable model sheet: PDF export and printing, built on QTextDocument."""
from __future__ import annotations

import html
from typing import List, Tuple

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, QUrl, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QPageLayout, QPageSize, QPagedPaintDevice, QPainter,
                           QPainterPath, QPdfWriter, QPen, QTextDocument)
from PySide6.QtPrintSupport import QPrinter

from . import __version__
from . import protocol as P
from .storage import Model

INK, SOFT, LINE = "#1b1d21", "#5b616c", "#c9cdd4"
CURVE_COLORS = ("#2f78c4", "#c27a0c")


def curve_image(title: str, normal: List[int], idle: List[int], w: int = 560, h: int = 300) -> QImage:
    img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(2)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(44, 28, w - 60, h - 64)
    f = QFont("Arial"); f.setPixelSize(11)
    p.setFont(f)
    p.setPen(QColor(INK)); bf = QFont(f); bf.setBold(True); p.setFont(bf)
    p.drawText(QRectF(0, 4, w, 18), Qt.AlignmentFlag.AlignLeft, title)
    p.setFont(f)
    X = lambda i: r.left() + i / 4 * r.width()
    Y = lambda v: r.bottom() - (v + 100) / 200 * r.height()
    for v in (-100, -50, 0, 50, 100):
        p.setPen(QPen(QColor("#9aa1ad" if v == 0 else "#e1e4e8"), 1)); p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
        p.setPen(QColor(SOFT)); p.drawText(QRectF(0, Y(v) - 8, 40, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
    for i in range(5):
        p.setPen(QPen(QColor("#e1e4e8"), 1)); p.drawLine(QPointF(X(i), r.top()), QPointF(X(i), r.bottom()))
        p.setPen(QColor(SOFT)); p.drawText(QRectF(X(i) - 24, r.bottom() + 4, 48, 14), Qt.AlignmentFlag.AlignCenter, f"{i * 25}%")
    p.setPen(QPen(QColor(LINE), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
    for vals, col, name in ((normal, CURVE_COLORS[0], "Normal"), (idle, CURVE_COLORS[1], "Idle")):
        path = QPainterPath(QPointF(X(0), Y(vals[0])))
        for i in range(1, 5): path.lineTo(X(i), Y(vals[i]))
        p.setPen(QPen(QColor(col), 2)); p.drawPath(path)
        p.setBrush(QColor(col))
        for i in range(5): p.drawEllipse(QPointF(X(i), Y(vals[i])), 3.5, 3.5)
    lx = r.right() - 120
    for k, (col, name) in enumerate(zip(CURVE_COLORS, ("Normal", "Idle"))):
        p.setPen(QPen(QColor(col), 2)); p.drawLine(QPointF(lx + k * 62, 12), QPointF(lx + k * 62 + 14, 12))
        p.setPen(QColor(SOFT)); p.drawText(QPointF(lx + k * 62 + 18, 16), name)
    p.end()
    return img


def _table(headers: List[str], rows: List[List[object]]) -> str:
    th = "".join(f"<th align='left' style='color:{SOFT};font-size:8pt;border-bottom:1px solid {LINE};padding:3px 8px 3px 0;white-space:nowrap'>{html.escape(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td style='padding:3px 8px 3px 0;border-bottom:1px solid #eceef1'>{html.escape(str(c))}</td>" for c in r) + "</tr>"
    return f"<table width='100%' cellspacing='0' cellpadding='0'><tr>{th}</tr>{body}</table>"


def build_document(m: Model) -> QTextDocument:
    s = m.settings
    doc = QTextDocument()
    for key, (a, b, t) in {"thr": (s.throttle_normal, s.throttle_idle, "Throttle curve"),
                           "pit": (s.pitch_normal, s.pitch_idle, "Pitch curve")}.items():
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(f"{key}.png"), curve_image(t, a, b))
    h2 = lambda t: f"<h3 style='margin:18px 0 6px 0;font-size:9pt;color:{SOFT};letter-spacing:1px'>{t.upper()}</h3>"
    chans = [[f"CH{i + 1}", m.channel_names[i] or "", "Reverse" if s.reverse[i] else "Normal"] for i in range(6)]
    rates = []
    for i in range(6):
        dr = ("\u2013", "\u2013")
        if i in P.DUAL_RATE_CHANNELS:
            k = P.DUAL_RATE_CHANNELS.index(i); dr = (s.dual_rate_on[k], s.dual_rate_off[k])
        sw = s.swash_afr[P.SWASH_CHANNELS.index(i)] if i in P.SWASH_CHANNELS else "\u2013"
        rates.append([f"CH{i + 1}", s.endpoint_min[i], s.endpoint_max[i], s.subtrim[i], dr[0], dr[1], sw])
    mixes = [[f"Mix {k + 1}", P.label_of(P.MIX_SOURCES, x.source), P.label_of(P.MIX_DESTS, x.dest), x.up, x.down,
              P.label_of(P.MIX_SWITCHES, x.switch)] for k, x in enumerate(s.mixes)]
    notes = f"<p style='color:{SOFT}'>{html.escape(m.description)}</p>" if m.description else ""
    notes += f"<p>{html.escape(m.notes).replace(chr(10), '<br>')}</p>" if m.notes else ""
    doc.setHtml(f"""
<body style="font-family:Arial; font-size:10pt; color:{INK}">
<h1 style="font-size:20pt;margin:0">{html.escape(m.name)}</h1>
<p style="color:{SOFT};margin:2px 0 8px 0">{P.label_of(P.MODEL_TYPES, s.model_type)} &nbsp;\u00b7&nbsp; {P.label_of(P.STICK_MODES, s.stick_mode)}
 &nbsp;\u00b7&nbsp; {html.escape(m.updated or '')}</p>{notes}
{h2('Channels')}{_table(['CHANNEL', 'NAME', 'DIRECTION'], chans)}
{h2('Rates and travel')}{_table(['CHANNEL', 'END POINT MIN', 'END POINT MAX', 'SUBTRIM', 'DUAL RATE ON', 'DUAL RATE OFF', 'SWASH AFR'], rates)}
{h2('Curves')}
<table width="100%"><tr><td><img src="thr.png" width="290"></td><td><img src="pit.png" width="290"></td></tr></table>
{_table(['POINT', 'THR NORMAL', 'THR IDLE', 'PITCH NORMAL', 'PITCH IDLE'], [[f'P{i + 1}', s.throttle_normal[i], s.throttle_idle[i], s.pitch_normal[i], s.pitch_idle[i]] for i in range(5)])}
{h2('Mixing')}{_table(['MIX', 'SOURCE', 'DESTINATION', 'UP RATE', 'DOWN RATE', 'SWITCH'], mixes)}
{h2('Switches')}{_table(['FUNCTION', 'ASSIGNED TO'], [['Switch A', P.label_of(P.SWITCH_FUNCS, s.switch_a)], ['Switch B', P.label_of(P.SWITCH_FUNCS, s.switch_b)], ['Variable A', P.label_of(P.VARIABLE_FUNCS, s.variable_a)], ['Variable B', P.label_of(P.VARIABLE_FUNCS, s.variable_b)]])}
<p style="color:{SOFT};font-size:8pt;margin-top:24px">Generated by TxBridge {__version__}</p>
</body>""")
    return doc


def _setup_printer(printer: QPagedPaintDevice) -> None:
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                      QMarginsF(16, 14, 16, 14), QPageLayout.Unit.Millimeter))


def _print(doc: QTextDocument, pr: QPagedPaintDevice) -> None:
    # Lay the document out in the printer's own pixel space so nothing is clipped.
    doc.setPageSize(QSizeF(pr.pageLayout().paintRectPixels(pr.resolution()).size()))
    doc.print_(pr)


def export_pdf(m: Model, path: str) -> None:
    pr = QPdfWriter(path)
    pr.setResolution(96)
    _setup_printer(pr)
    _print(build_document(m), pr)


def print_model(m: Model, parent=None) -> bool:
    from PySide6.QtPrintSupport import QPrintDialog
    pr = QPrinter(QPrinter.PrinterMode.ScreenResolution); _setup_printer(pr)
    dlg = QPrintDialog(pr, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return False
    _print(build_document(m), pr)
    return True
