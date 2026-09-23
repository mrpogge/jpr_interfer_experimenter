import tkinter as tk
import platform
import re
import sys
import shutil
import csv as csv_module
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from allocator import (
    allocate,
    get_pending_design_pool,
    get_pending_group_block,
    restore_design_pool,
    restore_group_block,
)
from auth import create_admin, login as auth_login, register as auth_register
from backup import backup_db
from database import (
    DB_PATH,
    activate_experimenter,
    count_experimenters,
    engine,
    get_all_allocations,
    get_allocation,
    get_data_versions,
    get_design_trials,
    get_n_designs,
    get_progress_summary,
    get_raw_data,
    get_seq_file,
    get_setting,
    list_pending_experimenters,
    load_pending_designs,
    load_pending_groups,
    log_event,
    save_allocation,
    save_pending_designs,
    save_pending_groups,
    save_raw_data,
    set_setting,
)
from exports import USER_DIR, export_participant
from import_designs import ImportConflict, MATERIAL_DIR, import_design_trials, import_seq_files_from_paths, import_trial_params
from instance_lock import acquire as acquire_instance_lock

# set this to auto-copy every downloaded .seq file into a shared folder as well
AUTO_EXPORT_DIR = None

if not acquire_instance_lock():
    _lock_root = tk.Tk()
    _lock_root.withdraw()
    messagebox.showerror(
        "Already running",
        "Another instance of the Experiment Allocator is already running against this database.",
    )
    sys.exit(1)

# color palette
COLOR_BG = "#f4f5f7"
COLOR_SURFACE = "#ffffff"
COLOR_ACCENT = "#4f46e5"
COLOR_ACCENT_ACTIVE = "#4338ca"
COLOR_TEXT = "#1f2933"
COLOR_MUTED = "#6b7280"
COLOR_BORDER = "#d1d5db"
COLOR_SUCCESS = "#16a34a"
COLOR_WARNING = "#d97706"
COLOR_DANGER = "#dc2626"
FONT_FAMILY = "Segoe UI" if platform.system() == "Windows" else "Helvetica"

PARTICIPANT_ID_PATTERN = re.compile(r"[A-Z0-9_-]+")

restore_group_block(load_pending_groups())
for group in ("A", "P"):
    restore_design_pool(group, load_pending_designs(group))

current_allocation = {"participant_id": None, "group": None, "design_id": None}
current_experimenter = {"username": None, "is_admin": False}


#--------------------------------------------
# HELPER FUNCTIONS 
#--------------------------------------------
def set_status(text, color):
    status_value.config(text=text)
    status_flag.config(bg=color)

#Function connecting the allocator function to the GUI components
def run_allocation():
    participant_id = participant_entry.get().strip().upper()

    if not participant_id:
        set_status("Please enter a participant ID", COLOR_WARNING)
        return

    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
        set_status("Participant ID may only contain letters, numbers, - and _", COLOR_WARNING)
        return

    existing = get_allocation(participant_id)
    if existing is not None:
        group, design_id = existing
        set_status(f"Participant {participant_id} already exists - showing existing allocation.", COLOR_WARNING)
        log_event(current_experimenter["username"], participant_id, "view_existing", f"group={group}, design_id={design_id}")
        display_allocation(participant_id, group, design_id)
        return

    #generate allocation
    try:
        group, design_id = allocate()
    except ValueError:
        set_status("No design data loaded yet. Please ask the admin to upload it in Settings.", COLOR_WARNING)
        return

    #store allocation
    save_allocation(participant_id, group, design_id, experimenter_id=current_experimenter["username"])
    save_pending_groups(get_pending_group_block())
    save_pending_designs(group, get_pending_design_pool(group))
    log_event(current_experimenter["username"], participant_id, "allocate", f"group={group}, design_id={design_id}")
    backup_db()

    set_status(f"Allocation of the new participant {participant_id} was successful.", COLOR_SUCCESS)

    #display allocation
    display_allocation(participant_id, group, design_id)

def display_allocation(participant_id, group, design_id):
    participant_value.config(text=participant_id)
    group_value.config(text=group)
    design_value.config(text=design_id)

    current_allocation["participant_id"] = participant_id
    current_allocation["group"] = group
    current_allocation["design_id"] = design_id
    download_button.config(state=tk.NORMAL)
    upload_raw_button.config(state=tk.NORMAL)

    export_participant(participant_id)
    refresh_data_status()

    for row in trial_table.get_children():
        trial_table.delete(row)

    for i, trial in enumerate(get_design_trials(design_id)):
        tag = "evenrow" if i % 2 == 0 else "oddrow"
        trial_table.insert("", tk.END, tags=(tag,), values=(
            trial["run_order"],
            trial["timing"],
            trial["interference"],
            trial["movement_trial_id"],
            trial["start"],
            trial["target"],
            trial["amplitude"],
            trial["speed"],
        ))

def download_seq():
    group, design_id = current_allocation["group"], current_allocation["design_id"]

    seq_file = get_seq_file(design_id, group)
    if seq_file is None:
        messagebox.showerror(
            "Sequence file missing",
            f"No .seq file loaded for design {design_id} ({group}). Run generate_seq.R and import_designs.py first.",
        )
        return
    filename, content = seq_file

    dest = filedialog.asksaveasfilename(
        initialfile=filename,
        defaultextension=".seq",
        filetypes=[("Sequence files", "*.seq")],
    )
    if not dest:
        return

    try:
        with open(dest, "w", encoding="utf-8", newline="") as f:
            f.write(content)

        if AUTO_EXPORT_DIR is not None:
            with open(AUTO_EXPORT_DIR / filename, "w", encoding="utf-8", newline="") as f:
                f.write(content)
    except OSError as e:
        messagebox.showerror("Could not save file", str(e))
        return

    log_event(current_experimenter["username"], current_allocation["participant_id"], "download_seq", filename)
    set_status(f"Saved {filename}", COLOR_SUCCESS)

#--------------------------------------------
# DATA (proprioceptor .xlsx results)
#--------------------------------------------
def refresh_data_status():
    if get_raw_data(current_allocation["participant_id"]) is not None:
        data_status_value.config(text="Success", foreground=COLOR_SUCCESS)
        download_raw_button.config(state=tk.NORMAL)
    else:
        data_status_value.config(text="No data yet", foreground=COLOR_MUTED)
        download_raw_button.config(state=tk.DISABLED)

def upload_raw_data():
    participant_id = current_allocation["participant_id"]

    chosen = filedialog.askopenfilename(
        title=f"Select raw data file for participant {participant_id}",
        filetypes=[("Excel files", "*.xlsx")],
    )
    if not chosen:
        return
    match = Path(chosen)

    with open(match, "rb") as f:
        save_raw_data(participant_id, match.name, f.read())

    export_participant(participant_id)
    log_event(current_experimenter["username"], participant_id, "upload_raw_data", match.name)
    backup_db()
    refresh_data_status()
    set_status(f"Uploaded raw data ({match.name}) for {participant_id}.", COLOR_SUCCESS)

def download_raw_data():
    participant_id = current_allocation["participant_id"]

    raw = get_raw_data(participant_id)
    if raw is None:
        messagebox.showerror(
            "Raw data missing",
            f"No raw data saved. Please browse for the dataset of participant {participant_id}.",
        )
        return
    filename, content = raw

    dest = filedialog.asksaveasfilename(
        initialfile=filename,
        defaultextension=".xlsx",
        filetypes=[("Excel files", "*.xlsx")],
    )
    if not dest:
        return

    try:
        with open(dest, "wb") as f:
            f.write(content)
    except OSError as e:
        messagebox.showerror("Could not save file", str(e))
        return

    log_event(current_experimenter["username"], participant_id, "download_raw_data", filename)
    set_status(f"Saved {filename}", COLOR_SUCCESS)

#--------------------------------------------
# SETTINGS MODULE
#--------------------------------------------
def upload_design_trials():
    path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
    if not path:
        return

    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    dest = MATERIAL_DIR / "design_trials.csv"
    shutil.copyfile(path, dest)

    try:
        n = import_design_trials(dest)
        settings_status.config(text=f"Imported {n} new design_trials row(s) from material/design_trials.csv.")
        log_event(current_experimenter["username"], None, "upload_design_trials", str(dest))
        refresh_progress()
    except ImportConflict as e:
        messagebox.showerror("Import conflict", str(e))

def upload_trial_params():
    path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
    if not path:
        return

    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    dest = MATERIAL_DIR / "trial_params.csv"
    shutil.copyfile(path, dest)

    try:
        n = import_trial_params(dest)
        settings_status.config(text=f"Imported {n} new trial_params row(s) from material/trial_params.csv.")
        log_event(current_experimenter["username"], None, "upload_trial_params", str(dest))
        refresh_progress()
    except ImportConflict as e:
        messagebox.showerror("Import conflict", str(e))

def upload_seq_files():
    paths = filedialog.askopenfilenames(filetypes=[("Sequence files", "*.seq")])
    if not paths:
        return

    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    dest_paths = []
    for p in paths:
        dest = MATERIAL_DIR / Path(p).name
        shutil.copyfile(p, dest)
        dest_paths.append(dest)

    try:
        n, skipped = import_seq_files_from_paths(dest_paths)
        message = f"Imported {n} new .seq file(s) from material/."
        if skipped:
            message += f" Skipped (bad filename): {', '.join(skipped)}"
        settings_status.config(text=message)
        log_event(current_experimenter["username"], None, "upload_seq_files", ", ".join(str(d) for d in dest_paths))
        refresh_progress()
    except ImportConflict as e:
        messagebox.showerror("Import conflict", str(e))

def refresh_progress():
    summary = get_progress_summary()
    progress_value.config(
        text=(
            f"Total participants: {summary['total']}   |   "
            f"Active: {summary['active']}/{get_n_designs()}   |   Passive: {summary['passive']}/{get_n_designs()}"
        )
    )

    versions = get_data_versions()
    lines = [
        f"{name}: {info['file_hash'][:12]}...  (imported {info['imported_at']})"
        for name, info in versions.items()
    ] or ["No design data imported yet."]
    data_version_value.config(text="\n".join(lines))

def export_all_allocations():
    dest = filedialog.asksaveasfilename(
        initialfile="allocations.csv",
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")],
    )
    if not dest:
        return

    rows = get_all_allocations()
    try:
        with open(dest, "w", newline="", encoding="utf-8") as f:
            writer = csv_module.DictWriter(
                f, fieldnames=["participant_id", "group", "design_id", "experimenter_id", "raw_data_filename"]
            )
            writer.writeheader()
            writer.writerows(rows)
    except OSError as e:
        messagebox.showerror("Could not save file", str(e))
        return

    log_event(current_experimenter["username"], None, "export_all_allocations", dest)
    settings_status.config(text=f"Exported {len(rows)} allocation row(s) to {dest}.")

def save_database_copy():
    dest = filedialog.asksaveasfilename(
        initialfile="allocator_backup.db",
        defaultextension=".db",
        filetypes=[("SQLite database", "*.db")],
    )
    if not dest:
        return

    try:
        shutil.copyfile(DB_PATH, dest)
    except OSError as e:
        messagebox.showerror("Could not save file", str(e))
        return

    log_event(current_experimenter["username"], None, "save_database_copy", dest)
    settings_status.config(text=f"Saved a full copy of the database to {dest}.")

def format_all():
    """Wipes the db/material/user folders for testing, after a type-to-confirm
    safeguard. Existing timestamped backups are left untouched."""
    confirm_win = tk.Toplevel(root)
    confirm_win.title("Format All - Danger Zone")
    confirm_win.geometry("420x340")
    confirm_win.resizable(False, False)

    tk.Label(
        confirm_win, text="⚠ Format All", font=(FONT_FAMILY, 14, "bold"), fg=COLOR_DANGER
    ).pack(pady=(20, 10))
    tk.Label(
        confirm_win,
        text=(
            "This permanently deletes the database (all participants, allocations,\n"
            "experimenter accounts), the material/ folder, and the user/ folder.\n\n"
            "Existing timestamped backups are NOT touched. One more backup is taken\n"
            "right before anything is deleted.\n\n"
            "The app will close immediately afterward - relaunch it to go through\n"
            "admin setup again."
        ),
        wraplength=380, justify="left",
    ).pack(padx=20)

    tk.Label(confirm_win, text='Type "FORMAT" to confirm:').pack(pady=(15, 5))
    confirm_entry = tk.Entry(confirm_win)
    confirm_entry.pack()

    error_label = tk.Label(confirm_win, text="", fg=COLOR_WARNING)
    error_label.pack(pady=(5, 0))

    def do_format(event=None):
        if confirm_entry.get().strip() != "FORMAT":
            error_label.config(text='You must type "FORMAT" exactly.')
            return

        backup_db()
        log_event(current_experimenter["username"], None, "format_all", "wiped db/material/user")

        confirm_win.destroy()
        root.destroy()

        engine.dispose()
        if DB_PATH.exists():
            DB_PATH.unlink()
        if MATERIAL_DIR.exists():
            shutil.rmtree(MATERIAL_DIR)
        if USER_DIR.exists():
            shutil.rmtree(USER_DIR)

    tk.Button(
        confirm_win, text="Permanently Delete Everything",
        command=do_format, bg=COLOR_DANGER, fg="white",
    ).pack(pady=15)
    confirm_win.bind("<Return>", do_format)

    confirm_win.grab_set()
    confirm_entry.focus_set()

##############################################
#MAIN TKINTER
##############################################
root = tk.Tk()
root.title("Experiment Allocator")
root.geometry("1100x900")
root.minsize(900, 750)
root.configure(bg=COLOR_BG)
root.withdraw()

#--------------------------------------------
# FIRST-RUN ADMIN SETUP
#--------------------------------------------
def show_admin_setup():
    """Runs once, only when the experimenters table is completely empty."""
    setup_win = tk.Toplevel(root)
    setup_win.title("Set Up Admin Account")
    setup_win.geometry("360x300")
    setup_win.resizable(False, False)
    setup_win.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

    tk.Label(setup_win, text="Set Up Admin Account", font=(FONT_FAMILY, 13, "bold")).pack(pady=(20, 5))
    tk.Label(setup_win, text="This runs once. Username is fixed to \"admin\".",
             fg=COLOR_MUTED, wraplength=300, justify="center").pack(pady=(0, 10))

    tk.Label(setup_win, text="Admin password:").pack()
    password_entry = tk.Entry(setup_win, show="*")
    password_entry.pack()

    tk.Label(setup_win, text="Confirm password:").pack(pady=(10, 0))
    confirm_entry = tk.Entry(setup_win, show="*")
    confirm_entry.pack()

    error_label = tk.Label(setup_win, text="", fg=COLOR_WARNING, wraplength=300, justify="center")
    error_label.pack(pady=(10, 0))

    def create_admin_account(event=None):
        password = password_entry.get()
        confirm = confirm_entry.get()

        if len(password) < 8:
            error_label.config(text="Password must be at least 8 characters.")
            return
        if password != confirm:
            error_label.config(text="Passwords do not match.")
            return

        create_admin("admin", password)
        setup_win.destroy()

    tk.Button(setup_win, text="Create Admin Account", command=create_admin_account).pack(pady=15)
    setup_win.bind("<Return>", create_admin_account)

    setup_win.grab_set()
    password_entry.focus_set()
    root.wait_window(setup_win)

if count_experimenters() == 0:
    show_admin_setup()

#--------------------------------------------
# LOGIN / REGISTER
#--------------------------------------------
def show_login():
    login_win = tk.Toplevel(root)
    login_win.title("Experimenter Login")
    login_win.geometry("360x360")
    login_win.resizable(False, False)
    login_win.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

    mode = {"value": "login"}

    header_label = tk.Label(login_win, text="Experimenter Login", font=(FONT_FAMILY, 13, "bold"))
    header_label.pack(pady=(20, 10))

    tk.Label(login_win, text="Username:").pack()
    username_entry = tk.Entry(login_win)
    username_entry.pack()

    tk.Label(login_win, text="Password:").pack(pady=(10, 0))
    password_entry = tk.Entry(login_win, show="*")
    password_entry.pack()

    confirm_label = tk.Label(login_win, text="Confirm password:")
    confirm_entry = tk.Entry(login_win, show="*")

    error_label = tk.Label(login_win, text="", fg=COLOR_WARNING, wraplength=320, justify="center")
    error_label.pack(pady=(10, 0))

    action_button = tk.Button(login_win, text="Login")
    action_button.pack(pady=10)

    toggle_button = tk.Button(login_win, text="Need an account? Register")
    toggle_button.pack()

    def set_mode(new_mode):
        mode["value"] = new_mode
        error_label.config(text="")
        if new_mode == "login":
            header_label.config(text="Experimenter Login")
            action_button.config(text="Login", command=attempt_login)
            toggle_button.config(text="Need an account? Register", command=lambda: set_mode("register"))
            confirm_label.pack_forget()
            confirm_entry.pack_forget()
        else:
            header_label.config(text="Register New Experimenter")
            action_button.config(text="Register", command=attempt_register)
            toggle_button.config(text="Already have an account? Login", command=lambda: set_mode("login"))
            confirm_label.pack(after=password_entry, pady=(10, 0))
            confirm_entry.pack(after=confirm_label)

    def attempt_login(event=None):
        username = username_entry.get().strip()
        password = password_entry.get()

        if not username or not password:
            error_label.config(text="Enter both username and password.")
            return

        status, record = auth_login(username, password)
        if status == "not_found":
            error_label.config(text="No such username. Please register below.")
        elif status == "wrong_password":
            error_label.config(text="Incorrect password.")
            password_entry.delete(0, tk.END)
        elif status == "inactive":
            error_label.config(text="Your registration is pending admin approval. Please find the admin to activate your account.")
        else:
            current_experimenter["username"] = record["username"]
            current_experimenter["is_admin"] = record["is_admin"]
            login_win.destroy()

    def attempt_register(event=None):
        username = username_entry.get().strip()
        password = password_entry.get()
        confirm = confirm_entry.get()

        if not username or not password:
            error_label.config(text="Enter both username and password.")
            return
        if len(password) < 8:
            error_label.config(text="Password must be at least 8 characters.")
            return
        if password != confirm:
            error_label.config(text="Passwords do not match.")
            return

        if not auth_register(username, password):
            error_label.config(text="That username is already taken.")
            return

        messagebox.showinfo(
            "Registration submitted",
            "Please find the admin to activate your experimenter registration, then log in with your new credentials.",
        )
        set_mode("login")
        password_entry.delete(0, tk.END)

    set_mode("login")
    login_win.bind("<Return>", lambda e: action_button.invoke())

    login_win.grab_set()
    username_entry.focus_set()
    root.wait_window(login_win)

show_login()
if current_experimenter["username"] is None:
    sys.exit(0)


root.deiconify()

#--------------------------------------------
# STYLE
#--------------------------------------------
style = ttk.Style(root)
style.theme_use("clam")

style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10))
style.configure("TFrame", background=COLOR_BG)
style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
style.configure("Muted.TLabel", foreground=COLOR_MUTED)
style.configure("Value.TLabel", font=(FONT_FAMILY, 12, "bold"))

style.configure("TLabelframe", background=COLOR_BG, bordercolor=COLOR_BORDER)
style.configure("TLabelframe.Label", background=COLOR_BG, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10, "bold"))

style.configure("TButton", font=(FONT_FAMILY, 10), padding=8)
style.configure("Accent.TButton", background=COLOR_ACCENT, foreground="white")
style.map("Accent.TButton",
          background=[("active", COLOR_ACCENT_ACTIVE), ("disabled", COLOR_BORDER)],
          foreground=[("disabled", COLOR_MUTED)])

style.configure("TEntry", padding=6)

style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
style.configure("TNotebook.Tab", padding=(18, 10), font=(FONT_FAMILY, 10, "bold"))
style.map("TNotebook.Tab",
          background=[("selected", COLOR_SURFACE)],
          foreground=[("selected", COLOR_ACCENT)])

style.configure("Treeview", rowheight=26, font=(FONT_FAMILY, 9), fieldbackground=COLOR_SURFACE)
style.configure("Treeview.Heading", font=(FONT_FAMILY, 9, "bold"))

#--------------------------------------------
# TABS: ALLOCATE / VIEW  vs  SETTINGS
#--------------------------------------------
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

allocate_tab = ttk.Frame(notebook, padding=20)
settings_tab = ttk.Frame(notebook)
notebook.add(allocate_tab, text="Allocate / View")
if current_experimenter["is_admin"]:
    notebook.add(settings_tab, text="Settings")

# settings_tab scrolls vertically so any number of cards stays reachable
settings_canvas = tk.Canvas(settings_tab, bg=COLOR_BG, highlightthickness=0)
settings_scrollbar = ttk.Scrollbar(settings_tab, orient="vertical", command=settings_canvas.yview)
settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

settings_scroll_frame = ttk.Frame(settings_canvas, padding=20)
settings_canvas_window = settings_canvas.create_window((0, 0), window=settings_scroll_frame, anchor="nw")

def _on_settings_scroll_frame_configure(event):
    settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))

def _on_settings_canvas_configure(event):
    settings_canvas.itemconfigure(settings_canvas_window, width=event.width)

settings_scroll_frame.bind("<Configure>", _on_settings_scroll_frame_configure)
settings_canvas.bind("<Configure>", _on_settings_canvas_configure)

def _on_settings_mousewheel(event):
    settings_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

def _bind_settings_mousewheel(event):
    settings_canvas.bind_all("<MouseWheel>", _on_settings_mousewheel)

def _unbind_settings_mousewheel(event):
    settings_canvas.unbind_all("<MouseWheel>")

settings_canvas.bind("<Enter>", _bind_settings_mousewheel)
settings_canvas.bind("<Leave>", _unbind_settings_mousewheel)

#--------------------------------------------
# PARTICIPANT ENTRY + SUBMIT
#--------------------------------------------
entry_card = ttk.LabelFrame(allocate_tab, text="New / Existing Participant", padding=15)
entry_card.pack(fill=tk.X, pady=(0, 15))

entry_row = ttk.Frame(entry_card)
entry_row.pack(fill=tk.X)

ttk.Label(entry_row, text="Participant ID:").pack(side=tk.LEFT)
participant_entry = ttk.Entry(entry_row, width=22)
participant_entry.pack(side=tk.LEFT, padx=(10, 0))

action_frame = ttk.Frame(entry_card)
action_frame.pack(fill=tk.X, pady=(15, 0))

submit_button = ttk.Button(
    action_frame,
    text="Submit",
    command=run_allocation,
    style="Accent.TButton",
)
submit_button.pack(side=tk.LEFT)

download_button = ttk.Button(
    action_frame,
    text="Download .seq",
    command=download_seq,
    state=tk.DISABLED,
)
download_button.pack(side=tk.LEFT, padx=(10, 0))

# blends into the background until the first submit sets its color
status_flag = tk.Frame(
    action_frame, width=16, height=16,
    bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER
)
status_flag.pack_propagate(False)
status_flag.pack(side=tk.LEFT, padx=(15, 8))

status_value = ttk.Label(action_frame, text="", style="Muted.TLabel")
status_value.pack(side=tk.LEFT)

#--------------------------------------------
# ALLOCATION RESULT
#--------------------------------------------
result_card = ttk.LabelFrame(allocate_tab, text="Allocation Result", padding=15)
result_card.pack(fill=tk.X, pady=(0, 15))

result_grid = ttk.Frame(result_card)
result_grid.pack(fill=tk.X)

def _result_field(parent, column, label):
    ttk.Label(parent, text=label, style="Muted.TLabel").grid(
        row=0, column=column, sticky="w", padx=(0 if column == 0 else 40, 0)
    )
    value = ttk.Label(parent, text="-", style="Value.TLabel")
    value.grid(row=1, column=column, sticky="w", padx=(0 if column == 0 else 40, 0), pady=(2, 0))
    return value

participant_value = _result_field(result_grid, 0, "Participant")
group_value = _result_field(result_grid, 1, "Group")
design_value = _result_field(result_grid, 2, "Design")

#--------------------------------------------
# TRIAL SEQUENCE TABLE
#--------------------------------------------
trial_card = ttk.LabelFrame(allocate_tab, text="Trial Sequence", padding=15)
trial_card.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

columns = ("run_order", "timing", "interference", "movement_trial_id",
           "start", "target", "amplitude", "speed")
trial_table = ttk.Treeview(trial_card, columns=columns, show="headings", height=10)
for col in columns:
    trial_table.heading(col, text=col)
    trial_table.column(col, width=80, anchor="center")
trial_table.tag_configure("evenrow", background=COLOR_SURFACE)
trial_table.tag_configure("oddrow", background="#f3f4f6")

trial_scrollbar = ttk.Scrollbar(trial_card, orient="vertical", command=trial_table.yview)
trial_table.configure(yscrollcommand=trial_scrollbar.set)
trial_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
trial_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

#--------------------------------------------
# DATA (proprioceptor .xlsx results)
#--------------------------------------------
data_card = ttk.LabelFrame(allocate_tab, text="Data", padding=15)
data_card.pack(fill=tk.X)

data_row = ttk.Frame(data_card)
data_row.pack(fill=tk.X)

upload_raw_button = ttk.Button(
    data_row, text="Upload Raw Data", command=upload_raw_data, style="Accent.TButton", state=tk.DISABLED
)
upload_raw_button.pack(side=tk.LEFT)

data_status_value = ttk.Label(data_row, text="-", style="Muted.TLabel")
data_status_value.pack(side=tk.LEFT, padx=(15, 0))

download_raw_button = ttk.Button(data_row, text="Download Raw Data", command=download_raw_data, state=tk.DISABLED)
download_raw_button.pack(side=tk.LEFT, padx=(10, 0))
#--------------------------------------------
# SETTINGS: UPLOAD DESIGN files
#--------------------------------------------
design_upload_card = ttk.LabelFrame(settings_scroll_frame, text="Upload Design CSVs", padding=15)
design_upload_card.pack(fill=tk.X, pady=(0, 15))

design_upload_row = ttk.Frame(design_upload_card)
design_upload_row.pack(fill=tk.X)
ttk.Button(design_upload_row, text="Upload design_trials.csv", command=upload_design_trials).pack(side=tk.LEFT)
ttk.Button(design_upload_row, text="Upload trial_params.csv", command=upload_trial_params).pack(
    side=tk.LEFT, padx=(10, 0)
)

ttk.Button(design_upload_row, text="Upload .seq files", command=upload_seq_files).pack(side=tk.LEFT, padx=(10, 0))

settings_status = ttk.Label(design_upload_card, text="", style="Muted.TLabel")
settings_status.pack(anchor="w", pady=(10, 0))

#--------------------------------------------
# SETTINGS: STUDY PROGRESS
#--------------------------------------------
progress_card = ttk.LabelFrame(settings_scroll_frame, text="Study Progress", padding=15)
progress_card.pack(fill=tk.X, pady=(15, 0))

progress_value = ttk.Label(progress_card, text="-")
progress_value.pack(anchor="w")

ttk.Label(progress_card, text="Loaded design data version:", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
data_version_value = ttk.Label(progress_card, text="-", style="Muted.TLabel")
data_version_value.pack(anchor="w")

ttk.Button(progress_card, text="Refresh", command=refresh_progress).pack(anchor="w", pady=(10, 0))

#--------------------------------------------
# SETTINGS: EXPORT DATA
#--------------------------------------------
export_card = ttk.LabelFrame(settings_scroll_frame, text="Export Data", padding=15)
export_card.pack(fill=tk.X, pady=(15, 0))
ttk.Button(export_card, text="Export All Allocations to CSV", command=export_all_allocations).pack(anchor="w")

db_backup_card = ttk.LabelFrame(settings_scroll_frame, text="Database Backup", padding=15)
db_backup_card.pack(fill=tk.X, pady=(15, 0))
ttk.Button(db_backup_card, text="Save Entire Database...", command=save_database_copy).pack(anchor="w")

danger_card = ttk.LabelFrame(settings_scroll_frame, text="Danger Zone", padding=15)
danger_card.pack(fill=tk.X, pady=(15, 0))
ttk.Label(
    danger_card,
    text="Wipes the database, material/, and user/ folders. Only for testing before the real experiment.",
    style="Muted.TLabel",
).pack(anchor="w")
tk.Button(
    danger_card, text="Format All...", command=format_all, bg=COLOR_DANGER, fg="white"
).pack(anchor="w", pady=(10, 0))

refresh_progress()

#--------------------------------------------
# SETTINGS: PENDING REGISTRATIONS (admin only)
#--------------------------------------------
if current_experimenter["is_admin"]:
    pending_card = ttk.LabelFrame(settings_scroll_frame, text="Pending Experimenter Registrations", padding=15)
    pending_card.pack(fill=tk.X, pady=(15, 0))

    pending_listbox = tk.Listbox(pending_card, height=5)
    pending_listbox.pack(fill=tk.X)

    def refresh_pending():
        pending_listbox.delete(0, tk.END)
        for username in list_pending_experimenters():
            pending_listbox.insert(tk.END, username)

    def activate_selected():
        selection = pending_listbox.curselection()
        if not selection:
            return

        username = pending_listbox.get(selection[0])
        activate_experimenter(username)
        log_event(current_experimenter["username"], None, "activate_experimenter", username)
        refresh_pending()

    ttk.Button(pending_card, text="Activate Selected", command=activate_selected).pack(anchor="w", pady=(10, 0))
    refresh_pending()

#--------------------------------------------
# BACKUP THE DB ON CLOSE
#--------------------------------------------
def backup_and_close():
    backup_db()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", backup_and_close)

root.mainloop()