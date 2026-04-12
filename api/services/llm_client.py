from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# Keep a single client instance
_client_instance = None

def get_genai_client():
    global _client_instance
    if _client_instance is None:
        _client_instance = genai.Client(api_key=API_KEY)
    return _client_instance
