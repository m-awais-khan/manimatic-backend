from streamlit import cache_resource
from openai import OpenAI
from config import API_KEY, BASE_URL

# Initialize and cache the OpenAI client
@cache_resource
def get_openai_client():
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)
