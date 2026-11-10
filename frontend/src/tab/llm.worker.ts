/// <reference lib="webworker" />
// The residents' model runs in its own worker so the town stays smooth while it thinks.
import { WebWorkerMLCEngineHandler } from "@mlc-ai/web-llm";

const handler = new WebWorkerMLCEngineHandler();
self.onmessage = (msg: MessageEvent) => handler.onmessage(msg);
