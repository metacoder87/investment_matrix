import { vi } from "vitest";

export const router = {
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
};

let pathname = "/";
let searchParams = new URLSearchParams();

export function useRouter() {
    return router;
}

export function usePathname() {
    return pathname;
}

export function useSearchParams() {
    return searchParams;
}

export function setPathname(value: string) {
    pathname = value;
}

export function setSearchParams(
    value: string | URLSearchParams | Record<string, string> = "",
) {
    if (value instanceof URLSearchParams) {
        searchParams = new URLSearchParams(value.toString());
        return;
    }
    if (typeof value === "string") {
        searchParams = new URLSearchParams(value);
        return;
    }
    searchParams = new URLSearchParams(value);
}

export function resetNavigationMocks() {
    pathname = "/";
    searchParams = new URLSearchParams();
    Object.values(router).forEach((fn) => fn.mockReset());
}
