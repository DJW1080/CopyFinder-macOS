"""Native, unprivileged GIO desktop integration and read-only diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib


FILE_MANAGER_BUS_NAME = "org.freedesktop.FileManager1"
FILE_MANAGER_OBJECT_PATH = "/org/freedesktop/FileManager1"
FILE_MANAGER_INTERFACE = "org.freedesktop.FileManager1"
DBUS_TIMEOUT_MILLISECONDS = 3000
MOUNTINFO_PATH = Path("/proc/self/mountinfo")
NETWORK_FILESYSTEM_TYPES = frozenset({
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs",
    "afs", "coda", "ncpfs", "9p", "ceph", "fuse.ceph", "fuse.rclone",
    "fuse.smbnetfs", "davfs", "davfs2", "fuse.davfs", "glusterfs", "fuse.glusterfs",
})
MOUNT_ESCAPE_PATTERN = re.compile(r"\\([0-7]{3})")


class DesktopIntegrationError(RuntimeError):
    """A requested desktop action could not be completed."""


def trash_file(path: str) -> None:
    """Move one path to native Trash, with no permanent-deletion fallback."""
    try:
        completed = Gio.File.new_for_path(path).trash(None)
    except GLib.Error as error:
        raise DesktopIntegrationError(f"GIO could not move the file to Trash: {error.message}") from error
    if not completed:
        raise DesktopIntegrationError(f"GIO did not confirm that the file was moved to Trash: {path}")


def _reveal_with_file_manager(uri: str) -> None:
    proxy = Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
        FILE_MANAGER_BUS_NAME, FILE_MANAGER_OBJECT_PATH, FILE_MANAGER_INTERFACE, None)
    proxy.call_sync("ShowItems", GLib.Variant("(ass)", ([uri], "")),
                    Gio.DBusCallFlags.NONE, DBUS_TIMEOUT_MILLISECONDS, None)


def reveal_file(path: str) -> None:
    """Select a file in FileManager1, or open its containing directory."""
    file = Gio.File.new_for_path(os.path.abspath(path))
    try:
        _reveal_with_file_manager(file.get_uri())
        return
    except GLib.Error:
        pass
    parent = file.get_parent()
    if parent is None:
        raise DesktopIntegrationError(f"The file has no containing directory: {path}")
    try:
        launched = Gio.AppInfo.launch_default_for_uri(parent.get_uri(), None)
    except GLib.Error as error:
        raise DesktopIntegrationError(f"Could not reveal the file's location: {error.message}") from error
    if not launched:
        raise DesktopIntegrationError(f"No file manager confirmed opening the containing directory: {path}")


def _is_under(path: str, directory: str) -> bool:
    directory = directory.rstrip("/")
    return path == directory or path.startswith(directory + "/")


def _decode_mount_path(value: str) -> str:
    return MOUNT_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 8)), value)


def _gvfs_roots() -> tuple[str, ...]:
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return (str(Path(runtime) / "gvfs"), f"/run/user/{os.getuid()}/gvfs",
            str(Path.home() / ".gvfs"))


def is_network_path(path: str) -> bool:
    """Best-effort remote classification using GVfs and the deepest mount."""
    absolute = os.path.abspath(path)
    resolved = os.path.realpath(absolute)
    if any(_is_under(candidate, root) for candidate in (absolute, resolved) for root in _gvfs_roots()):
        return True
    try:
        mount_lines = MOUNTINFO_PATH.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    except OSError:
        return False
    longest_match = ""
    matched_filesystem = ""
    for line in mount_lines:
        before, separator, after = line.partition(" - ")
        mount_fields, filesystem_fields = before.split(), after.split()
        if not separator or len(mount_fields) < 5 or not filesystem_fields:
            continue
        mount_point = _decode_mount_path(mount_fields[4])
        if _is_under(resolved, mount_point) and len(mount_point) > len(longest_match):
            longest_match, matched_filesystem = mount_point, filesystem_fields[0]
    return matched_filesystem in NETWORK_FILESYSTEM_TYPES


def _xdg_directory(variable: str, fallback: str) -> Path:
    configured = os.environ.get(variable, "")
    return Path(configured) if os.path.isabs(configured) else Path.home() / fallback


def _writable_ancestor(path: Path) -> str:
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    writable = os.access(ancestor, os.W_OK | os.X_OK)
    return f"{path} (existing ancestor {'writable' if writable else 'not writable'}: {ancestor})"


def compatibility_report() -> str:
    """Describe the current Linux runtime without writing or testing Trash."""
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    try:
        distribution = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    except OSError:
        distribution = "Linux (distribution information unavailable)"
    config = _xdg_directory("XDG_CONFIG_HOME", ".config") / "copyfinder"
    state = _xdg_directory("XDG_STATE_HOME", ".local/state") / "copyfinder"
    display = "Wayland" if os.environ.get("WAYLAND_DISPLAY") else (
        "X11" if os.environ.get("DISPLAY") else "No display environment detected")
    gtk_version = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
    return "\n".join((
        "CopyFinder Linux compatibility report",
        f"Operating system: {distribution}; kernel {platform.release()}; {platform.machine()}",
        f"Python: {platform.python_version()}; GTK: {gtk_version}; GIO/GLib: "
        f"{GLib.MAJOR_VERSION}.{GLib.MINOR_VERSION}.{GLib.MICRO_VERSION}",
        f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', 'unspecified')}; session: {display}",
        f"Home readable: {os.access(Path.home(), os.R_OK | os.X_OK)}",
        f"Configuration: {_writable_ancestor(config)}",
        f"State/logs: {_writable_ancestor(state)}",
        f"Mount information readable: {os.access(MOUNTINFO_PATH, os.R_OK)}",
        "Trash: native GIO only; support and permissions are checked for each actual operation.",
        "No permanent deletion, ownership changes, permission changes, or privilege elevation.",
        "These checks are read-only; they do not establish that every filesystem supports Trash.",
    ))
