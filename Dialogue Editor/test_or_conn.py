import requests

def main():
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        print(f"Models list status: {response.status_code}")
        if response.status_code == 200:
            print("Successfully reached OpenRouter models endpoint.")
        else:
            print(f"Failed to reach OpenRouter: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
