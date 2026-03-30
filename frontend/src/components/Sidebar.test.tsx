import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "./Sidebar";
import { resetNavigationMocks, setPathname } from "../../test/mocks/next-navigation";


const mockUseAuth = vi.fn();
const mockUseHealthCheck = vi.fn();

vi.mock("@/context/AuthContext", () => ({
    useAuth: () => mockUseAuth(),
}));

vi.mock("@/hooks/useHealthCheck", () => ({
    useHealthCheck: () => mockUseHealthCheck(),
}));


describe("Sidebar", () => {
    beforeEach(() => {
        resetNavigationMocks();
        mockUseHealthCheck.mockReturnValue({ isOnline: true, lastChecked: null });
        mockUseAuth.mockReturnValue({
            user: null,
            isAuthenticated: false,
            isLoading: false,
            login: vi.fn(),
            logout: vi.fn(),
        });
    });

    it("marks the active navigation item", () => {
        setPathname("/market");
        render(<Sidebar />);

        expect(screen.getByRole("link", { name: /market/i })).toHaveClass("text-primary");
        expect(screen.getByRole("link", { name: /dashboard/i })).not.toHaveClass("text-primary");
    });

    it("shows the authenticated user and calls logout", async () => {
        const logout = vi.fn();
        mockUseAuth.mockReturnValue({
            user: { email: "trader@example.com", full_name: null },
            isAuthenticated: true,
            isLoading: false,
            login: vi.fn(),
            logout,
        });

        render(<Sidebar />);

        expect(screen.getByText("trader@example.com")).toBeInTheDocument();

        const user = userEvent.setup();
        await user.click(screen.getByTitle("Log Out"));
        expect(logout).toHaveBeenCalledTimes(1);
    });

    it("shows offline state when unauthenticated and the health check fails", () => {
        mockUseHealthCheck.mockReturnValue({ isOnline: false, lastChecked: null });

        render(<Sidebar />);

        expect(screen.getByText("System Offline")).toBeInTheDocument();
        expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    });
});
