"""In-memory models of the step cache: step addressing and a cached unit."""

import hashlib

from pydantic import BaseModel, ConfigDict, model_validator

from .text import normalize_step_text

#: Unit Separator: makes the identity concatenation unambiguous.
_IDENTITY_SEPARATOR = "\x1f"


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
