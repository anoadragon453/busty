import copy
import json
from typing import Iterable

from config import JSON_DATA_TYPE, bot_state_file

# Global, persistent state of the bot. Not to be accessed directly. Instead, use the
# getter and setter methods below.
_bot_state = {}


def load_state_from_disk() -> None:
    """Read the bot state from disk and store it in memory."""
    global _bot_state

    bot_state_str = None
    try:
        with open(bot_state_file) as f:
            bot_state_str = f.read()
    except (FileNotFoundError, IOError):
        print(f"Could not read state from {bot_state_file}. Continuing...")

    if bot_state_str:
        # Load the JSON representation of the bot's state and convert it to a Python dict so
        # it can be easily manipulated.
        _bot_state = json.loads(bot_state_str)


def set_state(path: Iterable[str], value: JSON_DATA_TYPE) -> None:
    """Modifies the bot's state in memory, then dumps the modified state to disk.

    This function should not be made async! We do not want to yield from it before we update
    the bot's state on disk. Otherwise, this data model is thread-safe as long as there are
    never >1 simultaneous writes to disk, which python will not let happen without
    multi-processing.

    Args:
        path: The path to store the state under. For example, if storing the settings for a
            particular channel in a guild, you might set `path` to
            ["channel_settings", <guild_id>, <channel_id>, <setting_id>].
        value: The value to store. Only data types that can be serialised to JSON may be
            used, as the state is backed by a JSON store.
    """
    global _bot_state

    # We don't want to modify the given path directly, so we make a copy here.
    path = list(path)

    # Check if we need to traverse the bot state via the given path.
    if path:
        # Start at the top of the dict
        current_path = _bot_state

        # Iterate down the provided path until we reach the second from the last entry in the path.
        # We create a new dictionary and enter it if we hit a dead end. We'll use the final entry in
        # `path` as the field to store `value` under.
        #
        # Therefore, a `path` list of ["settings", "guild_id_123", "submission_channel"] and a `value`
        # of "channel_id_456" would yield a bot_state dictionary of:
        #
        # {"settings": {"guild_123": {"submission_channel": "channel_id_456"}}}
        key = path.pop()
        for pathname in path:
            current_path = current_path.setdefault(pathname, {})

        # `current_path` is now set to the dictionary where we're like to place our `key` and our `value`.
        # As `current_path` is just a reference to a dictionary inside `bot_state`, this modifies
        # `bot_state` as well.
        current_path[key] = value
    else:
        # If no path was provided, just override all bot state with the given value.
        # The given value must be a dict.
        if not isinstance(value, dict):
            raise Exception(
                "Attempted to override entire bot state with a non-dict type"
            )

        _bot_state = value

    # Now write the modified `bot_state` back to disk.
    with open(bot_state_file, "w") as f:
        # We add indenting (which also adds newlines) into the file to make it easy for a human
        # to look through in case of the need for debugging (the performance cost in minimal).
        bot_state_str = json.dumps(_bot_state, indent=2)
        f.write(bot_state_str)


def get_state(path: Iterable[str]) -> JSON_DATA_TYPE:
    """Retrieve persistent state at a given path.

    Args:
        path: The path to retrieve the state of.

    Returns:
        The value at the given path. None if the path does not exist, or if None was
        literally stored at this path.
    """
    # If path is empty, just return the entire bot state
    if not path:
        return copy.deepcopy(_bot_state)

    # We don't want to modify the given path directly, so we make a copy here.
    path = list(path)

    # Start at the top of the dict.
    current_path = _bot_state

    # Iterate over each item in the path until we reach the second to last item. The last item will
    # be used as the field name in the JSON dict.
    key = path.pop()
    for pathname in path:
        current_path = current_path.get(pathname)

        if current_path is None:
            # Oops, we hit a dead end.
            return None

    # Return the value under the field at the end of the given path.
    value = current_path.get(key)
    if value is None:
        return None

    # We explicitly return a copy of the value, otherwise any manipulations the calling function
    # does to the value may result in the state dict being changed.
    return copy.deepcopy(value)


def delete_state(path: Iterable[str]) -> bool:
    """
    Deletes the state at the given path. Removes all saved state under the given path
    This function writes to disk.

    Args:
        path: The path to delete the state for.

    Returns:
        True if the path was deleted, False if the path did not exist.
    """
    if not path:
        # We cannot delete without a path. Deleting all state this way is not supported.
        return False

    # We don't want to modify the given path directly, so we make a copy here.
    path = list(path)

    # Get the state at this path
    field_to_delete = path.pop()

    # this should be a dict as we're one level up
    state_at_path = get_state(path)
    if not isinstance(state_at_path, dict):
        # The path is invalid, as removing the last item from a path should
        # result in a path that leads to a dict.
        return False

    if state_at_path is None:
        # This path does not exist
        return False

    if field_to_delete not in state_at_path:
        # This field does not exist at this path.
        return False

    del state_at_path[field_to_delete]

    # Store the updated state to disk. We have to do this before calling `delete_state`
    # below otherwise it will call `get_state` again and receive the bot state without
    # any of the modifications above applied.
    set_state(path, state_at_path)

    # If deleting this field would result in an empty dict at this path, delete that path as well.
    # So that we don't end up with empty state dicts in our json store.
    if not state_at_path:
        delete_state(path)

    return True
