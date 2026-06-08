"""Generate tests/fixtures/sample_portfolio.pdf — a minimal but realistic
single-page PDF describing 2 assets and 1 commercial obligation. Pure stdlib so
it can run in CI without reportlab. Re-run with: python -m tests.fixtures._make_sample_pdf
"""
from __future__ import annotations

from pathlib import Path

LINES = [
    "Vela Onboarding - Asset Portfolio & Commercial Obligations",
    "",
    "ASSET PORTFOLIO",
    "Asset BESS-001 is a battery energy storage system rated at 50 MW / 200 MWh.",
    "BESS-001 uses LFP chemistry, settles at ERCOT node HB_HOUSTON via QSE Vela Energy.",
    "BESS-001 carries a 10 year / 6000 cycle warranty with an 80% capacity guarantee.",
    "BESS-001 was commissioned on 2024-03-15.",
    "",
    "Asset SOLAR-014 is a solar PV plant rated at 25 MW.",
    "SOLAR-014 interconnects at CAISO node SP15 and was commissioned 2023-11-01.",
    "",
    "COMMERCIAL OBLIGATIONS",
    "Seller commits 40 MW of capacity on weekdays from hour 14 to hour 20.",
    "Contract term runs from 2025-01-01 through 2027-12-31.",
    "Shortfall penalty is $150 per MWh; beyond 100 MWh of shortfall the penalty",
    "may be escalated by a factor of up to 2x at the buyer's reasonable discretion.",
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf() -> bytes:
    # Build the page content stream (text positioned with leading via TL/T*).
    parts = ["BT", "/F1 11 Tf", "14 TL", "50 760 Td"]
    for line in LINES:
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n"
    out += b"0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(out)


def main() -> None:
    target = Path(__file__).with_name("sample_portfolio.pdf")
    target.write_bytes(build_pdf())
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
