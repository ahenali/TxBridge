"""Draws the app icon (a stick box with the stick off-centre) and writes the PNG and .ico.

    python packaging/make_icon.py

Needs PySide6 and Pillow.  The output is committed, so you only run this to change the design.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#17171b"))
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    grid = QColor("#ffffff"); grid.setAlpha(70)
    p.setPen(QPen(grid, max(1.0, s * 0.018)))
    inner = QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(inner, s * 0.05, s * 0.05)
    p.drawLine(QPointF(s * 0.5, s * 0.2), QPointF(s * 0.5, s * 0.8))
    p.drawLine(QPointF(s * 0.2, s * 0.5), QPointF(s * 1 - s * 0.2, s * 0.5))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#5aa9f5"))
    p.drawEllipse(QPointF(s * 0.62, s * 0.37), s * 0.095, s * 0.095)
    p.end()
    return img


def main() -> None:
    app = QGuiApplication(sys.argv)                       # noqa: F841  (Qt needs one to paint)
    from PIL import Image
    big = draw(512)
    png = os.path.join(ROOT, "txbridge", "assets", "icon.png")
    os.makedirs(os.path.dirname(png), exist_ok=True)
    big.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(png)
    tmp = os.path.join(ROOT, "packaging", "_icon_512.png")
    big.save(tmp)
    Image.open(tmp).save(os.path.join(ROOT, "packaging", "TxBridge.ico"),
                         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    os.remove(tmp)
    print("wrote", png, "and packaging/TxBridge.ico")


if __name__ == "__main__":
    main()
