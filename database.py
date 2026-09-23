import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


def get_n_designs():
    with Session(engine) as session:
        return session.query(DesignTrial.design_id).distinct().count()



# --------------------------------------------
# DATABASE
# --------------------------------------------

# anchored to this file so the DB location doesn't depend on the process's cwd
DB_PATH = Path(__file__).resolve().parent / "allocator.db"
engine = create_engine(f"sqlite:///{DB_PATH}")


# --------------------------------------------
# MODEL
# --------------------------------------------

class Base(DeclarativeBase):
    pass


class Allocation(Base):
    __tablename__ = "allocations"

    participant_id: Mapped[str] = mapped_column(primary_key=True)
    group: Mapped[str]
    design_id: Mapped[int]
    experimenter_id: Mapped[Optional[str]] = mapped_column(default=None)
    raw_data_filename: Mapped[Optional[str]] = mapped_column(default=None)
    raw_data: Mapped[Optional[bytes]] = mapped_column(default=None)


class AllocationState(Base):
    __tablename__ = "allocation_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    pending_groups: Mapped[str]


class DesignState(Base):
    __tablename__ = "design_state"

    group: Mapped[str] = mapped_column(primary_key=True)  # "A" or "P"
    pending_designs: Mapped[str]


class TrialParam(Base):
    __tablename__ = "trial_params"

    movement_trial_id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[float]
    target: Mapped[float]
    amplitude: Mapped[float]
    speed: Mapped[float]
    direction: Mapped[int]


class DesignTrial(Base):
    __tablename__ = "design_trials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    design_id: Mapped[int]
    run_order: Mapped[int]
    timing_id: Mapped[int]
    timing: Mapped[str]
    block: Mapped[int]
    trial_in_block: Mapped[int]
    interference: Mapped[str]
    movement_trial_id: Mapped[int]


class SeqFile(Base):
    __tablename__ = "seq_files"

    design_id: Mapped[int] = mapped_column(primary_key=True)
    group: Mapped[str] = mapped_column(primary_key=True)  # "A" or "P"
    filename: Mapped[str]
    content: Mapped[str]


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]


class Experimenter(Base):
    __tablename__ = "experimenters"

    username: Mapped[str] = mapped_column(primary_key=True)
    salt: Mapped[str]
    password_hash: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[str]
    experimenter_id: Mapped[Optional[str]]
    participant_id: Mapped[Optional[str]]
    action: Mapped[str]
    detail: Mapped[Optional[str]]


class DataVersion(Base):
    __tablename__ = "data_versions"

    name: Mapped[str] = mapped_column(primary_key=True)
    file_hash: Mapped[str]
    imported_at: Mapped[str]


# design_state used to be keyed by a single fixed id; drop and let it get rebuilt
# per-group (from allocation history) since that old shape can't hold two pools.
def _migrate_design_state():
    inspector = inspect(engine)
    if "design_state" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("design_state")}
    if "group" not in columns:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE design_state"))


# adds the raw_data columns to an already-existing allocations table (plain
# ADD COLUMN, so existing participant rows are preserved)
def _migrate_allocations():
    inspector = inspect(engine)
    if "allocations" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("allocations")}
    with engine.begin() as conn:
        if "raw_data_filename" not in columns:
            conn.execute(text("ALTER TABLE allocations ADD COLUMN raw_data_filename TEXT"))
        if "raw_data" not in columns:
            conn.execute(text("ALTER TABLE allocations ADD COLUMN raw_data BLOB"))
        if "experimenter_id" not in columns:
            conn.execute(text("ALTER TABLE allocations ADD COLUMN experimenter_id TEXT"))


_migrate_design_state()
_migrate_allocations()


# adds the approval columns to an already-existing experimenters table
def _migrate_experimenters():
    inspector = inspect(engine)
    if "experimenters" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("experimenters")}
    needs_grandfathering = "is_admin" not in columns or "is_active" not in columns
    with engine.begin() as conn:
        if "is_admin" not in columns:
            conn.execute(text("ALTER TABLE experimenters ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
        if "is_active" not in columns:
            conn.execute(text("ALTER TABLE experimenters ADD COLUMN is_active BOOLEAN DEFAULT 0"))
        if needs_grandfathering:
            # accounts created before the approval system existed were already trusted;
            # grandfather them in as active admins instead of locking everyone out
            conn.execute(text("UPDATE experimenters SET is_admin = 1, is_active = 1"))


_migrate_experimenters()

# Create the database table
Base.metadata.create_all(engine)


# --------------------------------------------
# DATABASE FUNCTIONS
# --------------------------------------------

def save_allocation(participant_id, group, design_id, experimenter_id=None):
    with Session(engine) as session:

        allocation = Allocation(
            participant_id=participant_id,
            group=group,
            design_id=design_id,
            experimenter_id=experimenter_id,
        )

        session.add(allocation)
        session.commit()

def get_allocation(participant_id):
    with Session(engine) as session:
        allocation = session.get(Allocation, participant_id)

        if allocation is None:
            return None

        return allocation.group, allocation.design_id


def get_raw_data(participant_id):
    """Return (filename, content_bytes) for the participant's raw data, or None if not stored."""
    with Session(engine) as session:
        allocation = session.get(Allocation, participant_id)

        if allocation is None or allocation.raw_data is None:
            return None

        return allocation.raw_data_filename, allocation.raw_data


def save_raw_data(participant_id, filename, content):
    with Session(engine) as session:
        allocation = session.get(Allocation, participant_id)

        if allocation is None:
            raise ValueError(f"No allocation found for participant {participant_id!r}.")

        allocation.raw_data_filename = filename
        allocation.raw_data = content
        session.commit()


def load_pending_groups():
    with Session(engine) as session:
        state = session.get(AllocationState, 1)

        if state is None:
            return []

        return json.loads(state.pending_groups)


def save_pending_groups(groups):
    with Session(engine) as session:
        state = session.get(AllocationState, 1)

        if state is None:
            state = AllocationState(id=1, pending_groups=json.dumps(groups))
            session.add(state)
        else:
            state.pending_groups = json.dumps(groups)

        session.commit()


def load_pending_designs(group):
    with Session(engine) as session:
        state = session.get(DesignState, group)

        if state is not None:
            return json.loads(state.pending_designs)

        # first time this group's pool is requested: exclude designs already
        # allocated to that group (e.g. before this per-group split existed)
        used = {
            row.design_id
            for row in session.query(Allocation).filter_by(group=group).all()
        }
        pending = [d for d in range(1, get_n_designs() + 1) if d not in used]
        random.shuffle(pending)
        return pending


def save_pending_designs(group, designs):
    with Session(engine) as session:
        state = session.get(DesignState, group)

        if state is None:
            state = DesignState(group=group, pending_designs=json.dumps(designs))
            session.add(state)
        else:
            state.pending_designs = json.dumps(designs)

        session.commit()


def get_design_trials(design_id):
    """Return the full ordered trial-by-trial sequence for a design, with movement params joined in."""
    with Session(engine) as session:
        rows = (
            session.query(DesignTrial, TrialParam)
            .join(TrialParam, DesignTrial.movement_trial_id == TrialParam.movement_trial_id)
            .filter(DesignTrial.design_id == design_id)
            .order_by(DesignTrial.run_order)
            .all()
        )

        return [
            {
                "run_order": trial.run_order,
                "timing": trial.timing,
                "block": trial.block,
                "trial_in_block": trial.trial_in_block,
                "interference": trial.interference,
                "movement_trial_id": trial.movement_trial_id,
                "start": param.start,
                "target": param.target,
                "amplitude": param.amplitude,
                "speed": param.speed,
                "direction": param.direction,
            }
            for trial, param in rows
        ]


def get_seq_file(design_id, group):
    """Return (filename, content) for the frozen .seq file, or None if not loaded yet."""
    with Session(engine) as session:
        seq_file = session.get(SeqFile, (design_id, group))

        if seq_file is None:
            return None

        return seq_file.filename, seq_file.content


def get_setting(key, default=None):
    with Session(engine) as session:
        setting = session.get(AppSetting, key)

        return setting.value if setting is not None else default


def set_setting(key, value):
    with Session(engine) as session:
        setting = session.get(AppSetting, key)

        if setting is None:
            session.add(AppSetting(key=key, value=value))
        else:
            setting.value = value

        session.commit()


# --------------------------------------------
# EXPERIMENTER LOGIN
# --------------------------------------------

def count_experimenters():
    with Session(engine) as session:
        return session.query(Experimenter).count()


def get_experimenter(username):
    with Session(engine) as session:
        experimenter = session.get(Experimenter, username)

        if experimenter is None:
            return None

        return {
            "username": experimenter.username,
            "salt": experimenter.salt,
            "password_hash": experimenter.password_hash,
            "is_admin": experimenter.is_admin,
            "is_active": experimenter.is_active,
        }


def create_experimenter(username, salt, password_hash, is_admin=False, is_active=False):
    with Session(engine) as session:
        session.add(Experimenter(
            username=username,
            salt=salt,
            password_hash=password_hash,
            is_admin=is_admin,
            is_active=is_active,
        ))
        session.commit()


def list_pending_experimenters():
    with Session(engine) as session:
        rows = session.query(Experimenter).filter_by(is_active=False).order_by(Experimenter.username).all()
        return [row.username for row in rows]


def activate_experimenter(username):
    with Session(engine) as session:
        experimenter = session.get(Experimenter, username)

        if experimenter is None:
            raise ValueError(f"No such experimenter: {username!r}")

        experimenter.is_active = True
        session.commit()


# --------------------------------------------
# AUDIT LOG
# --------------------------------------------

def log_event(experimenter_id, participant_id, action, detail=""):
    with Session(engine) as session:
        session.add(AuditLog(
            timestamp=datetime.now(timezone.utc).isoformat(),
            experimenter_id=experimenter_id,
            participant_id=participant_id,
            action=action,
            detail=detail,
        ))
        session.commit()


# --------------------------------------------
# DATA VERSION TRACKING
# --------------------------------------------

def record_data_version(name, file_hash):
    with Session(engine) as session:
        version = session.get(DataVersion, name)
        imported_at = datetime.now(timezone.utc).isoformat()

        if version is None:
            session.add(DataVersion(name=name, file_hash=file_hash, imported_at=imported_at))
        else:
            version.file_hash = file_hash
            version.imported_at = imported_at

        session.commit()


def get_data_versions():
    with Session(engine) as session:
        return {
            v.name: {"file_hash": v.file_hash, "imported_at": v.imported_at}
            for v in session.query(DataVersion).all()
        }


# --------------------------------------------
# STUDY PROGRESS / EXPORT
# --------------------------------------------

def get_progress_summary():
    with Session(engine) as session:
        return {
            "total": session.query(Allocation).count(),
            "active": session.query(Allocation).filter_by(group="A").count(),
            "passive": session.query(Allocation).filter_by(group="P").count(),
        }


def get_all_allocations():
    with Session(engine) as session:
        rows = session.query(Allocation).order_by(Allocation.participant_id).all()

        return [
            {
                "participant_id": row.participant_id,
                "group": row.group,
                "design_id": row.design_id,
                "experimenter_id": row.experimenter_id,
                "raw_data_filename": row.raw_data_filename,
            }
            for row in rows
        ]

