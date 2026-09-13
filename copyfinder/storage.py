"""Per-user configuration, atomic reports and bounded diagnostic logs."""

import json
import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 2
APP_DIRECTORY = 'copyfinder'


def xdg_directory(variable, fallback):
    configured = os.environ.get(variable, '')
    return (Path(configured) if configured and Path(configured).is_absolute()
            else Path.home() / fallback) / APP_DIRECTORY


def settings_path():
    return xdg_directory('XDG_CONFIG_HOME', '.config') / 'settings.json'


def state_directory():
    return xdg_directory('XDG_STATE_HOME', '.local/state')


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', errors='surrogateescape', newline='') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_settings(path=None):
    path = Path(path) if path is not None else settings_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Settings must contain a JSON object.')
    return value


def save_settings(settings, path=None):
    atomic_write(path if path is not None else settings_path(), json.dumps(settings, indent=2))


def configure_logging():
    logger = logging.getLogger('copyfinder')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        directory = state_directory()
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / 'copyfinder.log', maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    return logger
