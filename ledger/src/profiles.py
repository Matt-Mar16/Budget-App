"""
profiles.py — multi-user profile registry for The Ledger.

Each profile is a completely separate SQLite database (own transactions,
budgets, debts, accounts, settings). Profiles are lightweight — a person
sharing a computer with a partner, or someone who wants a "Personal" and
a "Side Business" ledger, can switch between them without any data mixing.

There is deliberately no central profiles.json anymore. Every profile gets
its own subfolder under "Profiles" (Profiles/<slug>/profile.db) — this
module just scans that folder and reads each database's own `meta` table
(name/avatar/color/created/last_opened) via finance_core.Database. This
means a stray typo in a JSON file can never make profiles silently
disappear, and dropping a profile folder in (from a backup, a share,
another machine) makes it show up automatically — no import step required,
though import_existing_db() is still offered as a convenience for a .db
file living elsewhere on disk (or as a bare flat file).

Per-profile subfolders (not just per-profile files) exist so a profile's
own editable CSV exports (transactions.csv, accounts.csv, etc. — see
finance_core.py's export_*_editable_csv functions) can live right next to
its database, instead of all profiles' CSVs being dumped into one shared
folder. Older profiles stored as a flat Profiles/<slug>.db file are
migrated into Profiles/<slug>/profile.db automatically and transparently
the first time list_profiles() runs — see _migrate_flat_profiles().

Everything lives in a "Profiles" folder next to budget_app.py — not buried in
a hidden home-directory folder, and not mixed in with the .py source files
in src/ either, so it's easy to find, back up, or move to another machine.
Nothing leaves the machine on its own.
"""

import os
import re
import shutil
import sqlite3
import datetime

# "Profiles" sits next to budget_app.py (one level up from this file, which
# lives in src/), wherever the app happens to be run from — not the current
# working directory, so it stays in one place regardless of how the app is
# launched.
APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Profiles")

DB_FILENAME = "profile.db"

# A small curated palette so auto-assigned profile colors always look good
# together, rather than random hex values that might clash with the theme.
PALETTE = [
    "#5B8DEF", "#4CC9A0", "#F2994A", "#E56399",
    "#9B7EDE", "#43B7C5", "#E4574C", "#C9A227",
]

AVATARS = ["🦉", "🦊", "🐢", "🐬", "🦁", "🐝", "🐧", "🦄", "🐙", "🦋"]


def _ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)


def _migrate_flat_profiles():
    """One-time, transparent migration: older versions stored each profile
    as a flat Profiles/<slug>.db (and Profiles/<slug>.db.locked) file.
    Moves any such file into its own Profiles/<slug>/ subfolder under the
    new name, so profiles created before this change keep working with no
    action needed. Safe to call on every list_profiles() — a no-op once
    everything's already migrated."""
    if not os.path.isdir(APP_DIR):
        return
    for fname in list(os.listdir(APP_DIR)):
        full = os.path.join(APP_DIR, fname)
        if not os.path.isfile(full):
            continue
        if fname.endswith(".db.locked"):
            slug, new_name = fname[: -len(".db.locked")], DB_FILENAME + ".locked"
        elif fname.endswith(".db"):
            slug, new_name = fname[:-3], DB_FILENAME
        else:
            continue
        profile_dir = os.path.join(APP_DIR, slug)
        os.makedirs(profile_dir, exist_ok=True)
        dest = os.path.join(profile_dir, new_name)
        if not os.path.exists(dest):
            shutil.move(full, dest)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_")
    return slug or "profile"


def profile_dir_for(slug: str) -> str:
    _ensure_dir()
    profile_dir = os.path.join(APP_DIR, slug)
    os.makedirs(profile_dir, exist_ok=True)
    return profile_dir


def db_path_for(slug: str) -> str:
    return os.path.join(profile_dir_for(slug), DB_FILENAME)


def _read_meta(db_path: str) -> dict:
    """Reads just the meta table from a .db file with a short-lived plain
    sqlite3 connection — deliberately NOT finance_core.Database, so listing
    profiles never triggers a schema migration as a side effect of simply
    building the launcher screen."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
            return {r["key"]: r["value"] for r in rows}
        except sqlite3.OperationalError:
            return {}  # meta table doesn't exist yet (very old/unmigrated db)
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return {}  # file locked, not a valid sqlite db, etc.


def _existing_slugs() -> set:
    _ensure_dir()
    _migrate_flat_profiles()
    slugs = set()
    for entry in os.listdir(APP_DIR):
        full = os.path.join(APP_DIR, entry)
        if not os.path.isdir(full):
            continue
        if os.path.exists(os.path.join(full, DB_FILENAME)) or \
                os.path.exists(os.path.join(full, DB_FILENAME + ".locked")):
            slugs.add(entry)
    return slugs


def list_profiles() -> list:
    """Scans Profiles/<slug>/ subfolders and returns one dict per profile,
    sorted by last_opened (most recent first). A subfolder only counts as
    a profile if it actually contains profile.db or profile.db.locked —
    other folders that might sit alongside profiles (e.g. a stray backups
    directory) are silently skipped. Locked profiles can't have their meta
    read without the password, so they're listed with a placeholder
    name/flag and must be unlocked before opening.
    Shape: {slug, name, avatar, color, created, last_opened, locked}."""
    _ensure_dir()
    _migrate_flat_profiles()
    out = []
    for idx, slug in enumerate(sorted(os.listdir(APP_DIR))):
        profile_dir = os.path.join(APP_DIR, slug)
        if not os.path.isdir(profile_dir):
            continue
        db_path = os.path.join(profile_dir, DB_FILENAME)
        locked_path = db_path + ".locked"
        if os.path.exists(db_path):
            meta = _read_meta(db_path)
            out.append({
                "slug": slug,
                "name": meta.get("profile_name") or slug.replace("_", " ").title(),
                "avatar": meta.get("avatar") or AVATARS[idx % len(AVATARS)],
                "color": meta.get("color") or PALETTE[idx % len(PALETTE)],
                "created": meta.get("created") or "",
                "last_opened": meta.get("last_opened") or "",
                "locked": False,
            })
        elif os.path.exists(locked_path):
            out.append({
                "slug": slug,
                "name": slug.replace("_", " ").title() + " (locked)",
                "avatar": "🔒",
                "color": "#666C82",
                "created": "",
                "last_opened": "",
                "locked": True,
            })
    return sorted(out, key=lambda p: p["last_opened"], reverse=True)


def find_unregistered_db_files() -> list:
    """Kept for budget_app.py compatibility. With directory scanning, any
    .db file sitting in Profiles/ IS already a profile — there's no
    'unregistered' state anymore, so this always returns []. .db files
    from elsewhere on disk still go through import_existing_db() below;
    once copied in, list_profiles() picks them up on its own."""
    return []


def create_profile(display_name: str, avatar: str = None, color: str = None) -> dict:
    from finance_core import Database  # local import: keeps pure listing lightweight

    existing = _existing_slugs()
    base_slug = _slugify(display_name)
    slug = base_slug
    n = 2
    while slug in existing:
        slug = f"{base_slug}_{n}"
        n += 1

    idx = len(existing)
    path = db_path_for(slug)
    db = Database(path)
    today = datetime.date.today().isoformat()
    db.set_meta("profile_name", display_name.strip() or "Profile")
    db.set_meta("avatar", avatar or AVATARS[idx % len(AVATARS)])
    db.set_meta("color", color or PALETTE[idx % len(PALETTE)])
    db.set_meta("created", today)
    db.set_meta("last_opened", today)
    db.close()

    return {
        "slug": slug,
        "name": display_name.strip() or "Profile",
        "avatar": avatar or AVATARS[idx % len(AVATARS)],
        "color": color or PALETTE[idx % len(PALETTE)],
        "created": today,
        "last_opened": today,
    }


def import_existing_db(source_path: str, display_name: str = None) -> dict:
    """Registers a .db file as a profile — copied in from elsewhere on disk
    (or already sitting inside Profiles/, in which case it's just adopted
    in place). Stamps meta fields as needed so the launcher shows something
    sensible even if the source file had no meta table at all."""
    import shutil
    from finance_core import Database

    _ensure_dir()
    source_path = os.path.abspath(source_path)
    base_name = display_name or os.path.splitext(os.path.basename(source_path))[0]

    existing = _existing_slugs()
    base_slug = _slugify(base_name)
    slug = base_slug
    n = 2
    while slug in existing:
        slug = f"{base_slug}_{n}"
        n += 1

    dest_path = db_path_for(slug)
    if os.path.abspath(dest_path) != source_path:
        shutil.copy2(source_path, dest_path)

    idx = len(existing)
    db = Database(dest_path)  # triggers a schema migration on the imported file, safely
    today = datetime.date.today().isoformat()
    if not db.get_meta("profile_name") or db.get_meta("profile_name") == "Profile":
        db.set_meta("profile_name", (display_name or base_name).strip() or "Imported Profile")
    if not db.get_meta("avatar"):
        db.set_meta("avatar", AVATARS[idx % len(AVATARS)])
    if not db.get_meta("color"):
        db.set_meta("color", PALETTE[idx % len(PALETTE)])
    if not db.get_meta("created"):
        db.set_meta("created", today)
    db.set_meta("last_opened", today)
    name, avatar, color, created = (db.get_meta("profile_name"), db.get_meta("avatar"),
                                     db.get_meta("color"), db.get_meta("created"))
    db.close()

    return {"slug": slug, "name": name, "avatar": avatar, "color": color,
            "created": created, "last_opened": today}


def touch_profile(slug: str):
    from finance_core import Database
    path = db_path_for(slug)
    if not os.path.exists(path):
        return
    db = Database(path)
    db.touch_last_opened()
    db.close()


def rename_profile(slug: str, new_name: str):
    from finance_core import Database
    path = db_path_for(slug)
    if not os.path.exists(path):
        return
    db = Database(path)
    if new_name.strip():
        db.set_meta("profile_name", new_name.strip())
    db.close()


def lock_profile(slug: str, password: str):
    """Password-protects a profile's .db file (see crypto_utils for the
    honest limitations of this). The .db file is replaced by a .db.locked
    sidecar; caller must have already closed any open Database connection
    to this profile before calling this."""
    import crypto_utils
    from finance_core import Database
    path = db_path_for(slug)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No profile found for slug '{slug}'.")
    db = Database(path)
    db.set_encrypted(True)
    db.close()
    return crypto_utils.lock_file(path, password)


def unlock_profile(slug: str, password: str):
    """Decrypts a .db.locked file back into a usable .db file. Raises
    RuntimeError on wrong password."""
    import crypto_utils
    from finance_core import Database
    locked_path = os.path.join(profile_dir_for(slug), DB_FILENAME + crypto_utils.LOCKED_SUFFIX)
    dest_path = crypto_utils.unlock_file(locked_path, password)
    db = Database(dest_path)
    db.set_encrypted(False)
    db.touch_last_opened()
    db.close()
    os.remove(locked_path)
    return dest_path


def is_profile_locked(slug: str) -> bool:
    import crypto_utils
    return os.path.exists(os.path.join(profile_dir_for(slug), DB_FILENAME + crypto_utils.LOCKED_SUFFIX))


def delete_profile(slug: str, delete_data: bool = False):
    """With no central registry, 'un-registering' a profile just means
    deleting its whole subfolder — the database, any CSV exports sitting
    alongside it, everything. If delete_data=False, nothing on disk is
    touched (kept for signature compatibility with the old JSON-registry
    version, where this controlled whether the data file itself was also
    wiped)."""
    profile_dir = os.path.join(APP_DIR, slug)
    if not delete_data:
        return True
    if not os.path.isdir(profile_dir):
        return True
    import gc
    import time
    gc.collect()  # drop any lingering sqlite3.Connection so its file handle releases (matters on Windows)
    for attempt in range(3):
        try:
            shutil.rmtree(profile_dir)
            return True
        except OSError:
            if attempt < 2:
                time.sleep(0.2)
    return False
