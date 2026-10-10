"""Tier 2: dependency-free PDF writer produces valid, parseable PDFs."""

import pytest

from mobile_money_system.pdfdoc import build_pdf, receipt_pdf
from mobile_money_system.models import Transaction
from decimal import Decimal

pypdf = pytest.importorskip("pypdf")

from io import BytesIO


def test_pdf_structure_and_text_extraction():
    pdf = build_pdf("TEST RECEIPT", ["Hello (world) \\ backslash", "Amount: USD 1,234.56"])
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    reader = pypdf.PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "TEST RECEIPT" in text
    assert "Hello (world)" in text
    assert "USD 1,234.56" in text


def test_pdf_pagination():
    pdf = build_pdf("LONG", [f"Line {i}" for i in range(100)])
    reader = pypdf.PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 3
    assert "Line 99" in reader.pages[2].extract_text()


def test_receipt_pdf_contents():
    t = Transaction(id="TXN-ABC", sender_phone="+231776000001", receiver_phone="+231776000002",
                    amount=Decimal("250.75"), currency="USD", type="TRANSFER",
                    description="Dinner", status="COMPLETED")
    pdf = receipt_pdf(t, "Alice", "Bob", fee_text="USD 0.00")
    reader = pypdf.PdfReader(BytesIO(pdf))
    text = reader.pages[0].extract_text()
    for expected in ("TXN-ABC", "Alice", "Bob", "250.75", "TRANSFER", "Dinner", "COMPLETED"):
        assert expected in text, expected
