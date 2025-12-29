from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonicalSymbol:
    base: str
    quote: str

    def dash(self) -> str:
        return f"{self.base}-{self.quote}"

    def slash(self) -> str:
        return f"{self.base}/{self.quote}"


def parse_symbol(raw: str) -> CanonicalSymbol:
    raw = raw.strip().upper()
    if "/" in raw:
        base, quote = raw.split("/", 1)
    elif "-" in raw:
        base, quote = raw.split("-", 1)
    else:
        raise ValueError(f"Unsupported symbol format: {raw!r} (expected BASE-QUOTE or BASE/QUOTE)")
    base = base.strip()
    quote = quote.strip()
    if not base or not quote:
        raise ValueError(f"Unsupported symbol format: {raw!r} (empty base/quote)")
    return CanonicalSymbol(base=base, quote=quote)


def parse_symbol_list(raw: str) -> list[CanonicalSymbol]:
    symbols: list[CanonicalSymbol] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        symbols.append(parse_symbol(part))
    return symbols

