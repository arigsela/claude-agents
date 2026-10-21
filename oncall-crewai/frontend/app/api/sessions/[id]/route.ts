import { NextRequest, NextResponse } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";
const apiKey = (process.env.ORCHESTRATOR_API_KEY || "").split(",")[0].trim();

function buildHeaders(req: NextRequest): Record<string, string> {
  const clientAuth = req.headers.get("Authorization");
  if (clientAuth) return { Authorization: clientAuth };
  return apiKey ? { "X-API-Key": apiKey } : {};
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${orchestratorUrl}/sessions/${id}`, {
    headers: buildHeaders(req),
  });
  if (!res.ok) {
    return NextResponse.json(
      { error: "Session not found" },
      { status: res.status }
    );
  }
  const data = await res.json();
  return NextResponse.json(data);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${orchestratorUrl}/sessions/${id}`, {
    method: "POST",
    headers: buildHeaders(req),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${orchestratorUrl}/sessions/${id}`, {
    method: "DELETE",
    headers: buildHeaders(req),
  });
  if (!res.ok && res.status !== 204) {
    return NextResponse.json(
      { error: "Session not found" },
      { status: res.status }
    );
  }
  return new NextResponse(null, { status: 204 });
}
