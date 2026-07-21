import requests
import json
import threading

def _sanitize_key(key):
    """Remove any non-ASCII characters or hidden whitespace from the key."""
    if not key:
        return ""
    # Strip whitespace and remove any character with ordinal > 127 (non-ASCII)
    return "".join(c for c in key.strip() if ord(c) < 128)

class DeepLClient:
    def __init__(self, api_key):
        self.api_key = _sanitize_key(api_key)
        # Free API keys usually end in :fx
        if self.api_key.endswith(":fx"):
            self.url = "https://api-free.deepl.com/v2/translate"
        else:
            self.url = "https://api.deepl.com/v2/translate"

    def translate(self, text, target_lang="EN-US", source_lang="JA"):
        if not self.api_key:
            return {"error": "DeepL API key is missing or invalid (non-ASCII)."}
            
        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}"
        }
        data = {
            "text": text,
            "target_lang": target_lang,
            "source_lang": source_lang
        }
        
        try:
            response = requests.post(self.url, headers=headers, data=data, timeout=10)
            if response.status_code == 403:
                return {"error": "Invalid DeepL API key (403 Forbidden). Check if your key matches the Free/Pro account type."}
            response.raise_for_status()
            result = response.json()
            return {"text": result["translations"][0]["text"]}
        except requests.exceptions.RequestException as e:
            if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                return {"error": "Rate limit exceeded. Please wait."}
            return {"error": f"DeepL API Error: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}

class OpenRouterClient:
    def __init__(self, api_key):
        self.api_key = _sanitize_key(api_key)
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def chat(self, messages, model="openrouter/auto"):
        if not self.api_key:
            return {"error": "OpenRouter API key is missing or invalid (non-ASCII)."}

        # The 'openrouter/auto' router is forbidden (403) for some keys/accounts.
        # Fall back to the official free router if auto is rejected.
        tried_models = [model]
        if model == "openrouter/auto":
            tried_models.append("openrouter/free")

        last_error = None
        for attempt_model in tried_models:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "DDON Dialogue Editor"
            }
            payload = {
                "model": attempt_model,
                "messages": messages
            }

            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=15)
                if response.status_code == 401:
                    return {"error": "Invalid OpenRouter API key (401 Unauthorized). Please check your API key in Settings."}
                if response.status_code == 403:
                    # Remember the error and try the next fallback model if any.
                    last_error = "OpenRouter API key forbidden (403). The API key may be invalid, expired, or lack permissions. Please check your API key in Settings."
                    continue
                if response.status_code == 404:
                    try:
                        err_json = response.json()
                        msg = err_json.get("error", {}).get("message", "Not Found")
                        return {"error": f"OpenRouter Error: {msg} (404). Check model ID: {attempt_model}"}
                    except:
                        return {"error": f"OpenRouter Error: Endpoint not found (404). Check model ID: {attempt_model}"}
                if response.status_code == 429:
                    return {"error": "OpenRouter rate limit exceeded (429). Please wait a moment and try again."}
                response.raise_for_status()
                result = response.json()
                if "choices" in result:
                    return {"text": result["choices"][0]["message"]["content"]}
                elif "error" in result:
                    msg = result["error"].get("message", "Unknown error")
                    return {"error": f"OpenRouter Error: {msg}"}
                return {"error": "Unknown response format from OpenRouter."}
            except requests.exceptions.RequestException as e:
                if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                    return {"error": "Rate limit exceeded. Please wait."}
                return {"error": f"OpenRouter API Error: {str(e)}"}
            except Exception as e:
                return {"error": str(e)}

        # All attempts failed (e.g. 403 on every model).
        return {"error": last_error or "OpenRouter request failed."}

    def fetch_models(self, free_only=True):
        """Fetch available models from OpenRouter. Returns a list of IDs."""
        try:
            response = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
            response.raise_for_status()
            data = response.json().get("data", [])
            
            models = ["openrouter/auto"]
            for m in data:
                m_id = m.get("id")
                if not m_id: continue
                
                if free_only:
                    pricing = m.get("pricing", {})
                    # Free models have prompt/completion pricing as "0" (string)
                    if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
                        models.append(m_id)
                else:
                    models.append(m_id)
            
            return sorted(list(set(models)))
        except Exception as e:
            print(f"Error fetching models: {e}")
            return ["openrouter/auto", "mistralai/mistral-7b-instruct:free", "meta-llama/llama-3-8b-instruct:free"]

def test_connection():
    """Simple test function to verify logic without keys."""
    print("API Handler Module Loaded.")
    print("Use DeepLClient(key) and OpenRouterClient(key) to interact with APIs.")

if __name__ == "__main__":
    test_connection()
