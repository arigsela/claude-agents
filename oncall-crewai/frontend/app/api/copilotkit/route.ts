import { HttpAgent } from "@ag-ui/client";
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { NextRequest } from "next/server";

const orchestratorUrl =
  process.env.ORCHESTRATOR_URL || "http://localhost:8000";

// API_KEYS may be comma-separated; use only the first key
const apiKey = (process.env.ORCHESTRATOR_API_KEY || "").split(",")[0].trim();

export const POST = async (req: NextRequest) => {
  // Always use API_KEY for server-to-server auth.
  // Forward client JWT via X-User-JWT header for user scoping
  // (CopilotKit runtime doesn't reliably forward Authorization headers)
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const clientAuth = req.headers.get("Authorization");
  if (clientAuth) {
    headers["X-User-JWT"] = clientAuth;
  }

  const requestAgent = new HttpAgent({
    url: `${orchestratorUrl}/copilotkit`,
    headers,
  });
  const requestRuntime = new CopilotRuntime({
    agents: {
      // @ts-expect-error - HttpAgent/AbstractAgent type mismatch
      oncallAgent: requestAgent,
    },
  });
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime: requestRuntime,
    serviceAdapter: new ExperimentalEmptyAdapter(),
    endpoint: "/api/copilotkit",
  });
  return handleRequest(req);
};
