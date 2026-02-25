import { NextRequest, NextResponse } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";
const apiKey = (process.env.ORCHESTRATOR_API_KEY || "").split(",")[0].trim();

export async function GET(_req: NextRequest) {
  const res = await fetch(`${orchestratorUrl}/sessions`, {
    headers: apiKey ? { "X-API-Key": apiKey } : {},
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
