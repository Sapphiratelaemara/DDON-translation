import requests
import time
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

# Replies that are not translations: routers (openrouter/auto, openrouter/free) can land on a
# safety classifier whose whole answer is "User Safety: safe". Never hand those back as text.
_BAD_REPLY_PREFIXES = ("user safety", "openrouter error")


def _is_bad_reply(text):
    s = (text or "").strip().lstrip("{[\"' \n\t").lower()
    return (not s) or s.startswith(_BAD_REPLY_PREFIXES)


def _extract_text(result):
    """(text, why). text is None when the response has no usable message content.
    Never raises: free models / providers sometimes answer 200 with choices=null, message=null,
    content=null, content parts, or an error object, and indexing those blindly crashes."""
    try:
        if not isinstance(result, dict):
            return None, "response is not a JSON object"
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            return None, "no choices in response"
        first = choices[0]
        if not isinstance(first, dict):
            return None, "choices[0] is empty"
        msg = first.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if content is None or not str(content).strip():
            usage = result.get("usage")
            ctoks = usage.get("completion_tokens") if isinstance(usage, dict) else None
            mdesc = "null" if msg is None else f"keys {sorted(msg.keys()) if isinstance(msg, dict) else type(msg).__name__}"
            return None, (f"empty message content (message={mdesc}, finish_reason={first.get('finish_reason')!r}, "
                          f"completion_tokens={ctoks}, error={first.get('error')!r})")
        return str(content), ""
    except Exception as e:  # pragma: no cover - defensive
        return None, f"unparseable response: {e}"


def _api_error_message(result):
    """Best human-readable error from an OpenRouter response body, or ''."""
    try:
        err = result.get("error") if isinstance(result, dict) else None
        if err is None and isinstance(result, dict):
            ch = result.get("choices")
            if isinstance(ch, list) and ch and isinstance(ch[0], dict):
                err = ch[0].get("error")
        if isinstance(err, dict):
            msg = err.get("message") or "Unknown error"
            code = err.get("code")
            return f"{msg} (code {code})" if code is not None else str(msg)
        return str(err) if err else ""
    except Exception:  # pragma: no cover - defensive
        return ""


def _raw_excerpt(result, n=1500):
    try:
        return json.dumps(result, ensure_ascii=True)[:n]
    except Exception:
        return repr(result)[:n]


class OpenRouterClient:
    # No temperature was being sent, so every call ran at the provider default (often 1.0),
    # which makes voice notes get applied more literally and less consistently.
    DEFAULT_TEMPERATURE = 0.3
    MAX_BAD_REPLY_RETRIES = 2   # classifier junk ("User Safety: safe"): a different route often answers properly
    MAX_EMPTY_RETRIES = 1       # empty / malformed body: one re-ask only (each re-ask can take as long as the first
                                # call and the batch gives a whole attempt just 120 s)
    READ_TIMEOUT = 100          # seconds of SILENCE tolerated. It was a hard 15 s, which defeated the batch's own patience
                                # for slow free models (120 s per attempt, 3 retries): a slow reply became a hard error and
                                # the item dropped to the fallback instead of being retried.

    def __init__(self, api_key):
        self.api_key = _sanitize_key(api_key)
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def chat(self, messages, model="openrouter/auto", temperature=None):
        if not self.api_key:
            return {"error": "OpenRouter API key is missing or invalid (non-ASCII)."}

        # The 'openrouter/auto' router is forbidden (403) for some keys/accounts.
        # Fall back to the official free router if auto is rejected.
        tried_models = [model]
        if model == "openrouter/auto":
            tried_models.append("openrouter/free")

        last_error = None
        t0 = time.time()
        calls = 0
        for attempt_model in tried_models:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "DDON Dialogue Editor"
            }
            payload = {
                "model": attempt_model,
                "messages": messages,
                "temperature": self.DEFAULT_TEMPERATURE if temperature is None else temperature,
            }

            try:
                bad_replies = 0
                while True:
                    response = requests.post(self.url, headers=headers, json=payload, timeout=(10, self.READ_TIMEOUT))
                    calls += 1
                    if response.status_code != 200:
                        break
                    try:
                        result = response.json()
                    except Exception:
                        break
                    if isinstance(result, dict) and result.get("error") and not result.get("choices"):
                        break  # a real API error body: reported (with the provider's message) below
                    _text, _why = _extract_text(result)
                    if _text is not None and not _is_bad_reply(_text):
                        break
                    # empty / malformed / classifier "User Safety" reply: usually transient, so ask again
                    bad_replies += 1
                    _who = (result.get("model") if isinstance(result, dict) else None) or attempt_model
                    _reason = _why or f"junk reply {_text[:40]!a}"
                    _limit = self.MAX_BAD_REPLY_RETRIES if _text is not None else self.MAX_EMPTY_RETRIES
                    if bad_replies > _limit:
                        print(f"[OpenRouter] Unusable reply from {_who} (requested {attempt_model}): {_reason}; giving up")
                        print(f"[OpenRouter] raw response excerpt: {_raw_excerpt(result)!a}")
                        return {"error": f"OpenRouter Error: unusable reply from {_who}: {_reason}",
                                "raw": _raw_excerpt(result, 3000), "elapsed": round(time.time() - t0, 1), "attempts": calls}
                    print(f"[OpenRouter] Unusable reply from {_who} (requested {attempt_model}): {_reason}; "
                          f"re-asking {bad_replies}/{_limit}")
                    time.sleep(1)
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
                text, why = _extract_text(result)
                if text is not None:
                    used = (result.get("model") if isinstance(result, dict) else None) or attempt_model
                    if attempt_model in ("openrouter/auto", "openrouter/free"):
                        print(f"[OpenRouter] router {attempt_model} answered with model: {used}")
                    return {"text": text, "model": used, "elapsed": round(time.time() - t0, 1), "attempts": calls}
                api_err = _api_error_message(result)
                print(f"[OpenRouter] No usable reply from {attempt_model}: {api_err or why}")
                print(f"[OpenRouter] raw response excerpt: {_raw_excerpt(result)!a}")
                return {"error": f"OpenRouter Error: {api_err or why or 'Unknown response format from OpenRouter.'}",
                        "raw": _raw_excerpt(result, 3000), "elapsed": round(time.time() - t0, 1), "attempts": calls}
            except requests.exceptions.Timeout as e:
                # Report slowness in the form the batch's retry loop understands: "Cancelled (timeout)" means
                # "the model was just slow, try the same item again" (it is not a hard failure).
                return {"error": f"Cancelled (timeout): OpenRouter sent nothing for {self.READ_TIMEOUT}s "
                                 f"({type(e).__name__}, model {attempt_model})",
                        "elapsed": round(time.time() - t0, 1), "attempts": calls}
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
