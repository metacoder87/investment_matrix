export const formatPrice = (price: number | undefined | null): string => {
    if (price === undefined || price === null) return "---";
    if (price === 0) return "$0.00";

    // For very small numbers (e.g. SHIB/PEPE), show significant digits
    if (price < 0.01) {
        return `$${price.toFixed(8)}`; // e.g. $0.00001234
    }
    if (price < 1) {
        return `$${price.toFixed(4)}`; // e.g. $0.1234
    }
    if (price < 10) {
        return `$${price.toFixed(3)}`; // e.g. $5.123
    }
    // Standard 2 decimals for larger numbers
    return `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const formatCompactNumber = (num: number | undefined | null): string => {
    if (num === undefined || num === null) return "---";
    return new Intl.NumberFormat('en-US', {
        notation: "compact",
        maximumFractionDigits: 2
    }).format(num);
};
