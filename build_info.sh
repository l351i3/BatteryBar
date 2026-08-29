#!/bin/bash

ROOT="$HOME/BatteryBar"

printf '%s\n' "===== PROJECT ROOT ====="
printf '%s\n' "$ROOT"

printf '%s\n' "===== ROOT CONTENTS ====="
/bin/ls -la "$ROOT"

printf '%s\n' "===== DIRECTORY TREE ====="
/usr/bin/find "$ROOT" \
  \( -path "$ROOT/.git" \
  -o -path "$ROOT/.git/*" \
  -o -path "$ROOT/.venv" \
  -o -path "$ROOT/.venv/*" \
  -o -path "$ROOT/venv" \
  -o -path "$ROOT/venv/*" \
  -o -path "$ROOT/node_modules" \
  -o -path "$ROOT/node_modules/*" \
  -o -path "$ROOT/dist" \
  -o -path "$ROOT/dist/*" \
  -o -path "$ROOT/Widget/BatteryBarNative/build-release" \
  -o -path "$ROOT/Widget/BatteryBarNative/build-release/*" \
  -o -path "*/DerivedData" \
  -o -path "*/DerivedData/*" \) -prune \
  -o -print |
  /usr/bin/sed "s|^$ROOT|.|" |
  /usr/bin/sort

printf '%s\n' "===== TOP-LEVEL SIZES ====="
/usr/bin/du -sh "$ROOT"/* "$ROOT"/.[!.]* "$ROOT"/..?* 2>/dev/null |
  /usr/bin/sort -h

printf '%s\n' "===== GIT STATUS ====="
if /usr/bin/git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  /usr/bin/git -C "$ROOT" status --short
  printf 'branch='
  /usr/bin/git -C "$ROOT" branch --show-current
  printf 'commit='
  /usr/bin/git -C "$ROOT" rev-parse HEAD
else
  printf '%s\n' "NOT_A_GIT_REPOSITORY"
fi

printf '%s\n' "===== EXISTING BACKUP ====="
/bin/ls -lh "$HOME/BatteryBar_source_backup.tar.gz" 2>&1 || true