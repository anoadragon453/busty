"""Startup validation for Busty bot."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from busty.config.settings import BustySettings

logger = logging.getLogger(__name__)


def validate_and_setup_directories(settings: "BustySettings") -> list[str]:
    """Validate directories exist and are writable, create if needed.

    Args:
        settings: BustySettings instance containing directory paths.

    Returns:
        List of error messages (empty if all OK).
    """
    errors = []

    # Directories that must be writable
    writable_dirs = [
        (settings.state_dir, "state directory"),
        (settings.cache_dir, "cache directory"),
        (settings.temp_dir, "temp directory"),
        (settings.attachment_cache_dir, "attachment cache"),
    ]

    for dir_path, description in writable_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            # Test writability
            test_file = dir_path / ".write_test"
            test_file.touch()
            test_file.unlink()
        except (OSError, PermissionError) as e:
            errors.append(f"Cannot write to {description} ({dir_path}): {e}")

    # Config directory (may be read-only in production)
    if not settings.config_dir.exists():
        logger.warning(f"Config directory does not exist: {settings.config_dir}")

    # Auth directory validation (optional, only if Google Forms enabled)
    if settings.google_form_folder:
        if not settings.auth_dir.exists():
            errors.append(
                f"Auth directory required for Google Forms but not found: {settings.auth_dir}"
            )
        elif not settings.google_auth_file.parent.exists():
            errors.append(
                f"Google auth file directory does not exist: {settings.google_auth_file.parent}"
            )

    return errors
