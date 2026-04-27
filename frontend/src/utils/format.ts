export const formatPrice = (price: number | string | undefined | null): string => {
    if (price === undefined || price === null || price === "---") return "---";
    const num = Number(price);
    if (isNaN(num)) return "---";
    if (num === 0) return "$0.00";

    // For very small numbers (e.g. SHIB/PEPE), show significant digits
    if (num < 0.01) {
        return `$${num.toFixed(8)}`; // e.g. $0.00001234
    }
    if (num < 1) {
        return `$${num.toFixed(4)}`; // e.g. $0.1234
    }
    if (num < 10) {
        return `$${num.toFixed(3)}`; // e.g. $5.123
    }
    // Standard 2 decimals for larger numbers
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const formatCompactNumber = (num: number | string | undefined | null): string => {
    if (num === undefined || num === null || num === "---") return "---";
    const n = Number(num);
    if (isNaN(n)) return "---";
    return new Intl.NumberFormat('en-US', {
        notation: "compact",
        maximumFractionDigits: 2
    }).format(n);
};
