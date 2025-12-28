import copy
import json
import logging
from pathlib import Path
from typing import Any, Iterable, cast

from discord import Interaction

from busty.config.constants import JSON_DATA_TYPE

logger = logging.getLogger(__name__)


class PersistentState:
    """Manages persistent bot state with JSON file backing."""

    def __init__(self, state_file: Path) -> None:
        """Initialize persistent state manager and load from disk.

        Args:
            state_file: Path to the state file.
        """
        self._state: dict[str, Any] = {}
        self._state_file = state_file

        try:
            with open(state_file) as f:
                bot_state_str = f.read()
        except FileNotFoundError:
            # Expected on first run or after setting a new custom bot state filepath.
            bot_state_str = None
        except IOError:
            logger.error(f"Could not read state from {state_file}")
            raise

        if bot_state_str:
            # Load the JSON representation of the bot's state and convert it to a Python dict so
            # it can be easily manipulated.
            self._state = json.loads(bot_state_str)
            logger.info(f"Loaded bot state from {state_file}")
        else:
            logger.info("No existing bot state file found, starting fresh")

    def set_state(self, path: Iterable[str], value: JSON_DATA_TYPE) -> None:
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
        # We don't want to modify the given path directly, so we make a copy here.
        path = list(path)

        # Check if we need to traverse the bot state via the given path.
        if path:
            # Start at the top of the dict
            current_path = self._state

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

            self._state = value

        # Now write the modified `bot_state` back to disk.

        with open(self._state_file, "w") as f:
            # We add indenting (which also adds newlines) into the file to make it easy for a human
            # to look through in case of the need for debugging (the performance cost in minimal).
            bot_state_str = json.dumps(self._state, indent=2)
            f.write(bot_state_str)

    def get_state(self, path: Iterable[str]) -> JSON_DATA_TYPE:
        """Retrieve persistent state at a given path.

        Args:
            path: The path to retrieve the state of.

        Returns:
            The value at the given path. None if the path does not exist, or if None was
            literally stored at this path.
        """
        # If path is empty, just return the entire bot state
        if not path:
            return copy.deepcopy(self._state)

        # We don't want to modify the given path directly, so we make a copy here.
        path = list(path)

        # Start at the top of the dict.
        current_path = self._state

        # Iterate over each item in the path until we reach the second to last item. The last item will
        # be used as the field name in the JSON dict.
        key = path.pop()
        for pathname in path:
            next_path = current_path.get(pathname)

            if next_path is None or not isinstance(next_path, dict):
                # Oops, we hit a dead end.
                return None

            current_path = next_path

        # Return the value under the field at the end of the given path.
        value = current_path.get(key)
        if value is None:
            return None

        # We explicitly return a copy of the value, otherwise any manipulations the calling function
        # does to the value may result in the state dict being changed.
        return cast(JSON_DATA_TYPE, copy.deepcopy(value))

    def delete_state(self, path: Iterable[str]) -> bool:
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
        state_at_path = self.get_state(path)
        if state_at_path is None or not isinstance(state_at_path, dict):
            # The path is invalid, as removing the last item from a path should
            # result in a path that leads to a dict.
            return False

        if field_to_delete not in state_at_path:
            # This field does not exist at this path.
            return False

        del state_at_path[field_to_delete]

        # Store the updated state to disk. We have to do this before calling `delete_state`
        # below otherwise it will call `get_state` again and receive the bot state without
        # any of the modifications above applied.
        self.set_state(path, state_at_path)

        # If deleting this field would result in an empty dict at this path, delete that path as well.
        # So that we don't end up with empty state dicts in our json store.
        if not state_at_path:
            self.delete_state(path)

        return True

    async def save_form_image_url(self, interaction: Interaction, image_url: str) -> bool:
        """
        Safely save a Google form image url to disk.

        If saving the URL fails, the interaction is responded to.

        Args:
            interaction: The Nextcord interaction that triggered the image being saved.
            image_url: The image url to save.

        Returns:
            True if the image url saved correctly, False if not.
        """
        try:
            self.set_state(["guilds", str(interaction.guild_id), "form_image_url"], image_url)
        except Exception as e:
            logger.error(f"Unable to set form image: {e}")

            await interaction.response.send_message(
                f"Failed to upload image ({type(e)}). See the logs for more details.",
                ephemeral=True,
            )
            return False

        return True

    def get_form_image_url(self, interaction: Interaction) -> str | None:
        """
        Retrieve a saved google form image url given an interaction in a guild.

        Args:
            interaction: The interaction that triggered this call.

        Returns:
            The image form URL if it was found, otherwise None.
        """
        result = self.get_state(["guilds", str(interaction.guild_id), "form_image_url"])
        if isinstance(result, str):
            return result
        return None

    def clear_form_image_url(self, interaction: Interaction) -> bool:
        """
        Clear a saved google form image url given an interaction in a guild.

        Args:
            The interaction that triggered this call.

        Returns:
            True if there was an image to delete, False if not.
        """
        return self.delete_state(["guilds", str(interaction.guild_id), "form_image_url"])
