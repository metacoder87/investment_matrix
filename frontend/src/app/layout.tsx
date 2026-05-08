import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import clsx from "clsx";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { AuthProvider } from "@/context/AuthContext";
import { MatrixRain } from "@/components/MatrixRain";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
    title: "CryptoInsight | Investment Matrix",
    description: "Advanced crypto market analysis terminal",
    icons: {
        icon: "/logo.png",
    },
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
            <body className={clsx(inter.variable, "font-sans antialiased")}>
                {/* Background matrix rain (fixed, low opacity, behind everything) */}
                <MatrixRain opacity={0.13} />

                <div className="relative z-10 min-h-screen text-white">
                    <AuthProvider>
                        <Sidebar />
                        {/*
                          Content column. The Sidebar component sets the
                          `--sidebar-w` CSS variable on :root (16rem expanded,
                          4.5rem collapsed). We use a CSS Grid on md+ where the
                          first column is that variable so content reflows
                          smoothly when the sidebar collapses.
                        */}
                        <div
                            className={clsx(
                                "flex min-h-screen flex-col transition-[grid-template-columns] duration-200",
                                "md:grid md:[grid-template-columns:var(--sidebar-w,16rem)_1fr]"
                            )}
                        >
                            {/* spacer column — sidebar is fixed-position so this just reserves grid space */}
                            <div aria-hidden className="hidden md:block" />
                            <div className="flex min-h-screen flex-col">
                                <Header />
                                <main className="relative flex-1 overflow-x-hidden">
                                    {/* faint grid + scanline overlay for cyberpunk feel; pointer-events-none */}
                                    <div
                                        aria-hidden
                                        className="pointer-events-none absolute inset-0 -z-10 bg-grid-faint bg-grid-32 opacity-[0.18]"
                                    />
                                    <div
                                        aria-hidden
                                        className="pointer-events-none absolute inset-0 -z-10 bg-scanlines opacity-40"
                                    />
                                    {children}
                                </main>
                            </div>
                        </div>
                    </AuthProvider>
                </div>
            </body>
        </html>
    );
}
