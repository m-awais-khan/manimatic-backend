from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

API_KEY = os.getenv("MY_OPENROUTER_API_KEY") # Load environment variable
BASE_URL = "https://openrouter.ai/api/v1"
MODEL_NAME = "qwen/qwen3-coder:free"

OUTPUT_DIR = "generated_videos"
os.makedirs(OUTPUT_DIR, exist_ok=True)
