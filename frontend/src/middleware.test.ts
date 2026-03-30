// @vitest-environment node

import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "./middleware";


describe("middleware", () => {
    it("redirects unauthenticated protected routes to login", () => {
        const request = new NextRequest("http://localhost:3000/market");
        const response = middleware(request);

        expect(response?.status).toBe(307);
        expect(response?.headers.get("location")).toBe(
            "http://localhost:3000/login?redirect=%2Fmarket",
        );
    });

    it("redirects authenticated login requests to market", () => {
        const request = new NextRequest("http://localhost:3000/login", {
            headers: { cookie: "auth_token=test-token" },
        });
        const response = middleware(request);

        expect(response?.status).toBe(307);
        expect(response?.headers.get("location")).toBe("http://localhost:3000/market");
    });

    it("lets public routes continue when unauthenticated", () => {
        const request = new NextRequest("http://localhost:3000/");
        const response = middleware(request);

        expect(response?.headers.get("location")).toBeNull();
    });
});
