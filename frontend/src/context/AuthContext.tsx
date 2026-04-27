"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { getApiBaseUrl } from "@/utils/api";

interface User {
    id: number;
    email: string;
    full_name: string | null;
}

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    login: (token: string, redirectTo?: string) => Promise<boolean>;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const SESSION_CONFIRM_RETRIES = 3;
const SESSION_CONFIRM_DELAY_MS = 150;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();
    const pathname = usePathname();

    useEffect(() => {
        checkAuth();
    }, []);

    const fetchCurrentUser = async () => {
        const apiUrl = getApiBaseUrl();
        const response = await fetch(`${apiUrl}/auth/me`, {
            credentials: "include"
        });

        if (!response.ok) {
            return null;
        }

        const data = await response.json();
        return {
            id: data.id ?? 0,
            email: data.email ?? "",
            full_name: data.full_name ?? null
        };
    };

    const checkAuth = async () => {
        const isAuthRoute = pathname.startsWith("/login") || pathname.startsWith("/register");
        const isPublicRoot = pathname === "/";
        try {
            const currentUser = await fetchCurrentUser();

            if (currentUser) {
                setUser(currentUser);
            } else {
                setUser(null);
                if (!isAuthRoute && !isPublicRoot) {
                    router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
                }
            }
        } catch (e) {
            console.error("Auth check failed", e);
            setUser(null);
        } finally {
            setIsLoading(false);
        }
    };

    const login = async (_token: string, redirectTo = "/") => {
        for (let attempt = 1; attempt <= SESSION_CONFIRM_RETRIES; attempt += 1) {
            try {
                const currentUser = await fetchCurrentUser();
                if (currentUser) {
                    setUser(currentUser);
                    router.replace(redirectTo);
                    router.refresh();
                    return true;
                }
            } catch (e) {
                console.error("Session confirmation failed", e);
            }

            if (attempt < SESSION_CONFIRM_RETRIES) {
                await delay(SESSION_CONFIRM_DELAY_MS);
            }
        }

        setUser(null);
        return false;
    };

    const logout = async () => {
        // Call backend to clear the cookie
        const apiUrl = getApiBaseUrl();
        try {
            await fetch(`${apiUrl}/auth/logout`, {
                method: "POST",
                credentials: "include"  // Important: send cookies
            });
        } catch (err) {
            console.error("Logout failed", err);
        }

        setUser(null);
        router.push("/login");
    };

    return (
        <AuthContext.Provider value={{
            user,
            isAuthenticated: !!user,
            isLoading,
            login,
            logout
        }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
}
