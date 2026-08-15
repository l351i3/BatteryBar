#!/usr/bin/env python3

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from snapshot_store import (
    DEFAULT_SNAPSHOT_PATH,
)


WIDGET_BUNDLE_ID = (
    "io.github.l351i3."
    "batterybar.widgethost.widget"
)

HOST_BUNDLE_ID = (
    "io.github.l351i3."
    "batterybar.widgethost"
)

DEFAULT_WIDGET_SNAPSHOT_PATH = (
    Path.home()
    / "Library"
    / "Containers"
    / WIDGET_BUNDLE_ID
    / "Data"
    / "Library"
    / "Application Support"
    / "Battery Bar"
    / "snapshot.json"
)

DEFAULT_HOST_SNAPSHOT_PATH = (
    Path.home()
    / "Library"
    / "Containers"
    / HOST_BUNDLE_ID
    / "Data"
    / "Library"
    / "Application Support"
    / "Battery Bar"
    / "snapshot.json"
)


class WidgetSnapshotSyncError(Exception):
    pass


def _fsync_directory(directory):
    flags = os.O_RDONLY

    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    
    descriptor = None
    
    try:
        descriptor = os.open(
            str(directory),
            flags,
        )
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _sync_to_target(
    source_path,
    target_path,
):
    if (
        source_path.resolve(strict=False)
        == target_path.resolve(strict=False)
    ):
        raise ValueError(
            "source and target must differ"
        )

    try:
        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        raise WidgetSnapshotSyncError(
            "unable to create Widget snapshot "
            f"directory: {error}"
        ) from error
    
    temporary_path = None
    
    try:
        descriptor, temporary_name = (
            tempfile.mkstemp(
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                dir=str(target_path.parent),
            )
        )
        temporary_path = Path(
            temporary_name
        )
    
        with (
            source_path.open("rb") as source_handle,
            os.fdopen(descriptor, "wb") as target_handle,
        ):
            while True:
                chunk = source_handle.read(
                    1024 * 1024
                )
    
                if not chunk:
                    break
    
                target_handle.write(chunk)
    
            target_handle.flush()
            os.fsync(
                target_handle.fileno()
            )
    
        os.replace(
            temporary_path,
            target_path,
        )
        temporary_path = None
    
        _fsync_directory(
            target_path.parent
        )
    
    except OSError as error:
        raise WidgetSnapshotSyncError(
            "unable to synchronize Widget "
            f"snapshot: {error}"
        ) from error
    
    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()
            except OSError:
                pass
    
    return True


def sync_widget_snapshot(
    source=DEFAULT_SNAPSHOT_PATH,
    target=None,
):
    source_path = Path(source).expanduser()

    if not source_path.is_file():
        return False
    
    if target is not None:
        return _sync_to_target(
            source_path,
            Path(target).expanduser(),
        )
    
    widget_synced = False
    host_synced = False
    
    try:
        widget_synced = _sync_to_target(
            source_path,
            DEFAULT_WIDGET_SNAPSHOT_PATH,
        )
    except WidgetSnapshotSyncError:
        pass
    except ValueError:
        pass
    
    try:
        host_synced = _sync_to_target(
            source_path,
            DEFAULT_HOST_SNAPSHOT_PATH,
        )
    except WidgetSnapshotSyncError:
        pass
    except ValueError:
        pass
    
    return widget_synced or host_synced