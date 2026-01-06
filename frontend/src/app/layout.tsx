import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import clsx from "clsx";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";

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
                <div className="flex min-h-screen bg-background text-white">
                    <Sidebar />
                    <div className="flex flex-1 flex-col transition-all md:ml-64">
                        <Header />
                        <main className="flex-1">{children}</main>
                    </div>
                </div>
            </body>
        </html>
    );
}
