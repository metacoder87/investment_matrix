import sys
import os

sys.path.append(os.getcwd())

try:
    from app.signals.engine import SignalEngine
    # Mock session
    class MockSession:
        def query(self, *args): return self
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def limit(self, *args): return self
        def all(self): return []

    engine = SignalEngine(MockSession())
    print("✅ SignalEngine instantiated successfully.")
    
    # Check if new methods/logics are present by consistent behavior (no syntax error)
    print("✅ Syntax check passed.")

except Exception as e:
    print(f"❌ Error: {e}")
