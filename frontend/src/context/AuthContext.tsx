"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
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
    login: (token: string) => void;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();

    useEffect(() => {
        checkAuth();
    }, []);

    const checkAuth = async () => {
        const isAuthRoute = pathname.startsWith("/login") || pathname.startsWith("/register");
        const isPublicRoot = pathname === "/";
        try {
            const apiUrl = getApiBaseUrl();
            const response = await fetch(`${apiUrl}/auth/me`, {
                credentials: "include"
            });

            if (response.ok) {
                const data = await response.json();
                setUser({
                    id: data.id ?? 0,
                    email: data.email ?? "",
                    full_name: data.full_name ?? null
                });
            } else {
                setUser(null);
                if ((response.status === 401 || response.status === 403) && !isAuthRoute && !isPublicRoot) {
                    router.push("/login");
                }
            }
        } catch (e) {
            console.error("Auth check failed", e);
            setUser(null);
        } finally {
            setIsLoading(false);
        }
    };

    const login = (token: string) => {
        // Token is now stored in httpOnly cookie set by backend
        // We just need to decode it to get user info for UI
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            setUser({ id: payload.user_id, email: payload.sub, full_name: null });

            // Check for redirect parameter
            const redirectTo = searchParams.get("redirect") || "/";
            router.push(redirectTo);
        } catch (e) {
            console.error("Failed to decode token", e);
            router.push("/");
        }
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
