from app.websockets import RealtimeDataHandler

def main():
    """
    Main function to initialize and run the real-time data handler.
    """
    # Define the symbols you want to track
    # You can get these from a config file or an API call in a real application
    symbols_to_track = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    
    print("Initializing WebSocket client...")
    handler = RealtimeDataHandler(symbols=symbols_to_track)
    
    # The run() method is blocking and will run the event loop
    handler.run()

if __name__ == '__main__':
    main()
