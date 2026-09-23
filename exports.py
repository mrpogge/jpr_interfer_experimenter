"""Per-participant backup of the allocation row + raw data, written to
allocatorApp/user/<participant_id>/ for manual inspection/recovery."""
import csv
from paths import USER_DIR
from database import get_allocation, get_raw_data

def export_participant(participant_id):
    allocation = get_allocation(participant_id)
    if allocation is None:
        return

    group = allocation["group"] 
    design_id = allocation["design_id"]
    handedness = allocation["handedness"] if "handedness" in allocation else None
    raw = get_raw_data(participant_id)
    raw_data_filename = raw[0] if raw is not None else ""

    participant_dir = USER_DIR / participant_id
    participant_dir.mkdir(parents=True, exist_ok=True)

    with open(participant_dir / f"{participant_id}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["participant_id", "group", "design_id", "handedness", "raw_data_filename"])
        writer.writerow([participant_id, group, design_id, handedness, raw_data_filename])

    if raw is not None:
        filename, content = raw
        with open(participant_dir / filename, "wb") as f:
            f.write(content)
