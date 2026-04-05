import requests
import json
import os

def main():
    with open("keys.json", 'r') as f:
        keys = json.load(f)
    api_key = keys.get("openrouter_api_key")
    if not api_key:
        print("No key")
        return

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "DDON Dialogue Editor"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": "hi"}]
    }
    
    print(f"Testing POST to {url}...")
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("Success!")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    main()
