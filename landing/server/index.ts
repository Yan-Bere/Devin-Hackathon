import "dotenv/config";
import express from "express";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import Papa from "papaparse";

const app = express();
const port = Number(process.env.PORT) || 8787;
const dataDirectory = path.resolve(process.cwd(), "data");
const devinBaseUrl = "https://api.devin.ai/v1";

app.use(express.json());
app.use("/data", express.static(dataDirectory));

type DevinMessage = {
  message?: unknown;
  content?: unknown;
  source?: unknown;
  origin?: unknown;
  type?: unknown;
  created_at?: unknown;
  timestamp?: unknown;
};

type DesignRow = {
  id: string;
  fin_type: string;
  dp_psi: number;
  t_gpu_c: number;
  t_hbm_c: number;
};

function hasDevinApiKey() {
  return Boolean(process.env.DEVIN_API_KEY);
}

function respondWithoutKey(res: express.Response) {
  return res.status(503).json({ error: "no_key" });
}

async function requestDevin(pathname: string, init: RequestInit = {}) {
  return fetch(`${devinBaseUrl}${pathname}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${process.env.DEVIN_API_KEY}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
}

function normalizeTimestamp(value: unknown) {
  if (typeof value === "number") {
    const milliseconds = value < 1_000_000_000_000 ? value * 1000 : value;
    return new Date(milliseconds).toISOString();
  }

  if (typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.toISOString();
  }

  return new Date().toISOString();
}

function normalizeMessage(message: DevinMessage) {
  const labels = [message.source, message.origin, message.type]
    .filter((label): label is string => typeof label === "string")
    .map((label) => label.toLowerCase());
  // Devin identifies its replies with source "devin"; assistant/Devin labels in origin or type are also replies.
  const isAssistant = labels.some((label) => /(^|[_\s-])(devin|assistant)([_\s-]|$)/.test(label));
  const text = message.message ?? message.content ?? "";

  return {
    role: isAssistant ? ("assistant" as const) : ("user" as const),
    text: typeof text === "string" ? text : JSON.stringify(text),
    ts: normalizeTimestamp(message.created_at ?? message.timestamp),
  };
}

app.get("/api/health", (_req, res) => {
  res.json({ devinConfigured: hasDevinApiKey() });
});

app.post("/api/chat/start", async (req, res) => {
  if (!hasDevinApiKey()) return respondWithoutKey(res);
  if (typeof req.body?.prompt !== "string" || !req.body.prompt.trim()) {
    return res.status(400).json({ error: "invalid_prompt" });
  }

  try {
    const response = await requestDevin("/sessions", {
      method: "POST",
      body: JSON.stringify({ prompt: req.body.prompt }),
    });
    if (!response.ok) return res.status(502).json({ error: "devin_api_error" });
    const data = (await response.json()) as { session_id?: unknown };
    if (typeof data.session_id !== "string") {
      return res.status(502).json({ error: "devin_api_error" });
    }
    return res.json({ sessionId: data.session_id });
  } catch {
    return res.status(502).json({ error: "devin_api_error" });
  }
});

app.post("/api/chat/:id/message", async (req, res) => {
  if (!hasDevinApiKey()) return respondWithoutKey(res);
  if (typeof req.body?.message !== "string" || !req.body.message.trim()) {
    return res.status(400).json({ error: "invalid_message" });
  }

  try {
    const response = await requestDevin(
      `/sessions/${encodeURIComponent(req.params.id)}/message`,
      {
        method: "POST",
        body: JSON.stringify({ message: req.body.message }),
      },
    );
    if (!response.ok) return res.status(502).json({ error: "devin_api_error" });
    return res.json({ ok: true });
  } catch {
    return res.status(502).json({ error: "devin_api_error" });
  }
});

app.get("/api/chat/:id/messages", async (req, res) => {
  if (!hasDevinApiKey()) return respondWithoutKey(res);

  try {
    const response = await requestDevin(
      `/sessions/${encodeURIComponent(req.params.id)}`,
    );
    if (!response.ok) return res.status(502).json({ error: "devin_api_error" });
    const data = (await response.json()) as {
      status?: unknown;
      status_enum?: unknown;
      messages?: DevinMessage[];
    };
    return res.json({
      status: String(data.status ?? data.status_enum ?? "unknown"),
      messages: Array.isArray(data.messages) ? data.messages.map(normalizeMessage) : [],
    });
  } catch {
    return res.status(502).json({ error: "devin_api_error" });
  }
});

app.get("/api/demo-data", (_req, res) => {
  const csvPath = path.join(dataDirectory, "designs.csv");
  if (!existsSync(csvPath)) return res.status(404).json({ error: "missing" });

  try {
    const csv = readFileSync(csvPath, "utf8");
    const parsed = Papa.parse<Record<string, string | number>>(csv, {
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
    });
    const rows: DesignRow[] = parsed.data.map((row) => ({
      id: String(row.id ?? ""),
      fin_type: String(row.fin_type ?? ""),
      dp_psi: Number(row.dp_psi),
      t_gpu_c: Number(row.t_gpu_c),
      t_hbm_c: Number(row.t_hbm_c),
    }));
    return res.json(rows);
  } catch {
    return res.status(500).json({ error: "read_failed" });
  }
});

app.listen(port, () => {
  console.log(`ColdShock API listening on http://localhost:${port}`);
});
