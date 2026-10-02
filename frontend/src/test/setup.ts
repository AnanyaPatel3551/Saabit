import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout engine; Recharts' ResponsiveContainer needs ResizeObserver to exist.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

afterEach(() => {
  cleanup();
  window.localStorage.clear();  // the question history must not leak between tests
});
