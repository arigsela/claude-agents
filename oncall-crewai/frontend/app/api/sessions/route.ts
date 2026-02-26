import { NextRequest, NextResponse } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";
const apiKey = (process.env.ORCHESTRATOR_API_KEY || "").split(",")[0].trim();

function buildHeaders(req: NextRequest): Record<string, string> {
  // Forward JWT from client if present, otherwise fall back to API key
  const clientAuth = req.headers.get("Authorization");
  if (clientAuth) return { Authorization: clientAuth };
  return apiKey ? { "X-API-Key": apiKey } : {};
}

export async function GET(req: NextRequest) {
  const res = await fetch(`${orchestratorUrl}/sessions`, {
    headers: buildHeaders(req),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
