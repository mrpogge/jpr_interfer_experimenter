"""Import of the R-generated design CSVs (material/design_trials.csv,
material/trial_params.csv) and the generated .seq files (proprio_seq/) into the
allocator SQLite database.

Existing rows are never overwritten: only keys not yet in the database are
inserted. If a CSV row disagrees with an already-loaded row (same key, different
values), an ImportConflict is raised instead of silently changing data that may
already have been handed out to a participant.
"""
import csv
import hashlib
from pathlib import Path
import re

from sqlalchemy.orm import Session

from database import DesignTrial, SeqFile, TrialParam, engine, record_data_version
from seq_files import GROUP_LABELS, PROPRIO_SEQ_DIR

MATERIAL_DIR = Path(__file__).resolve().parent / "material"
SEQ_FILENAME_PATTERN = re.compile(r"^design_(\d+)_(active|passive)\.seq$")

class ImportConflict(Exception):
    """Raised when a CSV row would change data that has already been loaded."""


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_trial_param(row):
    return dict(
        movement_trial_id=int(row["movement_trial_id"]),
        start=float(row["start"]),
        target=float(row["target"]),
        amplitude=float(row["amplitude"]),
        speed=float(row["speed"]),
        direction=int(row["direction"]),
    )


def _parse_design_trial(row):
    return dict(
        design_id=int(row["design_id"]),
        run_order=int(row["run_order"]),
        timing_id=int(row["timing_id"]),
        timing=row["timing"],
        block=int(row["block"]),
        trial_in_block=int(row["trial_in_block"]),
        interference=row["interference"],
        movement_trial_id=int(row["movement_trial_id"]),
    )


def import_trial_params(path=MATERIAL_DIR / "trial_params.csv"):
    with Session(engine) as session, open(path, newline="") as f:
        existing = {p.movement_trial_id: p for p in session.query(TrialParam).all()}
        conflicts, inserted = [], 0

        for raw in csv.DictReader(f):
            parsed = _parse_trial_param(raw)
            current = existing.get(parsed["movement_trial_id"])

            if current is None:
                session.add(TrialParam(**parsed))
                inserted += 1
            elif any(getattr(current, k) != v for k, v in parsed.items()):
                conflicts.append(parsed["movement_trial_id"])

        if conflicts:
            session.rollback()
            raise ImportConflict(
                f"trial_params.csv differs from already-loaded movement_trial_id(s) {conflicts}; "
                "existing rows are never overwritten automatically."
            )

        session.commit()
        record_data_version("trial_params", _file_hash(path))
        return inserted


def import_design_trials(path=MATERIAL_DIR / "design_trials.csv"):
    with Session(engine) as session, open(path, newline="") as f:
        existing = {(d.design_id, d.run_order): d for d in session.query(DesignTrial).all()}
        conflicts, inserted = [], 0

        for raw in csv.DictReader(f):
            parsed = _parse_design_trial(raw)
            key = (parsed["design_id"], parsed["run_order"])
            current = existing.get(key)

            if current is None:
                session.add(DesignTrial(**parsed))
                inserted += 1
            elif any(getattr(current, k) != v for k, v in parsed.items()):
                conflicts.append(key)

        if conflicts:
            session.rollback()
            raise ImportConflict(
                f"design_trials.csv differs from already-loaded (design_id, run_order) {conflicts}; "
                "existing rows are never overwritten automatically."
            )

        session.commit()
        record_data_version("design_trials", _file_hash(path))
        return inserted


def import_seq_files(seq_dir=PROPRIO_SEQ_DIR):
    with Session(engine) as session:
        existing = {(s.design_id, s.group): s for s in session.query(SeqFile).all()}
        design_ids = {row.design_id for row in session.query(DesignTrial.design_id).distinct()}
        conflicts, inserted = [], 0

        for design_id in design_ids:
            for group, label in GROUP_LABELS.items():
                path = seq_dir / f"design_{design_id}_{label}.seq"
                if not path.exists():
                    continue

                with open(path, "r", encoding="utf-8", newline="") as f:
                    content = f.read()

                key = (design_id, group)
                current = existing.get(key)

                if current is None:
                    session.add(SeqFile(design_id=design_id, group=group, filename=path.name, content=content))
                    inserted += 1
                elif current.filename != path.name or current.content != content:
                    conflicts.append(key)

        if conflicts:
            session.rollback()
            raise ImportConflict(
                f".seq files differ from already-loaded (design_id, group) {conflicts}; "
                "existing rows are never overwritten automatically."
            )

        session.commit()
        return inserted

def _parse_seq_filename(filename):
    match = SEQ_FILENAME_PATTERN.match(filename)
    if not match:
        raise ValueError(
            f"'{filename}' doesn't match the required 'design_<id>_<active|passive>.seq' naming pattern."
        )
    design_id = int(match.group(1))
    group = "A" if match.group(2) == "active" else "P"
    return design_id, group


def import_seq_files_from_paths(paths):
    """Import specific .seq files chosen by the admin (e.g. via a file picker),
    rather than scanning proprio_seq/. Same insert-only/conflict-safe behavior."""
    with Session(engine) as session:
        existing = {(s.design_id, s.group): s for s in session.query(SeqFile).all()}
        conflicts, inserted, skipped = [], 0, []

        for raw_path in paths:
            path = Path(raw_path)
            try:
                design_id, group = _parse_seq_filename(path.name)
            except ValueError:
                skipped.append(path.name)
                continue

            with open(path, "r", encoding="utf-8", newline="") as f:
                content = f.read()

            key = (design_id, group)
            current = existing.get(key)

            if current is None:
                session.add(SeqFile(design_id=design_id, group=group, filename=path.name, content=content))
                inserted += 1
            elif current.filename != path.name or current.content != content:
                conflicts.append(key)

        if conflicts:
            session.rollback()
            raise ImportConflict(
                f"Uploaded .seq files differ from already-loaded (design_id, group) {conflicts}; "
                "existing rows are never overwritten automatically."
            )

        session.commit()
        return inserted, skipped


if __name__ == "__main__":
    n_params = import_trial_params()
    n_trials = import_design_trials()
    n_seqs = import_seq_files()
    print(
        f"Inserted {n_params} new trial_params row(s), {n_trials} new design_trials row(s), "
        f"and {n_seqs} new seq_files row(s); existing rows were left untouched."
    )


