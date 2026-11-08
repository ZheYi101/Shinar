"""Context-owned patches for standalone scenarios, independent of pytest."""

from contextlib import ExitStack
from unittest.mock import patch


class Patches(ExitStack):
    def setattr(self, target, name, value=None):
        if isinstance(target, str):
            return self.enter_context(patch(target, name))
        return self.enter_context(patch.object(target, name, value))
