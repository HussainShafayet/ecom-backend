#!/usr/bin/env bash
# Back up the database (pg_dump, custom format) and the uploaded media folder, then delete old backups.
# Run from cron, e.g. daily:  0 3 * * * cd /path/to/backend && scripts/backup.sh
# Settings (environment or .env): DATABASE_URL (required), BACKUP_DIR (default ./backups),
# BACKUP_KEEP_DAYS (default 14). Restore steps: README > Backups.
set -euo pipefail
umask 077  # dumps hold customer data

cd "$(dirname "$0")/.."

env_value() {  # a real environment variable wins over .env, as in the Django settings
    local name=$1
    if [[ -n "${!name:-}" ]]; then
        printf '%s' "${!name}"
    elif [[ -f .env ]]; then
        sed -n "s/^${name}=//p" .env | tail -n 1
    fi
}

DATABASE_URL=$(env_value DATABASE_URL)
BACKUP_DIR=$(env_value BACKUP_DIR)
BACKUP_DIR=${BACKUP_DIR:-./backups}
BACKUP_KEEP_DAYS=$(env_value BACKUP_KEEP_DAYS)
BACKUP_KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}

if [[ -z "$DATABASE_URL" ]]; then
    echo "backup: DATABASE_URL is not set" >&2
    exit 1
fi
if ! [[ "$BACKUP_KEEP_DAYS" =~ ^[0-9]+$ ]] || (( BACKUP_KEEP_DAYS < 1 )); then
    echo "backup: BACKUP_KEEP_DAYS must be a whole number of days, at least 1" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)

# Written under a temporary name first, so a failed run never leaves a half file that looks like a backup.
db_file="$BACKUP_DIR/db-$stamp.dump"
pg_dump --format=custom --no-owner --no-privileges --file="$db_file.partial" "$DATABASE_URL"
mv "$db_file.partial" "$db_file"
echo "backup: database -> $db_file"

# Uploads on the local disk only; with MEDIA_STORAGE_BACKEND=S3 the bucket needs its own backup/versioning.
if [[ -d media ]]; then
    media_file="$BACKUP_DIR/media-$stamp.tar.gz"
    tar -czf "$media_file.partial" media
    mv "$media_file.partial" "$media_file"
    echo "backup: media -> $media_file"
fi

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'media-*.tar.gz' -o -name '*.partial' \) \
    -mtime +"$BACKUP_KEEP_DAYS" -print -delete | sed 's/^/backup: deleted old /'
