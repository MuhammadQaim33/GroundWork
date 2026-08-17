# ============================================================================
# errors.py — domain exceptions for the generation pipeline.
#
# The logic layer (services/, llm.py, compile.py) must NOT know about HTTP.
# It raises these exceptions instead; each carries the HTTP status it maps to.
# The web layer translates them in ONE place (main.py's exception handler),
# while non-HTTP consumers — the MCP server, the Radar cron — catch them
# directly. That's the seam that keeps services reusable outside FastAPI.
# ============================================================================


class GenerationError(Exception):
    """Base class for all generation-pipeline errors.

    `status_code` is the HTTP status the web layer should respond with.
    `str(exc)` is the message users/callers see.
    """
    status_code = 502

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else self.__class__.__name__


class TokenBudgetError(GenerationError):
    """The input is too large for the active provider's free-tier token budget."""
    status_code = 400


class CompileError(GenerationError):
    """LaTeX failed to compile (or the model's LaTeX was structurally invalid
    and couldn't be salvaged by the pipeline)."""
    status_code = 502