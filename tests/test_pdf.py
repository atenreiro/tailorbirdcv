import sys
import time

import pytest

from autocv import pdf


@pytest.fixture
def docx(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCV_WORD_DIR", str(tmp_path / "word"))
    d = tmp_path / "app" / "r.docx"
    d.parent.mkdir()
    d.write_bytes(b"x")
    return d


def fake_word(monkeypatch, code):
    """Stand in for osascript + Word: `code` runs with argv = [docx, pdf] in the work folder."""
    monkeypatch.setattr(pdf, "_command", lambda src, dst: [sys.executable, "-c", code, str(src), str(dst)])


def test_stalled_word_is_killed_with_a_clear_message(docx, monkeypatch):
    fake_word(monkeypatch, "import time; time.sleep(30)")  # stand-in for a Word dialog
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="waiting on a dialog"):
        pdf.to_pdf(docx, timeout=1)
    assert time.monotonic() - start < 5


def test_missing_output_is_reported(docx, monkeypatch):
    fake_word(monkeypatch, "import sys; sys.exit('no Word here')")
    with pytest.raises(RuntimeError, match="no Word here"):
        pdf.to_pdf(docx, timeout=10)


def test_converts_in_one_fixed_folder_and_cleans_up(docx, monkeypatch, tmp_path):
    seen = tmp_path / "seen.txt"
    fake_word(monkeypatch, "import sys, shutil, pathlib; s, d = map(pathlib.Path, sys.argv[1:]);"
                           f"pathlib.Path({str(seen)!r}).write_text(str(s.parent));"
                           "shutil.copyfile(s, d)")
    out = pdf.to_pdf(docx, timeout=10)
    assert out == docx.with_suffix(".pdf") and out.read_bytes() == b"x"
    assert seen.read_text() == str((tmp_path / "word").resolve())  # Word only ever sees this folder
    assert list((tmp_path / "word").iterdir()) == []  # staged copies removed


def test_word_script_never_activates_or_touches_other_documents():
    s = pdf._WORD_JXA
    assert "activate" not in s and "activeDocument" not in s
    assert "open -g -j" in s and "if (!wasRunning) word.quit" in s
