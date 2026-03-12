from pathlib import Path


def output_root() -> Path:
    return Path(__file__).resolve().parent / "outputs"
