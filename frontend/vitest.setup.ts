import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, vi } from "vitest";

vi.mock("next/link", () => ({
    default: ({ href, children, ...props }: any) =>
        React.createElement("a", { href: typeof href === "string" ? href : String(href), ...props }, children),
}));

vi.mock("next/navigation", async () => import("./test/mocks/next-navigation"));

if (typeof window !== "undefined") {
    Object.defineProperty(window, "matchMedia", {
        writable: true,
        value: vi.fn().mockImplementation((query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: vi.fn(),
            removeListener: vi.fn(),
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
            dispatchEvent: vi.fn(),
        })),
    });
}

class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
}

vi.stubGlobal("ResizeObserver", ResizeObserverMock);

afterEach(() => {
    cleanup();
});
