import { useState, useEffect } from "react";
// import { getApiBaseUrl } from "@/services/apiClient"; // Removed duplicate

import { getApiBaseUrl } from "@/utils/api";

export function useHealthCheck() {
    const [isOnline, setIsOnline] = useState<boolean>(true); // Optimistic default
    const [lastChecked, setLastChecked] = useState<Date | null>(null);

    useEffect(() => {
        const checkHealth = async () => {
            try {
                const apiUrl = getApiBaseUrl();
                // Simple fetch to health endpoint
                // We use a short timeout to fail fast
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 5000);

                const res = await fetch(`${apiUrl}/health`, {
                    signal: controller.signal,
                    cache: 'no-store'
                });

                clearTimeout(timeoutId);

                if (res.ok) {
                    setIsOnline(true);
                } else {
                    setIsOnline(false);
                }
            } catch (error) {
                setIsOnline(false);
            } finally {
                setLastChecked(new Date());
            }
        };

        // Check immediately
        checkHealth();

        // Then poll every 30 seconds
        const interval = setInterval(checkHealth, 30000);

        return () => clearInterval(interval);
    }, []);

    return { isOnline, lastChecked };
}
