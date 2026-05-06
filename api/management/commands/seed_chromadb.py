"""
Management command: seed_chromadb
Usage: python manage.py seed_chromadb

Reads all prompts from fine_tuning/manim_dataset.json, embeds them with
SentenceTransformers ('all-MiniLM-L6-v2'), and persists them to a local
ChromaDB collection at backend/chroma_db/.

Run this ONCE after setting up the project, or any time the dataset grows.
Re-running is safe -- the collection is cleared and rebuilt from scratch.
"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Embed manim_dataset.json instructions into a local ChromaDB collection for RAG-powered prompt enhancement."

    def handle(self, *args, **options):
        import traceback
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "Missing dependencies. Run:\n  pip install chromadb sentence-transformers"
            ))
            return

        try:
            # ── 1. Locate dataset ──────────────────────────────────────────────
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent  # project root
            dataset_path = base_dir / "fine_tuning" / "manim_dataset.json"

            if not dataset_path.exists():
                self.stderr.write(self.style.ERROR(f"Dataset not found at: {dataset_path}"))
                return

            self.stdout.write(f"[*] Loading dataset from: {dataset_path}")
            with open(dataset_path, "r", encoding="utf-8") as f:
                dataset = json.load(f)

            self.stdout.write(f"[+] Loaded {len(dataset)} examples.")

            # ── 2. Init ChromaDB (persisted on disk) ──────────────────────────
            chroma_dir = Path(__file__).resolve().parent.parent.parent.parent / "chroma_db"
            chroma_dir.mkdir(parents=True, exist_ok=True)

            self.stdout.write(f"[*] ChromaDB directory: {chroma_dir}")
            client = chromadb.PersistentClient(path=str(chroma_dir))

            # Drop & recreate for a clean rebuild
            try:
                client.delete_collection("manim_prompts")
            except Exception:
                pass

            collection = client.create_collection(
                name="manim_prompts",
                metadata={"hnsw:space": "cosine"},
            )

            # ── 3. Embed with SentenceTransformers ────────────────────────────
            self.stdout.write("[*] Loading SentenceTransformer (all-MiniLM-L6-v2)...")
            model = SentenceTransformer("all-MiniLM-L6-v2")

            instructions = [item["instruction"] for item in dataset]
            ids = [item.get("id", f"item-{i}") for i, item in enumerate(dataset)]
            categories = [item.get("category", "General") for item in dataset]

            self.stdout.write(f"[*] Embedding {len(instructions)} prompts...")
            embeddings = model.encode(instructions, show_progress_bar=True, batch_size=64)

            # ── 4. Upsert into ChromaDB in batches ────────────────────────────
            BATCH_SIZE = 100
            for i in range(0, len(instructions), BATCH_SIZE):
                batch_emb = embeddings[i : i + BATCH_SIZE].tolist()
                batch_doc = instructions[i : i + BATCH_SIZE]
                batch_ids = ids[i : i + BATCH_SIZE]
                batch_meta = [{"category": c} for c in categories[i : i + BATCH_SIZE]]

                collection.add(
                    embeddings=batch_emb,
                    documents=batch_doc,
                    ids=batch_ids,
                    metadatas=batch_meta,
                )

            self.stdout.write(self.style.SUCCESS(
                f"\n[+] Done! {len(instructions)} prompts embedded and saved to {chroma_dir}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error during seeding: {e}"))
            traceback.print_exc()
