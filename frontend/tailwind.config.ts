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
            },
            backgroundImage: {
                "app-gradient": "radial-gradient(circle at 15% 10%, rgba(255, 43, 214, 0.15), transparent 40%), radial-gradient(circle at 80% 20%, rgba(0, 245, 255, 0.12), transparent 45%)",
            },
            fontFamily: {
                sans: ['var(--font-inter)'],
            },
        },
    },
    plugins: [],
};
export default config;
