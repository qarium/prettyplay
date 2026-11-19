"""In-memory models of the step cache: step addressing and a cached unit."""

import hashlib
import re

from pydantic import BaseModel, ConfigDict, model_validator

from ..failures import PrettyplayError
from .text import normalize_step_text

#: Unit Separator: makes the identity concatenation unambiguous.
_IDENTITY_SEPARATOR = "\x1f"

#: One scope segment: at least one ASCII letter, digit, dot, underscore or hyphen.
_SCOPE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


class StepIdentity(BaseModel):
    """The address of a step in the repository cache.

    Attributes:
        cache_key: the key of the test the step belongs to.
        step_type: the kind of the step sentence ({action, assertion}).
        normalized_text: the normalized step sentence.
    """

    model_config = ConfigDict(kw_only=True)

    cache_key: str
    step_type: str
    normalized_text: str

    @property
    def filename(self) -> str:
        """Return the cache filename deterministically derived from the triple.

        Returns:
            The filename — the parts joined with the Unit Separator,
            sha256-hashed, ``.py``-extended; the cache loader parses the
            text and never imports the module by name.
        """
        identity_string = _IDENTITY_SEPARATOR.join((self.cache_key, self.step_type, self.normalized_text))
        digest = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()
        return f"{digest}.py"


def validate_step_scope(scope: str) -> None:
    """Validate a step scope — the one rule of both validation rings.

    Args:
        scope: the candidate scope value.

    Raises:
        PrettyplayError: the value is not 1..N segments of ASCII letters,
            digits, dot, underscore or hyphen joined by single ``/``
            characters — the loud failure names the parameter, the received
            value and the allowed form; a valid value passes verbatim,
            nothing is rewritten.
    """
    segments = scope.split("/")

    if scope == "" or any(not _SCOPE_SEGMENT.fullmatch(segment) for segment in segments) or ".." in segments:
        raise PrettyplayError(
            f"invalid _scope {scope!r} — 1..N segments of ASCII letters, digits, dot, "
            "underscore or hyphen joined by single / characters, keyword-only"
        )


class CachedStep(BaseModel):
    """One unit of the step cache: a working step bound to its identity.

    Every newly built cached step satisfies the addressing invariant:
    ``normalize_step_text(addressing_text) == identity.normalized_text`` —
    a construction-time programming error, never a runtime path.

    Attributes:
        identity: the address of the step.
        addressing_text: the verbatim rendered sentence before NFC and trim;
            the metadata sentence field carries it.
        code: the step code — top-level imports when present, then the fixed
            form ``def step(page) -> None:``; the cache stores and restores
            the whole text verbatim.
        created_at: the date the code was generated (ISO format).
    """

    model_config = ConfigDict(kw_only=True)

    identity: StepIdentity
    addressing_text: str = ""
    code: str
    created_at: str

    @model_validator(mode="after")
    def _check_addressing_invariant(self) -> "CachedStep":
        """Enforce that the addressing text normalizes to the identity's normalized text.

        Raises:
            ValueError: the addressing text and the identity address different
                sentences — a construction-time programming error.
        """
        if normalize_step_text(self.addressing_text) != self.identity.normalized_text:
            raise ValueError("cached step addressing text does not normalize to the identity's normalized text")

        return self
