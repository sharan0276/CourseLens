import requests
import json

try:
    response = requests.get("http://localhost:8000/history/20567856-6eac-4728-8788-f988c54054e5")
    if response.status_code == 200:
        data = response.json()
        msgs = data.get("messages", [])
        print(f"Loaded {len(msgs)} messages.")
        for m in msgs:
            print(m.get("content")[:30].replace("\n", " "))
    else:
        print("API error", response.status_code)
except Exception as e:
    print(e)
