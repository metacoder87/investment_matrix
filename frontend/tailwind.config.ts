import type { Config } from "tailwindcss";

const config: Config = {
    content: [
        "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                background: "#05010d",
                surface: "#0a0c1c",
                primary: "#00f5ff",
                secondary: "#ff2bd6",
                accent: "#39ff14",
                muted: "rgba(230, 246, 255, 0.6)",
                neon: {
                    cyan: "#00f5ff",
                    green: "#39ff14",
                    pink: "#ff2bd6",
                    amber: "#ffb000",
                },
            },
            backgroundImage: {
                "app-gradient":
                    "radial-gradient(circle at 15% 10%, rgba(255, 43, 214, 0.15), transparent 40%), radial-gradient(circle at 80% 20%, rgba(0, 245, 255, 0.12), transparent 45%)",
                "scanlines":
                    "repeating-linear-gradient(180deg, rgba(0, 245, 255, 0.04) 0px, rgba(0, 245, 255, 0.04) 1px, transparent 1px, transparent 3px)",
                "grid-faint":
                    "linear-gradient(rgba(0, 245, 255, 0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 245, 255, 0.06) 1px, transparent 1px)",
            },
            backgroundSize: {
                "grid-32": "32px 32px",
            },
            fontFamily: {
                sans: ["var(--font-inter)"],
                mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
            },
            boxShadow: {
                "neon-cyan": "0 0 8px rgba(0, 245, 255, 0.5), 0 0 24px rgba(0, 245, 255, 0.25)",
                "neon-green": "0 0 8px rgba(57, 255, 20, 0.55), 0 0 24px rgba(57, 255, 20, 0.25)",
                "neon-pink": "0 0 8px rgba(255, 43, 214, 0.55), 0 0 24px rgba(255, 43, 214, 0.25)",
            },
            keyframes: {
                "neon-pulse": {
                    "0%, 100%": {
                        boxShadow:
                            "0 0 6px rgba(57, 255, 20, 0.45), 0 0 18px rgba(57, 255, 20, 0.20), inset 0 0 12px rgba(57, 255, 20, 0.05)",
                        borderColor: "rgba(57, 255, 20, 0.5)",
                    },
                    "50%": {
                        boxShadow:
                            "0 0 14px rgba(57, 255, 20, 0.85), 0 0 36px rgba(57, 255, 20, 0.45), inset 0 0 20px rgba(57, 255, 20, 0.15)",
                        borderColor: "rgba(57, 255, 20, 1)",
                    },
                },
                "neon-pulse-cyan": {
                    "0%, 100%": {
                        boxShadow:
                            "0 0 6px rgba(0, 245, 255, 0.4), 0 0 18px rgba(0, 245, 255, 0.18)",
                    },
                    "50%": {
                        boxShadow:
                            "0 0 12px rgba(0, 245, 255, 0.85), 0 0 30px rgba(0, 245, 255, 0.4)",
                    },
                },
                flicker: {
                    "0%, 19.999%, 22%, 62.999%, 64%, 64.999%, 70%, 100%": { opacity: "1" },
                    "20%, 21.999%, 63%, 63.999%, 65%, 69.999%": { opacity: "0.55" },
                },
                shimmer: {
                    "0%": { transform: "translateX(-100%)" },
                    "100%": { transform: "translateX(100%)" },
                },
            },
            animation: {
                "neon-pulse": "neon-pulse 2.4s ease-in-out infinite",
                "neon-pulse-cyan": "neon-pulse-cyan 2.8s ease-in-out infinite",
                flicker: "flicker 4s linear infinite",
                shimmer: "shimmer 2.5s linear infinite",
            },
        },
    },
    plugins: [],
};
export default config;
