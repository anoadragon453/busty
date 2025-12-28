"""Registry for managing BustController instances per guild."""

from typing import TYPE_CHECKING

from busty.bust.models import BustPhase

if TYPE_CHECKING:
    from busty.bust.controller import BustController


class BustRegistry:
    """Manages BustController instances per guild."""

    def __init__(self) -> None:
        self._controllers: dict[int, "BustController"] = {}

    def get(self, guild_id: int) -> "BustController | None":
        """Get controller for guild, auto-removing finished ones.

        Args:
            guild_id: Discord guild ID.

        Returns:
            Active controller, or None if none exists or finished.
        """
        controller = self._controllers.get(guild_id)

        # Auto-cleanup finished controllers
        if controller and controller.phase == BustPhase.FINISHED:
            del self._controllers[guild_id]
            return None

        return controller

    def register(self, guild_id: int, controller: "BustController") -> None:
        """Register a controller for a guild.

        Args:
            guild_id: Discord guild ID.
            controller: BustController to register.
        """
        self._controllers[guild_id] = controller

    def remove(self, guild_id: int) -> None:
        """Explicitly remove controller for guild.

        Args:
            guild_id: Discord guild ID.
        """
        self._controllers.pop(guild_id, None)
