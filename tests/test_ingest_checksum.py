"""Testing & QA (Puja Dey): checksum idempotency basis (ING-4) and schema recognition (ING-1).

Bronze skips a file whose SHA-256 checksum is already in the manifest, so the checksum must depend
only on the file's bytes, never on its name. Files are recognised by their columns/content, so the
hidden test drop can arrive with any file names.
"""
import hashlib
import shutil

from pipeline import contracts
from pipeline.bronze.ingest import sha256, sniff


def test_same_content_different_name_gives_same_checksum(tmp_path):
    a = tmp_path / "encounters_20260114.csv"
    a.write_text("a,b\n1,2\n")
    b = tmp_path / "redelivered_copy.csv"
    shutil.copy(a, b)
    assert sha256(a) == sha256(b)


def test_one_changed_value_changes_checksum(tmp_path):
    a = tmp_path / "x.csv"
    a.write_text("a,b\n1,2\n")
    b = tmp_path / "y.csv"
    b.write_text("a,b\n1,3\n")
    assert sha256(a) != sha256(b)


def test_checksum_matches_hashlib_for_large_file(tmp_path):
    data = b"episcope" * 300_000  # about 2.4 MB, crosses the 1 MB read-chunk boundary
    p = tmp_path / "big.csv"
    p.write_bytes(data)
    assert sha256(p) == hashlib.sha256(data).hexdigest()


def test_csv_is_recognised_by_columns_not_by_name(tmp_path):
    header = ",".join(contracts.SOURCES["encounters"]) + "\n"
    p1 = tmp_path / "encounters.csv"
    p1.write_text(header)
    p2 = tmp_path / "zzz_unknown_name.csv"
    p2.write_text(header)
    assert sniff(p1) == sniff(p2) == "encounters"


def test_json_is_recognised_by_content(tmp_path):
    topo = tmp_path / "anything.json"
    topo.write_text('{"type": "Topology", "objects": {}}')
    weather = tmp_path / "anything_else.json"
    weather.write_text('{"latitude": 22.3, "daily": {"time": []}}')
    assert sniff(topo) == "geometry"
    assert sniff(weather) == "weather"


def test_unknown_or_broken_files_are_not_guessed(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json")
    assert sniff(txt) is None
    assert sniff(empty) is None
    assert sniff(broken) is None
