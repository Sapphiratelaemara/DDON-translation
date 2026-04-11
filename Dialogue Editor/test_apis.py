import sys
import os
from api_handler import DeepLClient, OpenRouterClient

def main():
    print("--- DDON API Tester ---")
    deepl_key = input("Enter DeepL API Key (leave blank to skip): ").strip()
    openrouter_key = input("Enter OpenRouter API Key (leave blank to skip): ").strip()

    if deepl_key:
        print("\nTesting DeepL...")
        deepl = DeepLClient(deepl_key)
        result = deepl.translate("ドラゴンズドグマ オンラインへようこそ！")
        if "text" in result:
            print(f"DeepL Result: {result['text']}")
        else:
            print(f"DeepL Error: {result['error']}")

    if openrouter_key:
        print("\nTesting OpenRouter...")
        or_client = OpenRouterClient(openrouter_key)
        messages = [{"role": "user", "content": "Say hello in a medieval fantasy style."}]
        result = or_client.chat(messages)
        if "text" in result:
            print(f"OpenRouter Result: {result['text']}")
        else:
            print(f"OpenRouter Error: {result['error']}")

    print("\nTests complete.")

if __name__ == "__main__":
    main()
