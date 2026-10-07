import argparse
import json
import statistics
import time
from pathlib import Path

from App.infrastructure.pymupdf_extractor import extract_pdf_to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Microbenchmark repetible del extractor CPU (sin HTTP)."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--runs", type=int, default=30)
    args = parser.parse_args()

    if not args.pdf.is_file():
        parser.error(f"no existe el PDF: {args.pdf}")
    if args.runs < 1:
        parser.error("--runs debe ser mayor que cero")

    payload = args.pdf.read_bytes()
    extract_pdf_to_markdown(payload)
    samples = []
    page_count = 0
    for _ in range(args.runs):
        started = time.perf_counter()
        _, page_count = extract_pdf_to_markdown(payload)
        samples.append((time.perf_counter() - started) * 1000)

    print(
        json.dumps(
            {
                "file": str(args.pdf),
                "bytes": len(payload),
                "pages": page_count,
                "runs": args.runs,
                "milliseconds": {
                    "mean": round(statistics.fmean(samples), 3),
                    "median": round(statistics.median(samples), 3),
                    "min": round(min(samples), 3),
                    "max": round(max(samples), 3),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
