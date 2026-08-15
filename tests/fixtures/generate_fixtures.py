"""Generate static test fixtures (PDFs + offline search results).

Run: uv run python tests/fixtures/generate_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent


def make_text_pdf(path: Path) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Master of Cybersecurity Curriculum")
    text = (
        "This document describes the curriculum of a Master of Cybersecurity program.\n\n"
        "Core courses include network security, cryptography, secure software development,\n"
        "digital forensics and penetration testing. Students complete 120 credits.\n\n"
        "Program Overview\n"
        "The program prepares students for careers in information security.\n\n"
        "Learning Outcomes\n"
        "Graduates will be able to design and evaluate secure systems.\n"
    )
    page.insert_textbox(
        fitz.Rect(72, 100, 540, 720),
        text,
        fontsize=11,
        fontname="helv",
        lineheight=1.4,
    )
    doc.set_metadata({"title": "Master of Cybersecurity Curriculum", "author": "Test University"})
    doc.save(path)


def make_scanned_pdf(path: Path) -> None:
    import fitz  # PyMuPDF

    # Build a scanned-style PDF: render text to an image, then embed the image
    # with no text layer (as a real scanner produces).
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=612, height=792)
    temp_page.insert_text(
        (72, 72),
        "CYBERSECURITY SYLLABUS",
        fontsize=16,
        fontname="helv",
    )
    temp_page.insert_text(
        (72, 110),
        "This scanned document is an image of a syllabus page.",
        fontsize=9,
        fontname="helv",
    )
    temp_page.get_pixmap(dpi=150).save(str(path.parent / "_scan_raw.png"))
    temp_doc.close()

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), filename=str(path.parent / "_scan_raw.png"))
    doc.set_metadata({"title": "Scanned Syllabus"})
    doc.save(path)
    (path.parent / "_scan_raw.png").unlink(missing_ok=True)


def make_empty_pdf(path: Path) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    doc.new_page()
    doc.save(path)


def make_corrupted_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\ncorrupted garbage not a real pdf\n%%EOF broken")


def write_search_fixture(path: Path) -> None:
    fixture = {
        "cybersecurity curriculum": [
            {
                "title": "Master of Cybersecurity Curriculum",
                "url": "https://example.edu/cybersecurity/curriculum.pdf",
                "snippet": "Official curriculum of the Master of Cybersecurity program.",
            },
            {
                "title": "Cybersecurity Degree Requirements",
                "url": "https://example.edu/cyber/degree-requirements.pdf",
                "snippet": "Degree requirements and course catalog for cybersecurity.",
            },
        ],
        "cafeteria": [
            {
                "title": "University Cafeteria Regulations",
                "url": "https://example.edu/cafeteria/regulations.pdf",
                "snippet": "Food service hours, meal plans and cafeteria regulations.",
            },
            {
                "title": "Campus Dining Guide",
                "url": "https://example.edu/dining/guide.pdf",
                "snippet": "A guide to campus dining options.",
            },
        ],
        "network security": [
            {
                "title": "Network Security Course Syllabus",
                "url": "https://example.edu/cs/network-security-syllabus.pdf",
                "snippet": "Syllabus covering firewalls, IDS/IPS, VPNs and labs.",
            },
        ],
        "duplicate source": [
            {
                "title": "Duplicate Curriculum",
                "url": "https://example.edu/cybersecurity/curriculum.pdf",
                "snippet": "Same file as the master curriculum (duplicate URL).",
            },
        ],
    }
    path.write_text(json.dumps(fixture, indent=2))


def make_simple_pdf(path: Path, title: str, body: str) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), title)
    page.insert_textbox(
        fitz.Rect(72, 100, 540, 720),
        body,
        fontsize=11,
        fontname="helv",
        lineheight=1.4,
    )
    doc.set_metadata({"title": title})
    doc.save(path)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_text_pdf(FIXTURES / "text_pdf.pdf")
    make_scanned_pdf(FIXTURES / "scanned_pdf.pdf")
    make_empty_pdf(FIXTURES / "empty_pdf.pdf")
    make_corrupted_pdf(FIXTURES / "corrupted.pdf")
    make_simple_pdf(
        FIXTURES / "network_security.pdf",
        "Network Security Course Syllabus",
        "This syllabus covers network security fundamentals: firewalls, IDS/IPS, "
        "VPNs and hands-on labs. Weekly topics and grading are described.",
    )
    make_simple_pdf(
        FIXTURES / "cafeteria.pdf",
        "University Cafeteria Regulations",
        "This document regulates food service hours, meal pricing, menu rotation "
        "and student meal plans at the university cafeteria.",
    )
    write_search_fixture(FIXTURES / "search_results.json")
    print("fixtures written to", FIXTURES)


if __name__ == "__main__":
    main()
