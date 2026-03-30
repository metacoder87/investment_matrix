export const getApiBaseUrl = (): string => {
    const publicUrl = process.env.NEXT_PUBLIC_API_URL;
    if (typeof window === 'undefined') {
        return process.env.INTERNAL_API_URL || publicUrl || "http://localhost:8000/api";
    }
    return publicUrl || "/api";
};
