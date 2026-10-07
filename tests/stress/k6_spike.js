import http from "k6/http";
import { check } from "k6";
import { Counter, Rate } from "k6/metrics";

const paths = (__ENV.PDF_FILES || "").split("|").filter(Boolean);
if (paths.length !== 4) {
  throw new Error(
    `Se requieren exactamente 4 PDFs oficiales; se recibieron ${paths.length}.`
  );
}

const pdfs = paths.map((path) => {
  const segments = path.split("/");
  return { name: segments[segments.length - 1], data: open(path, "b") };
});

const baseUrl = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const successfulExtractions = new Rate("successful_extractions");
const controlledRejections = new Rate("controlled_rejections");
const unexpectedFailures = new Counter("unexpected_failures");

http.setResponseCallback(http.expectedStatuses(200, 429, 503));

export const options = {
  scenarios: {
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "10s", target: 100 },
        { duration: "20s", target: 100 },
        { duration: "10s", target: 0 },
      ],
      gracefulRampDown: "0s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<30000"],
    successful_extractions: ["rate>0"],
    unexpected_failures: ["count==0"],
  },
};

export default function () {
  const pdf = pdfs[(__VU + __ITER) % pdfs.length];
  const response = http.post(
    `${baseUrl}/extract`,
    { file: http.file(pdf.data, pdf.name, "application/pdf") },
    { timeout: "30s", tags: { pdf: pdf.name } }
  );

  const success = response.status === 200;
  const rejected = response.status === 429 || response.status === 503;
  successfulExtractions.add(success);
  controlledRejections.add(rejected);
  if (!success && !rejected) {
    unexpectedFailures.add(1);
  }

  check(response, {
    "respuesta controlada": () => success || rejected,
    "contrato JSON válido en 200": (res) => {
      if (!success) return true;
      try {
        const body = res.json();
        return typeof body.content === "string" && Number.isInteger(body.page_count);
      } catch (_) {
        return false;
      }
    },
  });
}
