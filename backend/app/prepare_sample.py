"""Prepare the sample's cached metadata. Run at image build: python -m app.prepare_sample."""

from app import plan_seed
from app.api.sample import build_sample_cache, get_sample_cache_dir, get_sample_path


def main() -> None:
    """Scan the bundled sample once, write its cache, and load the plan seed into it."""
    cache_dir = get_sample_cache_dir()
    dataset = build_sample_cache(get_sample_path(), cache_dir)
    print(f"sample {dataset.dataset_id}: {dataset.rows} rows, cache written to {cache_dir}")
    current, total = plan_seed.load(cache_dir)
    print(f"plan seed: {current} of {total} entries match the current prompt and sample")
    if total and not current:
        print("WARNING: no seed entry matches; regenerate it with python -m app.plan_seed export")


if __name__ == "__main__":
    main()
