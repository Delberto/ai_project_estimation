#!/usr/bin/env python3
"""Genera PDFs sintéticos determinísticos para evals de adjuntos.

Produce en este directorio:
- attach_5kb.pdf
- attach_20kb.pdf
- attach_50kb.pdf
- attach_100kb.pdf

Los binarios no se versionan; el stress runner debe invocar este script
antes de ejecutar escenarios con adjuntos.

Uso:
    uv run python evals/stress/fixtures/build_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

TARGETS: dict[str, int] = {
    "attach_5kb.pdf": 5 * 1024,
    "attach_20kb.pdf": 20 * 1024,
    "attach_50kb.pdf": 50 * 1024,
    "attach_100kb.pdf": 100 * 1024,
}

OUTPUT_DIR = Path(__file__).resolve().parent

FILLER_PREFIX = (
    "Estimador-CAG stress fixture | synthetic PDF attachment | "
    "deterministic corpus for attachment-size evals"
)


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _make_stream_padding(num_bytes: int) -> bytes:
    """Comentarios PDF dentro del stream (no visibles, no alteran el texto)."""
    if num_bytes == 0:
        return b""
    if num_bytes < 2:
        raise ValueError("Stream padding must be at least 2 bytes")

    chunks: list[bytes] = []
    remaining = num_bytes
    while remaining > 0:
        if remaining == 1:
            raise ValueError("Stream padding of 1 byte is invalid")
        if remaining == 2:
            chunks.append(b"%\n")
            remaining = 0
            continue
        body_len = min(remaining - 2, 78)
        chunks.append(b"%" + (b"X" * body_len) + b"\n")
        remaining -= 2 + body_len

    padding = b"".join(chunks)
    if len(padding) != num_bytes:
        raise RuntimeError("Stream padding size mismatch")
    return padding


def _stream_body(*, extra_lines: int, stream_padding: bytes) -> bytes:
    """Contenido del stream page: título + líneas de relleno deterministas."""
    lines = [
        "BT /F1 10 Tf 50 750 Td",
        f"({_escape_pdf_text(FILLER_PREFIX)}) Tj",
        "0 -14 Td",
    ]
    for index in range(extra_lines):
        line = f"{FILLER_PREFIX} | line={index:06d}"
        lines.append(f"({_escape_pdf_text(line)}) Tj")
        lines.append("0 -14 Td")
    lines.append("ET")
    return "\n".join(lines).encode("ascii") + stream_padding


def _render_pdf(*, extra_lines: int, stream_padding: bytes) -> bytes:
    """PDF mínimo válido con xref coherente."""
    stream = _stream_body(extra_lines=extra_lines, stream_padding=stream_padding)
    stream_len = len(stream)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % stream_len + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    parts: list[bytes] = [b"%PDF-1.4\n"]
    offsets: list[int] = []

    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii"))
        parts.append(body)
        parts.append(b"\nendobj\n")

    xref_offset = sum(len(part) for part in parts)
    xref_lines = [b"xref\n", b"0 6\n", b"0000000000 65535 f \n"]
    for offset in offsets:
        xref_lines.append(f"{offset:010d} 00000 n \n".encode("ascii"))

    trailer = (
        b"trailer\n"
        b"<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )

    return b"".join(parts + xref_lines + [trailer])


def build_pdf(*, target_bytes: int) -> bytes:
    """Construye un PDF válido de tamaño exacto ``target_bytes``."""
    extra_lines = 0
    while len(_render_pdf(extra_lines=extra_lines, stream_padding=b"")) > target_bytes:
        extra_lines += 1
        if extra_lines > 10_000:
            raise RuntimeError(f"Cannot shrink PDF below {target_bytes} bytes")

    low = 0
    high = target_bytes
    best_padding = 0
    while low <= high:
        mid = (low + high) // 2
        try:
            padding = _make_stream_padding(mid)
        except ValueError:
            low = mid + 1
            continue

        size = len(_render_pdf(extra_lines=extra_lines, stream_padding=padding))
        if size <= target_bytes:
            best_padding = mid
            low = mid + 1
        else:
            high = mid - 1

    final_padding = _make_stream_padding(best_padding)
    pdf = _render_pdf(extra_lines=extra_lines, stream_padding=final_padding)
    if len(pdf) != target_bytes:
        raise RuntimeError(
            f"Could not hit exact size {target_bytes}; closest={len(pdf)} "
            f"(extra_lines={extra_lines}, padding={best_padding})"
        )
    return pdf


def generate_all(output_dir: Path = OUTPUT_DIR) -> dict[str, int]:
    """Regenera todos los fixtures y devuelve ``{filename: byte_size}``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for filename, target_bytes in TARGETS.items():
        payload = build_pdf(target_bytes=target_bytes)
        path = output_dir / filename
        path.write_bytes(payload)
        written[filename] = len(payload)
    return written


def main() -> None:
    written = generate_all()
    for filename, size in written.items():
        expected = TARGETS[filename]
        status = "ok" if size == expected else "MISMATCH"
        print(f"{filename}: {size} bytes ({status}, target={expected})")


if __name__ == "__main__":
    main()
