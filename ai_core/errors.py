"""User-facing AI errors. Each carries a setup hint the UI can turn into an action."""


class AIUnavailable(RuntimeError):
    """A capability is not available on this PC; never replaced by fake output."""

    def __init__(self, message, setup_hint=None):
        super().__init__(message)
        self.message = message
        self.setup_hint = setup_hint

    def to_dict(self):
        return {'error': self.message, 'setup_hint': self.setup_hint}


class ModelMissing(AIUnavailable):
    """A required model or engine is not installed (and is never auto-downloaded)."""


class ConsentRequired(AIUnavailable):
    """A download needs explicit license acceptance before it can start."""
