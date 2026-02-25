import { NextRequest, NextResponse } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";
const apiKey = (process.env.ORCHESTRATOR_API_KEY || "").split(",")[0].trim();

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${orchestratorUrl}/sessions/${id}`, {
    headers: apiKey ? { "X-API-Key": apiKey } : {},
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

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${orchestratorUrl}/sessions/${id}`, {
    method: "DELETE",
    headers: apiKey ? { "X-API-Key": apiKey } : {},
  });
  if (!res.ok && res.status !== 204) {
    return NextResponse.json(
      { error: "Session not found" },
      { status: res.status }
    );
  }
  return new NextResponse(null, { status: 204 });
}
