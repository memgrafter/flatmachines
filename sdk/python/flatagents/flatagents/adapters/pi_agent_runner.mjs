#!/usr/bin/env node

import { pathToFileURL } from "url";
import { resolve } from "path";
import process from "process";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf-8");
}

function parseRef(ref) {
  if (!ref) {
    throw new Error("Missing ref for pi-agent runner");
  }
  const [moduleRef, exportName] = ref.split("#");
  return { moduleRef, exportName: exportName || "buildAgent" };
}

async function loadFactory(moduleRef, exportName) {
  const url = moduleRef.startsWith(".") || moduleRef.startsWith("/")
    ? pathToFileURL(resolve(moduleRef)).href
    : moduleRef;
  const mod = await import(url);
  const factory = mod[exportName] || mod.default;
  if (!factory) {
    throw new Error(`Factory '${exportName}' not found in ${moduleRef}`);
  }
  return factory;
}

function extractText(content) {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (part.type === "text") return part.text || "";
        return "";
      })
      .join("");
  }
  return "";
}

async function run() {
  const raw = await readStdin();
  if (!raw) {
    throw new Error("No input provided to pi-agent runner");
  }
  const request = JSON.parse(raw);
  const { ref, config, input } = request;
  const { moduleRef, exportName } = parseRef(ref);

  const factory = await loadFactory(moduleRef, exportName);
  const agent = await factory(config || {});

  if (!agent || typeof agent.prompt !== "function") {
    throw new Error("Factory did not return a pi-mono Agent instance");
  }

  const payload = input || {};

  if (payload.messages) {
    await agent.prompt(payload.messages);
  } else if (payload.message) {
    await agent.prompt(payload.message);
  } else if (payload.task || payload.prompt) {
    const task = payload.task || payload.prompt;
    const images = payload.images || undefined;
    await agent.prompt(task, images);
  } else {
    throw new Error("pi-agent input requires task/prompt or message(s)");
  }

  const messages = agent.state?.messages || [];
  const assistant = [...messages].reverse().find((msg) => msg.role === "assistant");
  const content = assistant ? extractText(assistant.content) : "";
  const usage = assistant?.usage || null;
  const cost = usage?.cost?.total ?? null;

  const response = {
    output: { content },
    content,
    usage,
    cost,
    raw: { messages },
  };

  process.stdout.write(JSON.stringify(response));
}

run().catch((err) => {
  console.error(err?.stack || String(err));
  process.exit(1);
});
