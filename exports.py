"""Per-participant backup of allocation, expected trial structure, and raw data."""

from openpyxl import Workbook

from database import get_allocation, get_design_trials, get_raw_data
from paths import USER_DIR


def export_participant(participant_id):
    allocation = get_allocation(participant_id)

    if allocation is None:
        return

    group = allocation["group"]
    design_id = allocation["design_id"]
    handedness = allocation["handedness"]

    raw = get_raw_data(participant_id)

    participant_dir = USER_DIR / participant_id
    participant_dir.mkdir(parents=True, exist_ok=True)

    columns = [
        "participant_id",
        "group",
        "design_id",
        "handedness",
        "run_order",
        "timing",
        "interference",
        "movement_trial_id",
        "start",
        "target",
        "amplitude",
        "speed",
    ]

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Data"

    worksheet.append(columns)

    for trial in get_design_trials(design_id):
        worksheet.append([
            participant_id,
            group,
            design_id,
            handedness,
            trial["run_order"],
            trial["timing"],
            trial["interference"],
            trial["movement_trial_id"],
            trial["start"],
            trial["target"],
            trial["amplitude"],
            trial["speed"],
        ])

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    for column_cells in worksheet.columns:
        max_length = max(
            len(str(cell.value)) if cell.value is not None else 0
            for cell in column_cells
        )
        worksheet.column_dimensions[
            column_cells[0].column_letter
        ].width = min(max_length + 2, 30)

    workbook.save(
        participant_dir / f"{participant_id}_data_template.xlsx"
    )

    # --------------------------------------------------
    # 3. Raw Proprioceptor data
    # --------------------------------------------------
    if raw is not None:
        filename, content = raw

        with open(participant_dir / filename, "wb") as f:
            f.write(content)