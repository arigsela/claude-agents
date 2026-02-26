import { NextRequest, NextResponse } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";

export async function GET(req: NextRequest) {
  const authHeader = req.headers.get("Authorization") || "";
  const res = await fetch(`${orchestratorUrl}/auth/me`, {
    headers: authHeader ? { Authorization: authHeader } : {},
  });
  if (!res.ok) {
    return NextResponse.json(
      { error: "Not authenticated" },
      { status: res.status }
    );
  }
  const data = await res.json();
  return NextResponse.json(data);
}
