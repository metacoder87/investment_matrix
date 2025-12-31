import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from celery_app import celery_app

def trigger_backfill():
    print("🚀 Triggering backfill for Core Universe (BTC, ETH, SOL)...")
    try:
        # Calling the task by name as registered in celery_worker/tasks.py
        # You can see the name in the user's logs: celery_worker.tasks.backfill_core_universe
        task = celery_app.send_task(
            "celery_worker.tasks.backfill_core_universe",
            kwargs={"exchange_id": "coinbase", "days": 30}
        )
        print(f"✅ Task dispatched: {task.id}")
        print("⏳ Background worker will process this. Graphs should populate shortly.")
    except Exception as e:
        print(f"❌ Failed to dispatch task: {e}")

if __name__ == "__main__":
    trigger_backfill()
