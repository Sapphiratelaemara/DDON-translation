import json
import requests
from src.api_handler import DeepLClient, OpenRouterClient
from src.config_manager import ConfigManager

def check_deepl(key):
    print("Testing DeepL...")
    client = DeepLClient(key)
    res = client.translate("こんにちは")
    if "text" in res:
        print(f"DeepL OK: {res['text']}")
    else:
        print(f"DeepL Error: {res.get('error')}")

def check_openrouter(key):
    print("\nTesting OpenRouter...")
    client = OpenRouterClient(key)
    # Use a known free model from my recent listing
    model = "meta-llama/llama-3.2-3b-instruct:free"
    messages = [{"role": "user", "content": "Hi, say 'Connected'"}]
    res = client.chat(messages, model=model)
    if "text" in res:
        print(f"OpenRouter OK: {res['text']}")
    else:
        print(f"OpenRouter Error: {res.get('error')}")

if __name__ == "__main__":
    with open("keys.json", 'r') as f:
        keys = json.load(f)
    
    check_deepl(keys.get("deepl_api_key"))
    check_openrouter(keys.get("openrouter_api_key"))
