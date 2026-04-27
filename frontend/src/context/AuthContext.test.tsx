import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./AuthContext";
import {
    resetNavigationMocks,
    router,
    setPathname,
} from "../../test/mocks/next-navigation";


function makeToken(payload: Record<string, unknown>) {
    return `header.${btoa(JSON.stringify(payload))}.signature`;
}

function Consumer() {
    const auth = useAuth();
    return (
        <div>
            <div data-testid="loading">{String(auth.isLoading)}</div>
            <div data-testid="state">{auth.isAuthenticated ? "authenticated" : "anonymous"}</div>
            <div data-testid="email">{auth.user?.email ?? ""}</div>
            <button onClick={() => void auth.login(makeToken({ user_id: 7, sub: "trader@example.com" }), "/paper")}>
                Call Login
            </button>
            <button onClick={() => void auth.logout()}>
                Call Logout
            </button>
        </div>
    );
}


describe("AuthProvider", () => {
    beforeEach(() => {
        resetNavigationMocks();
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.stubGlobal("fetch", vi.fn());
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("loads the authenticated user on mount", async () => {
        setPathname("/market");
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 3, email: "trader@example.com", full_name: "Trader" }),
        } as Response);

        render(
            <AuthProvider>
                <Consumer />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("authenticated"));
        expect(screen.getByTestId("email")).toHaveTextContent("trader@example.com");
        expect(router.push).not.toHaveBeenCalled();
    });

    it("redirects protected routes to login when auth check fails", async () => {
        setPathname("/portfolio");
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 401,
            json: async () => ({ detail: "unauthorized" }),
        } as Response);

        render(
            <AuthProvider>
                <Consumer />
            </AuthProvider>,
        );

        await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login?redirect=%2Fportfolio"));
        expect(screen.getByTestId("state")).toHaveTextContent("anonymous");
    });

    it("uses the supplied redirect when login is called", async () => {
        setPathname("/login");
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 401,
            json: async () => ({ detail: "unauthorized" }),
        } as Response).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 7, email: "trader@example.com", full_name: "Trader" }),
        } as Response);

        render(
            <AuthProvider>
                <Consumer />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));

        const user = userEvent.setup();
        await user.click(screen.getByText("Call Login"));

        await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("authenticated"));
        expect(screen.getByTestId("email")).toHaveTextContent("trader@example.com");
        expect(fetch).toHaveBeenLastCalledWith("http://api.test/auth/me", {
            credentials: "include",
        });
        expect(router.replace).toHaveBeenCalledWith("/paper");
        expect(router.refresh).toHaveBeenCalled();
    });

    it("calls the logout endpoint and redirects to login", async () => {
        setPathname("/market");
        vi.mocked(fetch)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ id: 3, email: "trader@example.com", full_name: "Trader" }),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({}),
            } as Response);

        render(
            <AuthProvider>
                <Consumer />
            </AuthProvider>,
        );

        await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("authenticated"));

        const user = userEvent.setup();
        await user.click(screen.getByText("Call Logout"));

        await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
        expect(fetch).toHaveBeenLastCalledWith("http://api.test/auth/logout", {
            method: "POST",
            credentials: "include",
        });
        expect(screen.getByTestId("state")).toHaveTextContent("anonymous");
    });
});
