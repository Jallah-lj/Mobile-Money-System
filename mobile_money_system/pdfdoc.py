"""Minimal dependency-free PDF writer.

Builds valid single- or multi-page PDF 1.4 documents (A4, Helvetica) from
plain text lines — used for transaction receipts and account statements
without pulling in a heavy PDF library.
"""

from typing import Iterable, List, Optional

PAGE_WIDTH = 595   # A4 in points
PAGE_HEIGHT = 842
MARGIN_X = 50
TOP_Y = 790
TITLE_Y = 800
LINES_PER_PAGE = 46


def _escape(text: str) -> str:
    """Escape a string for a PDF literal string."""
    return (str(text)
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\r", " ")
            .replace("\n", " "))


def _paginate(lines: List[str]) -> List[List[str]]:
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)]
    return pages or [[]]


def build_pdf(title: str, lines: Iterable[str], font_size: int = 10, leading: int = 14) -> bytes:
    """Build a PDF document. `title` prints on the first page; `lines` are body text."""
    body = [_escape(line) for line in lines]
    pages = _paginate(body)

    objects: List[bytes] = []  # index + 1 == object number

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font_obj = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_obj = add(b"")  # placeholder, filled once page objects exist

    content_objs = []
    for page_idx, page_lines in enumerate(pages):
        parts = []
        if page_idx == 0:
            parts.append(f"BT /F1 16 Tf {MARGIN_X} {TITLE_Y} Td ({_escape(title)}) Tj ET")
            parts.append(f"BT /F1 {font_size} Tf {MARGIN_X} {TITLE_Y - 24} Td ( ) Tj ET")
        y = TOP_Y - (30 if page_idx == 0 else 0)
        for line in page_lines:
            parts.append(f"BT /F1 {font_size} Tf {MARGIN_X} {y} Td ({line}) Tj ET")
            y -= leading
        stream = "\n".join(parts).encode("latin-1", "replace")
        content_objs.append(add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"))

    page_objs = []
    for idx in range(len(pages)):
        page_objs.append(add(
            (f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
             f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_objs[idx]} 0 R >>").encode()))

    kids = " ".join(f"{p} 0 R" for p in page_objs)
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_objs)} >>".encode()
    catalog_obj = add(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode())

    # Serialize with a cross-reference table
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_obj} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF").encode()
    return bytes(out)


def receipt_pdf(transaction, sender_name: str = "System", receiver_name: str = "System",
                fee_text: str = "") -> bytes:
    """Build a one-page PDF receipt for a Transaction."""
    lines = [
        "",
        f"Transaction ID : {transaction.id}",
        f"Date (UTC)     : {transaction.timestamp.replace('T', ' ')}",
        f"Type           : {transaction.type}",
        f"Amount         : {transaction.currency} {float(transaction.amount):,.2f}",
    ]
    if fee_text:
        lines.append(f"Fee            : {fee_text}")
    lines += [
        f"From           : {sender_name} ({transaction.sender_phone})",
        f"To             : {receiver_name} ({transaction.receiver_phone})",
        f"Description    : {transaction.description or '-'}",
        f"Status         : {transaction.status}",
        "",
        "Thank you for using the Mobile Money System.",
    ]
    return build_pdf("TRANSACTION RECEIPT", lines)
