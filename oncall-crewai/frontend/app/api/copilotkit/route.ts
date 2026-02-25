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

const oncallAgent = new HttpAgent({
  url: `${orchestratorUrl}/copilotkit`,
  headers: apiKey ? { "X-API-Key": apiKey } : {},
});

const runtime = new CopilotRuntime({
  agents: {
    // @ts-expect-error - HttpAgent/AbstractAgent type mismatch between ag-ui and copilotkit versions
    oncallAgent,
  },
});

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new ExperimentalEmptyAdapter(),
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};
