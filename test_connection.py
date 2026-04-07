import os
from binance.client import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API keys
api_key = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_SECRET_KEY", "")

print("Testing Binance API connection...")
print(f"API Key exists: {bool(api_key)}")
print(f"API Secret exists: {bool(api_secret)}")

try:
    # Create client with longer timeout
    client = Client(api_key, api_secret, requests_params={'timeout': 30})
    print("Client created successfully")

    # Test ping
    print("Testing ping...")
    result = client.ping()
    print(f"Ping result: {result}")

    # Test get server time
    print("Testing server time...")
    server_time = client.get_server_time()
    print(f"Server time: {server_time}")

    print("Connection test successful!")

except Exception as e:
    print(f"Connection test failed: {e}")