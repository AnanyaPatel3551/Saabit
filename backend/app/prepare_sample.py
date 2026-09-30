"""Prepare the sample's cached metadata. Run at image build: python -m app.prepare_sample."""

from app.api.sample import build_sample_cache, get_sample_cache_dir, get_sample_path


def main() -> None:
    """Scan the bundled sample once and write metadata.json into the sample cache folder."""
    cache_dir = get_sample_cache_dir()
    dataset = build_sample_cache(get_sample_path(), cache_dir)
    print(f"sample {dataset.dataset_id}: {dataset.rows} rows, cache written to {cache_dir}")


if __name__ == "__main__":
    main()
