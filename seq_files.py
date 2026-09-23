"""Locates the pre-generated .seq files (prereg_code/generate_seq.R -> proprio_seq/)
for a given design_id/group combination."""
from pathlib import Path

PROPRIO_SEQ_DIR = Path(__file__).resolve().parent / "material"
GROUP_LABELS = {"A": "active", "P": "passive"}


def get_seq_path(design_id, group):
    label = GROUP_LABELS[group]
    path = PROPRIO_SEQ_DIR / f"design_{design_id}_{label}.seq"

    if not path.exists():
        raise FileNotFoundError(f"No .seq file found for design {design_id} ({label}) at {path}")

    return path
