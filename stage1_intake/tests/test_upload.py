"""Chat file upload: .md/.pptx feed the agent and requirements_markdown, .csv -> reference_files."""

import base64
import json
import zipfile
from unittest.mock import MagicMock

import app as intake_app

SLIDE = ('<p:sld xmlns:a="a" xmlns:p="p"><p:cSld><p:spTree>'
         '<a:p><a:r><a:t>Coolant: PG25</a:t></a:r></a:p>'
         '<a:p><a:r><a:t>Flow 2 L/min &amp; 25 C inlet</a:t></a:r></a:p>'
         '</p:spTree></p:cSld></p:sld>')


def _pptx(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", SLIDE)
        z.writestr("ppt/slides/slide2.xml", SLIDE.replace("PG25", "water"))
        z.writestr("ppt/media/image1.png", b"\x89PNG fake")
    return path


def test_upload_md_pptx_ppt_csv_then_dashboard_payload(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    md = src / "notes.md"
    md.write_text("# Specs\nGPU power 554 W")
    deck = _pptx(src / "deck.pptx")
    legacy = src / "old.ppt"
    legacy.write_bytes(b"\xd0\xcf")
    csv = src / "power_map.csv"
    csv.write_text("x,y,w\n0,0,48\n")

    results = list(intake_app.on_upload(
        [str(md), str(deck), str(legacy), str(csv)], None, None,
        "mock", tmp_path / "sessions"))
    agent, chat = results[-1][0], results[-1][1]
    contents = [m["content"] for m in chat]

    assert "Uploaded notes.md" in contents
    assert "Uploaded deck.pptx (2 slides)" in contents
    assert "old.ppt: Please save as .pptx" in contents
    assert "Uploaded power_map.csv (reference file)" in contents
    uploads = agent.session.dir / "uploads"
    assert (uploads / "deck_media" / "image1.png").is_file()
    assert (uploads / "power_map.csv").is_file()

    agent.session.finalized = True
    (agent.session.dir / "requirements_final.json").write_text('{"finalized": true}')
    opener = MagicMock()
    assert "Modelling started" in intake_app.start_modelling(agent, opener=opener)
    body = json.loads(opener.call_args[0][0].data)
    assert body["requirements_final"] == {"finalized": True}
    doc = body["requirements_markdown"]
    assert "## notes.md\n\n# Specs" in doc
    assert "## deck.pptx" in doc and "Flow 2 L/min & 25 C inlet" in doc
    assert body["reference_files"] == [{
        "name": "power_map.csv",
        "content_base64": base64.b64encode(csv.read_bytes()).decode()}]
