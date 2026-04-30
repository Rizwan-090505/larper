import sys
import asyncio
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.retrieval import search_and_enrich_blocks
from src.ingestion.db.schema import init_db


async def main():
    # Initialize DB/schema only
    await init_db()

    while True:
        query = input("\nEnter your query (or type 'exit'): ").strip()

        if query.lower() == "exit":
            print("Exiting...")
            break

        if not query:
            print("Please enter a valid query.")
            continue

        try:
            results = await search_and_enrich_blocks(query, k=5)

            print("\nTop Retrieval Results:\n")

            if not results:
                print("No matching results found.")
                continue

            for i, result in enumerate(results, start=1):
                print("=" * 70)
                print(f"Rank      : {i}")
                print(f"Block ID  : {result.get('id')}")
                print(f"Score     : {result.get('similarity_score')}")
                print(f"File Path : {result.get('file_path')}")
                print(f"Content   : {result.get('content')}")
                print(f"Related   : {result.get('related_blocks')}")
                print("=" * 70)

        except Exception as e:
            print(f"\nError during retrieval: {e}")


if __name__ == "__main__":
    asyncio.run(main())