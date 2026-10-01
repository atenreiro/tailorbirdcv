import sys
import time

import pytest

from autocv import pdf


def test_stalled_word_is_killed_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_CONVERT", "import time; time.sleep(30)")  # stand-in for a Word dialog
    docx = tmp_path / "r.docx"
    docx.write_bytes(b"x")
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="waiting on a dialog"):
        pdf.to_pdf(docx, timeout=1)
    assert time.monotonic() - start < 5


def test_missing_output_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_CONVERT", "import sys; sys.exit('no Word here')")
    docx = tmp_path / "r.docx"
    docx.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="no Word here"):
        pdf.to_pdf(docx, timeout=10)
