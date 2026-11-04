"""SDE loader tuning and the files this app reads. Checked against SDE build 3667080 (2026-11-03)."""

import re

# Raw-loaded files. Typed tables are derived from the first group; the rest stay raw (JSON per
# record) and are read by key: they are small or only needed for a few types.
DEFAULT_INCLUDED_FILES = [
    # typed
    "categories",
    "groups",
    "metaGroups",
    "types",
    "blueprints",
    "mapSolarSystems",
    # raw only
    "typeDogma",
    "dogmaAttributes",
    "dogmaEffects",  # which rig attribute feeds which structure bonus, and security scaling
    "typeMaterials",
    "compressibleTypes",
    "industryModifierSources",
    "industryTargetFilters",
    "marketGroups",
]
# Typed derivation runs parents before children so foreign keys resolve.
TYPED_DERIVATION_ORDER = [
    "categories",
    "groups",
    "metaGroups",
    "types",
    "blueprints",
    "mapSolarSystems",
]

# blueprints.jsonl activity names
ACTIVITIES = (
    "manufacturing",
    "copying",
    "invention",
    "reaction",
    "research_material",
    "research_time",
)

BUILD_INFO_FILE = "_sde"  # 80-byte member: {"_key": "sde", "buildNumber": N, "releaseDate": ...}
BUILD_FILENAME_RE = re.compile(r"eve-online-static-data-(\d+)-jsonl\.zip$")

RAW_BATCH_SIZE = 1000  # 5 bind params per row keeps far below Postgres's 65535 limit
TYPED_BATCH_SIZE = 1000
RAW_ITER_CHUNK = 2000
INCOMING_SETTLE_SECONDS = 60  # a zip still being copied must not be picked up
DOWNLOADS_TO_KEEP = 2
DOWNLOAD_RETRIES = 3
DOWNLOAD_BACKOFF_SECONDS = (5, 15, 45)
DOWNLOAD_CHUNK_BYTES = 1 << 20
DOWNLOAD_HEADROOM = 1.2  # free disk required as a multiple of Content-Length
DOWNLOAD_FALLBACK_BYTES = 300 << 20  # when Content-Length is missing
SDE_IMPORT_LOCK_KEY = 0x45494E31  # "EIN1"; pg advisory lock shared by CLI and cron
