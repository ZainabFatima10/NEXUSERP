import requests
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("OPENWEATHER_API_KEY")

def get_weather():
    cities = ["Islamabad", "Lahore", "Karachi"]
    all_data = []

    for city in cities:
        print(f"Fetching weather for {city}...")
        url = "http://api.openweathermap.org/data/2.5/forecast"
        params = {
            "q":      city,
            "appid":  API_KEY,
            "units":  "metric",
            "cnt":    40  # 5 days, every 3 hours
        }

        response = requests.get(url, params=params)

        if response.status_code != 200:
            print(f"Error for {city}: {response.json()}")
            continue

        data = response.json()

        for item in data["list"]:
            all_data.append({
                "date":        item["dt_txt"],
                "city":        city,
                "temperature": item["main"]["temp"],
                "humidity":    item["main"]["humidity"],
                "wind_speed":  item["wind"]["speed"],
                "description": item["weather"][0]["description"]
            })

    df = pd.DataFrame(all_data)
    os.makedirs("data/raw", exist_ok=True)
    df.to_csv("data/raw/weather.csv", index=False)
    print(f"\nDone! Saved {len(df)} rows to data/raw/weather.csv")
    print(df.head())

get_weather()