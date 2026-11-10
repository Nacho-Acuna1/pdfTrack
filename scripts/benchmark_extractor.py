import argparse
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import statistics
import sys
import time

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

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
    size = len(payload)
    if size == 0:
        parser.error("el archivo PDF está vacío")

    shm = SharedMemory(create=True, size=size)
    try:
        shm.buf[:size] = payload

        # Warm-up run
        extract_pdf_to_markdown(shm.name, size)

        samples = []
        page_count = 0
        for _ in range(args.runs):
            started = time.perf_counter()
            _, page_count = extract_pdf_to_markdown(shm.name, size)
            samples.append((time.perf_counter() - started) * 1000)

        print(
            json.dumps(
                {
                    "file": str(args.pdf),
                    "bytes": size,
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
    finally:
        try:
            shm.close()
        except Exception:
            pass
        try:
            shm.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
