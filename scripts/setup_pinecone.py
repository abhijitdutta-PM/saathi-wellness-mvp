"""Create/check the configured Pinecone index. Run from the project root after editing .env."""
from pathlib import Path
import sys

# Running ``python scripts\setup_pinecone.py`` puts ``scripts`` rather than the
# project root at sys.path[0]. Add the project root so ``from app...`` works.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402


def main() -> None:
    if not settings.pinecone_api_key:
        raise SystemExit("Set PINECONE_API_KEY in your local .env. Do not paste it into chat or commit it.")
    try:
        from pinecone import Pinecone, ServerlessSpec
    except ImportError as exc:
        raise SystemExit("Pinecone SDK missing. Run scripts/setup-local.ps1 or pip install -r requirements.txt.") from exc

    pc = Pinecone(api_key=settings.pinecone_api_key)
    name = settings.pinecone_index_name
    if not pc.has_index(name):
        print(f"Creating index '{name}' in {settings.pinecone_cloud}/{settings.pinecone_region}, dimension={settings.pinecone_dimension}...")
        pc.create_index(
            name=name,
            dimension=settings.pinecone_dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
        )
    desc = pc.describe_index(name)
    dimension = getattr(desc, "dimension", None) if not isinstance(desc, dict) else desc.get("dimension")
    host = getattr(desc, "host", None) if not isinstance(desc, dict) else desc.get("host")
    status = getattr(desc, "status", {}) if not isinstance(desc, dict) else desc.get("status", {})
    ready = getattr(status, "ready", None) if not isinstance(status, dict) else status.get("ready")
    if dimension != settings.pinecone_dimension:
        raise SystemExit(f"Index dimension is {dimension}; .env expects {settings.pinecone_dimension}. Use a new index or fix .env/model output.")
    print(f"Index exists. name={name}; dimension={dimension}; host={host}; ready={ready}")
    print("Next: start the app; it will sync approved shared knowledge and pending tenant resources. Query-vector search is disabled until PINECONE_QUERY_VECTORS_ENABLED=true.")


if __name__ == "__main__":
    main()
