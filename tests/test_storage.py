import csv, os, pytest
from txbridge import protocol as P
from txbridge.storage import Library, Model, Prefs
from txbridge import exporters
from txbridge.outputs import Profile


@pytest.fixture()
def lib(tmp_path):
    return Library(str(tmp_path / "lib.db"))


def test_save_load_search_duplicate_delete(lib):
    s = P.Settings(); s.subtrim[2] = 9
    m = lib.save(Model(name="Trainer", tags=["acro", "foam"], settings=s, channel_names=["Ail", "", "", "", "", ""]))
    got = lib.get(m.id)
    assert got.settings == s and got.tags == ["acro", "foam"] and got.channel_label(0) == "Ail" and got.channel_label(1) == "CH2"
    assert [x.id for x in lib.list(search="foam")] == [m.id] and lib.list(search="zzz") == []
    assert lib.all_tags() == ["acro", "foam"] and lib.list(tag="acro")[0].id == m.id
    d = lib.duplicate(m.id); assert d.id != m.id and d.name.endswith("(copy)")
    lib.delete(m.id); assert lib.get(m.id) is None


def test_snapshots_hidden_and_pruned(lib):
    for i in range(Library.SNAPSHOT_KEEP + 5):
        lib.snapshot(P.Settings(), "Before send")
    assert lib.list() == []
    assert len(lib.list(snapshots=True)) == Library.SNAPSHOT_KEEP


def test_cfg_import_export(lib, tmp_path):
    s = P.Settings(); s.endpoint_max[0] = 111
    m = lib.save(Model(name="x", settings=s)); path = str(tmp_path / "x.cfg")
    lib.export_cfg(m, path); assert os.path.getsize(path) == 67
    assert lib.import_cfg(path).settings == s
    data = bytearray(open(path, "rb").read()); data[3] ^= 1; open(path, "wb").write(data)
    with pytest.raises(P.ChecksumError): lib.import_cfg(path)
    assert lib.import_cfg(path, strict=False)


def test_backup_restore_merge_replace_and_tamper(lib, tmp_path):
    prefs = Prefs(str(tmp_path / "p.json")); prefs.profiles = [Profile(name="Sim A")]
    a = P.Settings(); a.subtrim[0] = 5
    lib.save(Model(name="A", settings=a)); lib.save(Model(name="B"))
    bk = str(tmp_path / "bk.zip"); assert lib.backup(bk, prefs) == 2
    assert lib.restore(bk) == 0                                   # merge: nothing new
    lib.delete(lib.list()[0].id)
    assert lib.restore(bk) == 1 and len(lib.list()) == 2
    lib.save(Model(name="extra")); assert lib.restore(bk, replace=True) == 2 and len(lib.list()) == 2
    import zipfile, json
    with zipfile.ZipFile(bk) as z: blob = z.read("backup.json"); man = z.read("manifest.json")
    with zipfile.ZipFile(str(tmp_path / "bad.zip"), "w") as z:
        z.writestr("backup.json", blob.replace(b'"A"', b'"Z"')); z.writestr("manifest.json", man)
    with pytest.raises(ValueError): lib.restore(str(tmp_path / "bad.zip"))


def test_prefs_roundtrip(tmp_path):
    p = Prefs(str(tmp_path / "p.json")); p["theme"] = "light"; p.profiles.append(Profile(name="Z")); p.save()
    q = Prefs(str(tmp_path / "p.json")); assert q["theme"] == "light" and [x.name for x in q.profiles][-1] == "Z"


def test_csv_and_xlsx(lib, tmp_path):
    lib.save(Model(name="One", settings=P.Settings())); lib.save(Model(name="Two", notes="n;x"))
    ms = lib.list()
    exporters.write_csv(ms, str(tmp_path / "o.csv"), ";")
    rows = list(csv.reader(open(tmp_path / "o.csv", encoding="utf-8-sig"), delimiter=";"))
    assert len(rows) == 3 and rows[0][0] == "Name" and len(rows[0]) == len(rows[1])
    exporters.write_xlsx(ms, str(tmp_path / "o.xlsx"))
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "o.xlsx").active
    assert ws.max_row == 3 and ws.cell(1, 1).value == "Name"
