"""Model library: save, open, compare, export, print, backup."""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import exporters, protocol as P, report
from ..controller import Controller
from ..storage import Model
from .radio_page import ChangesDialog
from .theme import T, sans
from .widgets import button, heading, label, rule

ROW_H = 54


class ModelDelegate(QStyledItemDelegate):
    """Two-line list rows: model name, then type and date."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        p.save()
        r = option.rect.adjusted(2, 1, -2, -1)
        if option.state & QStyle.StateFlag.State_Selected:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("hover")); p.drawRoundedRect(r, 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("hover")); p.drawRoundedRect(r, 6, 6)
        name, meta = index.data(Qt.ItemDataRole.UserRole), index.data(Qt.ItemDataRole.UserRole + 1)
        p.setFont(sans(13, 600)); p.setPen(T.color("text"))
        fm = p.fontMetrics()
        p.drawText(QRect(r.left() + 12, r.top() + 8, r.width() - 24, 20), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, r.width() - 24))
        p.setFont(sans(12)); p.setPen(T.color("text2"))
        fm = p.fontMetrics()
        p.drawText(QRect(r.left() + 12, r.top() + 28, r.width() - 24, 18), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(meta, Qt.TextElideMode.ElideRight, r.width() - 24))
        p.restore()


class LibraryPage(QWidget):
    def __init__(self, ctl: Controller, goto_radio) -> None:
        super().__init__()
        self.ctl, self.goto_radio = ctl, goto_radio
        self.models: List[Model] = []
        root = QVBoxLayout(self); root.setContentsMargins(0, 4, 0, 0); root.setSpacing(16)

        bar = QHBoxLayout(); bar.setSpacing(8)
        bar.addWidget(button("Save current", primary=True, slot=self.save_current))
        bar.addWidget(button("Save as new", slot=lambda: self.save_current(new=True)))
        bar.addWidget(button("Import .cfg\u2026", slot=self.import_cfg))
        ex = button("Export"); m = QMenu(ex)
        m.addAction("Selected model as .cfg\u2026", self.export_cfg)
        m.addAction("Selected model as PDF\u2026", self.export_pdf)
        m.addAction("Print selected model\u2026", self.print_selected)
        m.addSeparator()
        m.addAction("All models as spreadsheet (.xlsx)\u2026", lambda: self.export_sheet("xlsx"))
        m.addAction("All models as CSV\u2026", lambda: self.export_sheet("csv"))
        ex.setMenu(m); bar.addWidget(ex)
        bk = button("Backup"); m2 = QMenu(bk)
        m2.addAction("Back up library\u2026", self.backup); m2.addAction("Restore from backup\u2026", self.restore)
        bk.setMenu(m2); bar.addWidget(bk); bar.addStretch()
        root.addLayout(bar)

        self.pages = QStackedWidget(); root.addWidget(self.pages, 1)

        # empty state
        empty = QWidget(); el = QVBoxLayout(empty); el.setContentsMargins(0, 60, 0, 0); el.setSpacing(6)
        t = heading("No models saved yet"); t.setAlignment(Qt.AlignmentFlag.AlignHCenter); el.addWidget(t)
        d = label("Save what is in the editor now, or import .cfg files from t6config or Digital Radio.", "muted")
        d.setAlignment(Qt.AlignmentFlag.AlignHCenter); d.setWordWrap(True); el.addWidget(d)
        el.addStretch()
        self.pages.addWidget(empty)

        # list + details
        body = QWidget(); bl = QHBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(28)
        left = QVBoxLayout(); left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search name, notes, tags"); self.search.textChanged.connect(self.reload)
        self.tag = QComboBox(); self.tag.currentIndexChanged.connect(self.reload); self.tag.setMinimumWidth(110)
        r = QHBoxLayout(); r.setSpacing(8); r.addWidget(self.search, 1); r.addWidget(self.tag); left.addLayout(r)
        self.list = QListWidget(); self.list.setItemDelegate(ModelDelegate(self.list)); self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentRowChanged.connect(self._select); self.list.itemDoubleClicked.connect(lambda _i: self.load())
        left.addWidget(self.list, 1)
        self.show_snap = QCheckBox("Show automatic backups"); self.show_snap.toggled.connect(self.reload); left.addWidget(self.show_snap)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(320); bl.addWidget(lw)

        self.detail = QWidget(); d = QVBoxLayout(self.detail); d.setContentsMargins(0, 0, 0, 0); d.setSpacing(14)
        d.addWidget(heading("Details"))
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(16); form.setVerticalSpacing(10)
        self.f_name, self.f_desc, self.f_tags = QLineEdit(), QLineEdit(), QLineEdit()
        self.f_tags.setPlaceholderText("comma separated")
        self.f_notes = QPlainTextEdit(); self.f_notes.setFixedHeight(96)
        for t_, w in (("Name", self.f_name), ("Description", self.f_desc), ("Tags", self.f_tags), ("Notes", self.f_notes)):
            lb = label(t_, "muted"); lb.setMinimumWidth(84); form.addRow(lb, w)
        d.addLayout(form)
        self.summary = label("", "hint"); self.summary.setWordWrap(True); d.addWidget(self.summary)
        row = QHBoxLayout(); row.setSpacing(8)
        self.b_save = button("Save details", slot=self.save_details)
        row.addWidget(self.b_save); row.addStretch(); d.addLayout(row)
        d.addWidget(rule())
        row2 = QHBoxLayout(); row2.setSpacing(8)
        self.b_load = button("Load into editor", primary=True, slot=self.load)
        self.b_send = button("Load and send to radio", slot=self.load_and_send)
        self.b_cmp = button("Compare with editor", slot=self.compare)
        for b in (self.b_load, self.b_send, self.b_cmp):
            row2.addWidget(b)
        row2.addStretch(); d.addLayout(row2)
        row3 = QHBoxLayout(); row3.setSpacing(8)
        self.b_dup = button("Duplicate", slot=self.duplicate)
        self.b_del = button("Delete", danger=True, slot=self.delete)
        row3.addWidget(self.b_dup); row3.addWidget(self.b_del); row3.addStretch(); d.addLayout(row3)
        d.addStretch()
        bl.addWidget(self.detail, 1)
        self.pages.addWidget(body)
        self.reload()

    # ------------------------------------------------------------- listing
    def current(self) -> Optional[Model]:
        r = self.list.currentRow()
        return self.models[r] if 0 <= r < len(self.models) else None

    def reload(self, *_a) -> None:
        keep = self.current().id if self.current() else None
        tags = self.ctl.lib.all_tags()
        self.tag.blockSignals(True); cur = self.tag.currentText()
        self.tag.clear(); self.tag.addItem("All tags")
        self.tag.addItems(tags); self.tag.setCurrentText(cur if cur in tags else "All tags"); self.tag.blockSignals(False)
        tag = self.tag.currentText() if self.tag.currentIndex() > 0 else ""
        self.models = self.ctl.lib.list(self.search.text().strip(), tag, self.show_snap.isChecked())
        self.list.blockSignals(True); self.list.clear()
        for m in self.models:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, m.name)
            it.setData(Qt.ItemDataRole.UserRole + 1, f"{P.label_of(P.MODEL_TYPES, m.settings.model_type)}  \u00b7  {m.updated[:16]}"
                       + ("  \u00b7  automatic" if m.kind == "snapshot" else ""))
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self.models:
            idx = next((i for i, m in enumerate(self.models) if m.id == keep), 0)
            self.list.setCurrentRow(idx)
        self._select(self.list.currentRow())

    def _select(self, row: int) -> None:
        m = self.current()
        has = m is not None
        filtered = bool(self.search.text().strip()) or self.tag.currentIndex() > 0 or self.show_snap.isChecked()
        self.pages.setCurrentIndex(1 if (self.models or filtered or self.ctl.lib.list()) else 0)
        self.detail.setVisible(has)
        for w in (self.f_name, self.f_desc, self.f_tags, self.f_notes, self.b_load, self.b_send, self.b_cmp,
                  self.b_save, self.b_dup, self.b_del):
            w.setEnabled(has)
        if not m:
            for w in (self.f_name, self.f_desc, self.f_tags): w.clear()
            self.f_notes.clear(); self.summary.setText(""); return
        self.f_name.setText(m.name); self.f_desc.setText(m.description); self.f_tags.setText(", ".join(m.tags))
        self.f_notes.setPlainText(m.notes)
        s = m.settings
        self.summary.setText(f"{P.label_of(P.MODEL_TYPES, s.model_type)}, {P.label_of(P.STICK_MODES, s.stick_mode)}. "
                             f"Updated {m.updated}, created {m.created}.")
        self.b_send.setEnabled(has and self.ctl.link.connected)

    # ------------------------------------------------------------- actions
    def _snapshot_model(self) -> Model:
        m = self.ctl.model
        return Model(id=m.id, name=m.name or "Untitled", description=m.description, notes=m.notes, tags=list(m.tags),
                     channel_names=list(m.channel_names), settings=self.ctl.edit.copy())

    def save_current(self, new: bool = False) -> None:
        m = self._snapshot_model()
        if new:
            m.id = None
            if self.ctl.lib.list(search=m.name) and any(x.name == m.name for x in self.ctl.lib.list(search=m.name)):
                m.name += " (2)"
        saved = self.ctl.lib.save(m)
        self.ctl.model.id, self.ctl.model.name = saved.id, saved.name
        self.ctl.model_dirty = False; self.ctl.model_changed.emit()
        self.reload(); self.ctl.notice.emit("ok", f"Saved \u201c{saved.name}\u201d to the library.")

    def load(self) -> bool:
        m = self.current()
        if not m: return False
        if self.ctl.is_dirty() and QMessageBox.question(
                self, "Load model", "You have unsent changes in the editor. Replace them?") != QMessageBox.StandardButton.Yes:
            return False
        cm = self.ctl.model
        cm.id, cm.name, cm.description, cm.notes, cm.tags = m.id, m.name, m.description, m.notes, list(m.tags)
        cm.channel_names = list(m.channel_names)
        self.ctl.set_edit(m.settings); self.ctl.model_changed.emit()
        self.goto_radio(); return True

    def load_and_send(self) -> None:
        if self.load():
            self.ctl.send_to_radio()

    def compare(self) -> None:
        m = self.current()
        if m:
            ch = P.diff_settings(self.ctl.edit, m.settings)
            ChangesDialog(self, ch, "Compare", f"{len(ch)} difference(s)" if ch else "Identical to the editor",
                          "Editor", m.name[:24]).exec()

    def save_details(self) -> None:
        m = self.current()
        if m:
            m.name, m.description, m.notes = self.f_name.text(), self.f_desc.text(), self.f_notes.toPlainText()
            m.tags = [t.strip() for t in self.f_tags.text().split(",") if t.strip()]
            self.ctl.lib.save(m)
            if self.ctl.model.id == m.id:
                self.ctl.model.name = m.name; self.ctl.model_changed.emit()
            self.reload()

    def duplicate(self) -> None:
        m = self.current()
        if m: self.ctl.lib.duplicate(m.id); self.reload()

    def delete(self) -> None:
        m = self.current()
        if m and QMessageBox.question(self, "Delete model", f"Delete \u201c{m.name}\u201d from the library?") == QMessageBox.StandardButton.Yes:
            self.ctl.lib.delete(m.id)
            if self.ctl.model.id == m.id: self.ctl.model.id = None
            self.reload()

    # ------------------------------------------------------------- files
    def import_cfg(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import settings", "", "t6config files (*.cfg);;All files (*)")
        n, bad = 0, []
        for p in paths:
            try:
                self.ctl.lib.import_cfg(p); n += 1
            except P.ChecksumError:
                if QMessageBox.question(self, "Checksum mismatch", f"{os.path.basename(p)} is damaged or was edited by hand. "
                                        "Import it anyway?") == QMessageBox.StandardButton.Yes:
                    self.ctl.lib.import_cfg(p, strict=False); n += 1
            except Exception as exc:                                     # noqa: BLE001
                bad.append(f"{os.path.basename(p)}: {exc}")
        self.reload()
        if bad: QMessageBox.warning(self, "Import", "\n".join(bad))
        if n: self.ctl.notice.emit("ok", f"Imported {n} file(s).")

    def export_cfg(self) -> None:
        m = self.current()
        if m:
            p, _ = QFileDialog.getSaveFileName(self, "Export settings", m.name + ".cfg", "t6config files (*.cfg)")
            if p: self.ctl.lib.export_cfg(m, p)

    def export_pdf(self) -> None:
        m = self.current()
        if m:
            p, _ = QFileDialog.getSaveFileName(self, "Export PDF", m.name + ".pdf", "PDF (*.pdf)")
            if p: report.export_pdf(m, p); self.ctl.notice.emit("ok", "PDF saved.")

    def print_selected(self) -> None:
        m = self.current()
        if m: report.print_model(m, self)

    def export_sheet(self, kind: str) -> None:
        ms = self.ctl.lib.list()
        if not ms:
            QMessageBox.information(self, "Export", "The library is empty."); return
        p, _ = QFileDialog.getSaveFileName(self, "Export models", "txbridge-models." + kind, "Spreadsheet (*.%s)" % kind)
        if not p: return
        if kind == "csv": exporters.write_csv(ms, p, self.ctl.prefs["csv_separator"])
        else: exporters.write_xlsx(ms, p)
        self.ctl.notice.emit("ok", f"Exported {len(ms)} model(s).")

    def backup(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Back up library", "txbridge-backup.zip", "Backup (*.zip)")
        if p:
            n = self.ctl.lib.backup(p, self.ctl.prefs); self.ctl.notice.emit("ok", f"Backed up {n} model(s) and profiles.")

    def restore(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "Backup (*.zip)")
        if not p: return
        box = QMessageBox(self); box.setWindowTitle("Restore backup"); box.setText("How should the backup be applied?")
        merge = box.addButton("Merge (keep what I have)", QMessageBox.ButtonRole.AcceptRole)
        rep = box.addButton("Replace library", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel); box.exec()
        if box.clickedButton() not in (merge, rep): return
        try:
            n = self.ctl.lib.restore(p, replace=box.clickedButton() is rep, prefs=self.ctl.prefs)
        except Exception as exc:                                         # noqa: BLE001
            QMessageBox.critical(self, "Restore", str(exc)); return
        self.reload(); self.ctl.notice.emit("ok", f"Restored {n} model(s).")
