import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";


const login = vi.fn();

vi.mock("@/context/AuthContext", () => ({
    useAuth: () => ({
        login,
    }),
}));


describe("LoginPage", () => {
    beforeEach(() => {
        login.mockReset();
        login.mockResolvedValue(true);
        window.history.pushState({}, "", "/login");
        process.env.NEXT_PUBLIC_API_URL = "http://api.test";
        vi.stubGlobal("fetch", vi.fn());
    });

    it("submits form-encoded credentials and awaits session login on success", async () => {
        window.history.pushState({}, "", "/login?redirect=%2Fmarket");
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ access_token: "header.payload.signature" }),
        } as Response);

        const user = userEvent.setup();
        const { container } = render(<LoginPage />);

        await user.type(screen.getByPlaceholderText("name@example.com"), "trader@example.com");
        await user.type(
            container.querySelector('input[type="password"]') as HTMLInputElement,
            "hunter2",
        );
        await user.click(screen.getByRole("button", { name: /sign in/i }));

        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

        const [, init] = vi.mocked(fetch).mock.calls[0];
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("include");
        expect(String(init?.body)).toContain("username=trader%40example.com");
        expect(String(init?.body)).toContain("password=hunter2");
        await waitFor(() => expect(login).toHaveBeenCalledWith("header.payload.signature", "/market"));
    });

    it("renders an error when the cookie session is not confirmed", async () => {
        login.mockResolvedValueOnce(false);
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ access_token: "header.payload.signature" }),
        } as Response);

        const user = userEvent.setup();
        const { container } = render(<LoginPage />);

        await user.type(screen.getByPlaceholderText("name@example.com"), "trader@example.com");
        await user.type(
            container.querySelector('input[type="password"]') as HTMLInputElement,
            "hunter2",
        );
        await user.click(screen.getByRole("button", { name: /sign in/i }));

        expect(await screen.findByText("Sign in succeeded, but the browser session was not established. Please try again.")).toBeInTheDocument();
    });

    it("renders an error when login fails", async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: "Invalid credentials" }),
        } as Response);

        const user = userEvent.setup();
        const { container } = render(<LoginPage />);

        await user.type(screen.getByPlaceholderText("name@example.com"), "trader@example.com");
        await user.type(
            container.querySelector('input[type="password"]') as HTMLInputElement,
            "wrong",
        );
        await user.click(screen.getByRole("button", { name: /sign in/i }));

        expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
        expect(login).not.toHaveBeenCalled();
    });
});
