"""Data location, preferences and the model library (SQLite)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from . import __version__
from . import protocol as P
from .outputs import Profile


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """Portable mode: a 'data' folder next to the program wins."""
    override = os.environ.get("TXBRIDGE_DATA")
    if override:
        path = override
    elif os.path.isdir(os.path.join(app_dir(), "data")):
        path = os.path.join(app_dir(), "data")
    elif sys.platform == "win32":
        path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TxBridge")
    else:
        path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "txbridge")
    os.makedirs(path, exist_ok=True)
    return path


def make_portable() -> str:
    """Copy current data next to the program and switch to it from the next start."""
    src, dst = data_dir(), os.path.join(app_dir(), "data")
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


def atomic_write(path: str, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ------------------------------------------------------------------ prefs
DEFAULT_PREFS = {
    "theme": "system", "last_port": "", "autoconnect": True, "auto_read": True,
    "update_mode": "manual", "csv_separator": ";", "show_values": True,
    "output_enabled": False, "profile": "Default", "autoswitch": True,
    "geometry": "", "setup_nudge_dismissed": False,
}


class Prefs:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(data_dir(), "preferences.json")
        self.data: dict = dict(DEFAULT_PREFS)
        self.profiles: List[Profile] = []
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.data.update({k: v for k, v in raw.get("prefs", {}).items()})
            self.profiles = [Profile.from_dict(d) for d in raw.get("profiles", [])]
        except (OSError, ValueError):
            pass
        if not self.profiles:
            self.profiles = [Profile(name="Default")]

    def save(self) -> None:
        raw = {"prefs": self.data, "profiles": [p.to_dict() for p in self.profiles]}
        atomic_write(self.path, json.dumps(raw, indent=2).encode("utf-8"))

    def __getitem__(self, k): return self.data.get(k, DEFAULT_PREFS.get(k))
    def __setitem__(self, k, v): self.data[k] = v

    def profile(self, name: str) -> Profile:
        for p in self.profiles:
            if p.name == name:
                return p
        return self.profiles[0]


# ------------------------------------------------------------------ library
@dataclass
class Model:
    id: Optional[int] = None
    name: str = "New model"
    description: str = ""
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    channel_names: List[str] = field(default_factory=lambda: [""] * 6)
    settings: P.Settings = field(default_factory=P.Settings)
    created: str = ""
    updated: str = ""
    kind: str = "model"          # 'model' or 'snapshot' (automatic safety copy)

    def channel_label(self, ch: int) -> str:
        return self.channel_names[ch] or f"CH{ch + 1}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Library:
    SNAPSHOT_KEEP = 25

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(data_dir(), "library.db")
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS models(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT DEFAULT '',
            notes TEXT DEFAULT '', tags TEXT DEFAULT '', channel_names TEXT DEFAULT '[]',
            cfg BLOB NOT NULL, created TEXT, updated TEXT, kind TEXT DEFAULT 'model')""")
        self.db.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> Model:
        names = (json.loads(r["channel_names"] or "[]") + [""] * 6)[:6]
        return Model(id=r["id"], name=r["name"], description=r["description"], notes=r["notes"],
                     tags=[t for t in (r["tags"] or "").split(",") if t], channel_names=names,
                     settings=P.decode_cfg(bytes(r["cfg"]), strict=False),
                     created=r["created"], updated=r["updated"], kind=r["kind"])

    def save(self, m: Model) -> Model:
        cfg = P.encode_cfg(m.settings)
        m.updated = _now()
        vals = (m.name.strip() or "Untitled", m.description, m.notes, ",".join(m.tags),
                json.dumps(m.channel_names), cfg, m.updated, m.kind)
        if m.id is None:
            m.created = m.updated
            cur = self.db.execute("INSERT INTO models(name,description,notes,tags,channel_names,cfg,updated,kind,created)"
                                  " VALUES(?,?,?,?,?,?,?,?,?)", vals + (m.created,))
            m.id = cur.lastrowid
        else:
            self.db.execute("UPDATE models SET name=?,description=?,notes=?,tags=?,channel_names=?,cfg=?,updated=?,kind=? "
                            "WHERE id=?", vals + (m.id,))
        self.db.commit()
        return m

    def get(self, id_: int) -> Optional[Model]:
        r = self.db.execute("SELECT * FROM models WHERE id=?", (id_,)).fetchone()
        return self._row(r) if r else None

    def delete(self, id_: int) -> None:
        self.db.execute("DELETE FROM models WHERE id=?", (id_,))
        self.db.commit()

    def duplicate(self, id_: int) -> Optional[Model]:
        m = self.get(id_)
        if not m:
            return None
        m.id, m.name, m.kind = None, m.name + " (copy)", "model"
        return self.save(m)

    def list(self, search: str = "", tag: str = "", snapshots: bool = False) -> List[Model]:
        q = "SELECT * FROM models WHERE 1=1"
        args: list = []
        if not snapshots:
            q += " AND kind='model'"
        if search:
            q += " AND (name LIKE ? OR description LIKE ? OR notes LIKE ? OR tags LIKE ?)"
            args += [f"%{search}%"] * 4
        q += " ORDER BY datetime(updated) DESC, id DESC"
        out = [self._row(r) for r in self.db.execute(q, args)]
        if tag:
            out = [m for m in out if tag in m.tags]
        return out

    def all_tags(self) -> List[str]:
        return sorted({t for m in self.list() for t in m.tags})

    def snapshot(self, settings: P.Settings, why: str) -> Model:
        m = Model(name=f"{why} {_now()}", settings=settings.copy(), kind="snapshot", tags=["auto"])
        self.save(m)
        old = self.db.execute("SELECT id FROM models WHERE kind='snapshot' ORDER BY id DESC LIMIT -1 OFFSET ?",
                              (self.SNAPSHOT_KEEP,)).fetchall()
        for r in old:
            self.db.execute("DELETE FROM models WHERE id=?", (r["id"],))
        self.db.commit()
        return m

    # ---- files
    def import_cfg(self, path: str, strict: bool = True) -> Model:
        with open(path, "rb") as f:
            data = f.read()
        st = P.decode_cfg(data, strict=strict)
        m = Model(name=os.path.splitext(os.path.basename(path))[0], settings=st, tags=["imported"])
        return self.save(m)

    @staticmethod
    def export_cfg(m: Model, path: str) -> None:
        with open(path, "wb") as f:
            f.write(P.encode_cfg(m.settings))

    # ---- backup / restore
    def backup(self, path: str, prefs: Optional[Prefs] = None) -> int:
        models = self.list(snapshots=True)
        body = {"app": "TxBridge", "version": __version__, "created": _now(),
                "models": [{"name": m.name, "description": m.description, "notes": m.notes, "tags": m.tags,
                            "channel_names": m.channel_names, "kind": m.kind, "created": m.created,
                            "updated": m.updated, "cfg": base64.b64encode(P.encode_cfg(m.settings)).decode()}
                           for m in models],
                "profiles": [p.to_dict() for p in (prefs.profiles if prefs else [])]}
        blob = json.dumps(body, indent=1).encode("utf-8")
        manifest = {"sha256": hashlib.sha256(blob).hexdigest(), "models": len(models), "created": body["created"]}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("backup.json", blob)
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
        return len(models)

    def restore(self, path: str, replace: bool = False, prefs: Optional[Prefs] = None) -> int:
        with zipfile.ZipFile(path) as z:
            blob = z.read("backup.json")
            manifest = json.loads(z.read("manifest.json"))
        if hashlib.sha256(blob).hexdigest() != manifest.get("sha256"):
            raise ValueError("This backup is damaged (checksum mismatch); nothing was restored.")
        body = json.loads(blob)
        models = [Model(name=d["name"], description=d.get("description", ""), notes=d.get("notes", ""),
                        tags=d.get("tags", []), channel_names=d.get("channel_names", [""] * 6),
                        settings=P.decode_cfg(base64.b64decode(d["cfg"]), strict=False), kind=d.get("kind", "model"))
                  for d in body["models"]]
        if replace:
            self.db.execute("DELETE FROM models")
        existing = {(m.name, P.encode_cfg(m.settings)) for m in self.list(snapshots=True)}
        n = 0
        for m in models:
            if (m.name, P.encode_cfg(m.settings)) in existing:
                continue                                     # merge: skip exact duplicates
            self.save(m); n += 1
        if prefs is not None and body.get("profiles"):
            if replace:
                prefs.profiles = [Profile.from_dict(d) for d in body["profiles"]]
            else:
                have = {p.name for p in prefs.profiles}
                prefs.profiles += [Profile.from_dict(d) for d in body["profiles"] if d["name"] not in have]
            prefs.save()
        return n
