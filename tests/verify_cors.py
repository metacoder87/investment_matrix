
import httpx
import asyncio

async def check_cors():
    url = "http://localhost:8000/api/coin/BTC-USD/analysis"
    headers = {
        "Origin": "http://localhost:3000",
        "Referer": "http://localhost:3000/",
    }
    print(f"Checking CORS for {url}")
    try:
        async with httpx.AsyncClient() as client:
            # Option 1: OPTIONS request
            print("\n--- OPTIONS Request ---")
            resp_opt = await client.options(url, headers=headers)
            print(f"Status: {resp_opt.status_code}")
            print(f"Access-Control-Allow-Origin: {resp_opt.headers.get('access-control-allow-origin')}")
            print(f"Access-Control-Allow-Methods: {resp_opt.headers.get('access-control-allow-methods')}")

            # Option 2: GET request
            print("\n--- GET Request ---")
            resp_get = await client.get(url, headers=headers)
            print(f"Status: {resp_get.status_code}")
            print(f"Access-Control-Allow-Origin: {resp_get.headers.get('access-control-allow-origin')}")
            print(f"Access-Control-Allow-Credentials: {resp_get.headers.get('access-control-allow-credentials')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_cors())
