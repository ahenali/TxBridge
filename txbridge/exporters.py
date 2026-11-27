"""Spreadsheet export (CSV / XLSX)."""
from __future__ import annotations

import csv
from typing import Iterable, List

from .storage import Model

SEPARATORS = {"Semicolon": ";", "Comma": ",", "Tab": "\t"}


def table(models: Iterable[Model]) -> List[List[object]]:
    """One row per model, one column per parameter - easy to compare in a spreadsheet."""
    models = list(models)
    header: List[object] = ["Name", "Description", "Notes", "Updated"] + [f"CH{i + 1} name" for i in range(6)]
    if models:
        header += [f"{g}: {lbl}" for g, lbl, _ in models[0].settings.flat()]
    rows: List[List[object]] = [header]
    for m in models:
        rows.append([m.name, m.description, m.notes, m.updated] + [m.channel_names[i] for i in range(6)]
                    + [v for _, _, v in m.settings.flat()])
    return rows


def write_csv(models: Iterable[Model], path: str, sep: str = ";") -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:      # BOM so Excel detects UTF-8
        csv.writer(f, delimiter=sep).writerows(table(models))


def write_xlsx(models: Iterable[Model], path: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    rows = table(models)
    wb = Workbook(); ws = wb.active; ws.title = "Models"
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2B2F36")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "B2"
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(34, max(9, width + 2))
    wb.save(path)
