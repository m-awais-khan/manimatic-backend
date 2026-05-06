from django.apps import AppConfig
import sys
import logging

logger = logging.getLogger(__name__)

class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Eagerly load the AI models on the MAIN thread to prevent worker thread segfaults
        if 'runserver' in sys.argv:
            try:
                logger.info("Initializing RAG Embedder on the main thread...")
                from .services.prompt_enhancer import _get_embedder, _get_collection
                _get_embedder()
                _get_collection()
                logger.info("RAG Embedder initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to eagerly load RAG models: {e}")
