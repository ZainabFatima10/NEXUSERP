from pyngrok import ngrok
import time

try:
    public_url = ngrok.connect(8000)
    print("=" * 60)
    print(f"YOUR PUBLIC API URL IS: {public_url.public_url}")
    print("=" * 60)
    print("Keep this script running to keep the tunnel open.")
    while True:
        time.sleep(1)
except Exception as e:
    print(f"Error starting ngrok: {e}")
