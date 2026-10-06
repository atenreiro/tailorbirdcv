"""Identify a PDF: sent copies record their fingerprints, and any PDF is matched back to its application by
exact file, by the PDF's own ids (a re-saved copy), or by text. Fictional data only."""

import base64

import pytest

from tailorbirdcv import identify
from test_freeze_history import env  # noqa: F401 — the application fixture (fake PDF engine)


def make_pdf(text: str, doc_id: str | None = None, pdf_id: str | None = None, producer: str = "Word") -> bytes:
    """A minimal real PDF with extractable text, an optional XMP DocumentID and trailer /ID."""
    lines = " ".join(f"({w}) Tj 0 -14 Td" for w in text.split(". "))
    content = f"BT /F1 11 Tf 50 750 Td {lines} ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R" + (b" /Metadata 6 0 R" if doc_id else b"") + b" >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    if doc_id:
        xmp = (f'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
               f'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
               f'xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
               f'<xmpMM:DocumentID>uuid:{doc_id}</xmpMM:DocumentID><pdf:Producer>{producer}</pdf:Producer>'
               f'</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>').encode()
        objects.append(b"<< /Type /Metadata /Subtype /XML /Length %d >>\nstream\n" % len(xmp) + xmp + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    trailer_id = f" /ID [<{pdf_id}> <{pdf_id}>]".encode() if pdf_id else b""
    out += b"trailer\n<< /Size %d /Root 1 0 R" % (len(objects) + 1) + trailer_id + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


RESUME = ("Jane Example. Detection engineering lead at Example Capital. Cut false positives by over 65 percent. "
          "Built the threat hunting programme. Led a team of 5 engineers protecting 20M customers")
OTHER = "Sam Sample. Pastry chef at Example Bakery. Baked bread every morning. Ran the kitchen for ten years"


def test_fingerprint_reads_the_pdfs_own_ids():
    pdf = make_pdf(RESUME, doc_id="E002BDE6-7326-4FA6-A9EC-EBD111B82644", pdf_id="ab12cd34")
    fp = identify.fingerprint(pdf)
    assert fp["sha256"] == identify.sha256(pdf) and len(fp["sha256"]) == 64
    assert fp["document_id"] == "e002bde6-7326-4fa6-a9ec-ebd111b82644"  # "uuid:" dropped, lower case
    assert fp["pdf_id"] == "ab12cd34"
    assert identify.fingerprint(b"not a pdf")["document_id"] is None


def test_match_prefers_exact_then_same_document_then_text():
    sent = make_pdf(RESUME, doc_id="11111111-2222-3333-4444-555555555555", pdf_id="aa")
    other = make_pdf(OTHER, doc_id="99999999-2222-3333-4444-555555555555", pdf_id="bb")
    cands = [{"app_id": "a", "kind": "sent", "read": lambda: sent, "fingerprint": None},
             {"app_id": "b", "kind": "sent", "read": lambda: other, "fingerprint": None}]
    assert [(m["app_id"], m["match"]) for m in identify.match(sent, cands)["matches"]] == [("a", "exact")]
    resaved = make_pdf(RESUME, doc_id="11111111-2222-3333-4444-555555555555", pdf_id="cc", producer="Acrobat")
    assert [(m["app_id"], m["match"]) for m in identify.match(resaved, cands)["matches"]] == [("a", "document")]
    retyped = make_pdf(RESUME.replace("programme", "program"))  # no ids at all: only the text is left
    (m,) = identify.match(retyped, cands)["matches"]
    assert m["app_id"] == "a" and m["match"] == "text" and 0.9 < m["score"] < 1
    assert identify.match(make_pdf("Completely unrelated words here"), cands)["matches"] == []


def test_freezing_records_fingerprints_and_identify_finds_the_sent_copy(env, monkeypatch):  # noqa: F811
    client, store, app_id, _ = env
    from tailorbirdcv import pdf as pdfmod
    sent_pdf = make_pdf(RESUME, doc_id="0f0f0f0f-2222-3333-4444-555555555555", pdf_id="dd")

    def real_looking_pdf(docx, pdf=None, timeout=0, engine=None):
        out = pdf or docx.with_suffix(".pdf")
        out.write_bytes(sent_pdf)
        return out
    monkeypatch.setattr(pdfmod, "to_pdf", real_looking_pdf)
    data = client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true").json()
    (copy,) = data["sent"]
    fp = copy["fingerprints"]["Jane_Example_Resume.pdf"]
    assert fp["sha256"] == identify.sha256(sent_pdf) and fp["document_id"].startswith("0f0f0f0f")
    assert len(copy["fingerprints"]["Jane_Example_Resume.docx"]["sha256"]) == 64

    res = client.post("/api/identify", json={"filename": "x.pdf", "data": base64.b64encode(sent_pdf).decode()}).json()
    assert res["sha256"] == fp["sha256"]
    (m,) = res["matches"]  # the identical current build is folded into its sent copy
    assert (m["app_id"], m["kind"], m["match"], m["snapshot"]) == (app_id, "sent", "exact", copy["id"])
    assert m["company"] == "Example Capital" and "read" not in m and "fingerprint" not in m


def test_copies_frozen_before_fingerprints_still_identify(env):  # noqa: F811
    client, store, app_id, _ = env
    client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
    (copy,) = store.sent_copies(app_id)
    folder = store.sent_dir(app_id) / copy["id"]
    record = folder / "sent.json"
    record.chmod(0o644)
    import json
    old = json.loads(record.read_text())
    old.pop("fingerprints")
    record.write_text(json.dumps(old))
    pdf = (folder / "Jane_Example_Resume.pdf").read_bytes()
    (filled,) = store.sent_copies(app_id, fingerprints=True)
    assert filled["fingerprints"]["Jane_Example_Resume.pdf"]["sha256"] == identify.sha256(pdf)
    assert "fingerprints" not in json.loads(record.read_text())  # worked out, never written back
    assert store.identify(pdf)["matches"][0]["snapshot"] == copy["id"]


@pytest.mark.parametrize("body,detail", [({"data": "%%%"}, "couldn't be read"),
                                         ({"data": base64.b64encode(b"PK\x03\x04 a docx").decode()}, "isn't a PDF")])
def test_identify_refuses_what_isnt_a_pdf(env, body, detail):  # noqa: F811
    client, *_ = env
    res = client.post("/api/identify", json=body)
    assert res.status_code == 422 and detail in res.json()["detail"]
