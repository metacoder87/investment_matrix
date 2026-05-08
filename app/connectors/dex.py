from __future__ import annotations

from typing import Any

import httpx


class DexScreenerConnector:
    base_url = "https://api.dexscreener.com"

    async def get_latest_token_profiles(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/token-profiles/latest/v1")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    async def search_pairs(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/latest/dex/search", params={"q": query})
            response.raise_for_status()
            data = response.json()
            return data.get("pairs", []) if isinstance(data, dict) else []

    async def get_token_pairs(self, chain_id: str, token_address: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/token-pairs/v1/{chain_id}/{token_address}")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []


class GeckoTerminalConnector:
    base_url = "https://api.geckoterminal.com/api/v2"

    async def get_network_pools(self, network: str, *, page: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/networks/{network}/pools", params={"page": page})
            response.raise_for_status()
            return response.json()

    async def get_pool_ohlcv(
        self,
        network: str,
        pool_address: str,
        timeframe: str = "minute",
        aggregate: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}",
                params={"aggregate": aggregate, "limit": limit},
            )
            response.raise_for_status()
            return response.json()


class DeFiLlamaConnector:
    api_url = "https://api.llama.fi"
    coins_url = "https://coins.llama.fi"

    async def get_protocols(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{self.api_url}/protocols")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    async def get_current_prices(self, coins: list[str]) -> dict[str, Any]:
        if not coins:
            return {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.coins_url}/prices/current/{','.join(coins)}")
            response.raise_for_status()
            data = response.json()
            return data.get("coins", {}) if isinstance(data, dict) else {}
