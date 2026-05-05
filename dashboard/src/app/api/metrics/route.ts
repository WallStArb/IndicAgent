import { NextRequest, NextResponse } from "next/server";

const PROMETHEUS_API =
  `${process.env.PROMETHEUS_URL ?? "http://localhost:9090"}/api/v1/query`;

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const query = searchParams.get("query");

  if (!query) {
    return NextResponse.json({ error: "Query parameter is required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${PROMETHEUS_API}?query=${encodeURIComponent(query)}`);
    if (!res.ok) {
      console.error(`Prometheus returned ${res.status}: ${res.statusText}`);
      return NextResponse.json(
        { error: "Failed to fetch metrics from upstream" },
        { status: res.status >= 500 ? 502 : res.status }
      );
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    console.error("Metrics proxy error:", e);
    return NextResponse.json({ error: "Failed to fetch metrics" }, { status: 500 });
  }
}
