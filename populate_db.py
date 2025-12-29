import time
from celery_app import celery_app
from database import SessionLocal, init_db
from app.models.instrument import Coin

def run_pipeline():
    """
    Triggers the data pipeline to populate the database with cryptocurrency data.
    """
    print("Starting the data pipeline...")

    # Step 1: Fetch and store the list of all coins from CoinGecko.
    print("Triggering task to fetch the coin list...")
    fetch_coins_task = celery_app.send_task('celery_worker.tasks.fetch_and_store_coin_list')
    
    # Wait for the task to complete
    while not fetch_coins_task.ready():
        print("Waiting for coin list to be fetched...")
        time.sleep(5)
    
    result = fetch_coins_task.get()
    print(result)
    
    # Step 2: Ingest historical data for each coin.
    print("\nFetching coins from the database...")
    init_db()
    db = SessionLocal()
    try:
        coins = db.query(Coin).all()
        print(f"Found {len(coins)} coins in the database.")
        
        # Ingest historical data for the top 10 coins by market cap
        coins_to_ingest = [coin for coin in coins if coin.market_cap_rank is not None]
        coins_to_ingest.sort(key=lambda x: x.market_cap_rank)
        
        for coin in coins_to_ingest[:10]: # Limiting to top 10 for this example
            symbol = f"{coin.symbol.upper()}/USDT"
            print(f"Triggering task to ingest historical data for {symbol}...")
            ingest_data_task = celery_app.send_task('celery_worker.tasks.ingest_historical_data', args=[symbol])
            
            # Wait for the task to complete
            while not ingest_data_task.ready():
                print(f"Waiting for historical data for {symbol} to be ingested...")
                time.sleep(2)
            
            result = ingest_data_task.get()
            print(result)

    finally:
        db.close()

    print("\nData pipeline finished.")

if __name__ == "__main__":
    run_pipeline()
