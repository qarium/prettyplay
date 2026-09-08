"""In-memory models of the step cache: step addressing and a cached unit.

``StepIdentity`` is the address of a step: the triple (cache key, step type,
normalized sentence) plus the filename derived from it. ``CachedStep`` is one
unit of the cache in memory: the identity, the generated code, and the date
of its creation.
"""

import hashlib

from pydantic import BaseModel, ConfigDict

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

        The three parts are joined with the Unit Separator (so no pair of
        values can collide with another pair), hashed with sha256, and given
        the ``.py`` extension. The name does not have to be a Python
        identifier: the cache loader parses the file text and never imports
        the module by name.
        """
        identity_string = _IDENTITY_SEPARATOR.join((self.cache_key, self.step_type, self.normalized_text))
        digest = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()
        return f"{digest}.py"


class CachedStep(BaseModel):
    """One unit of the step cache: a working step bound to its identity.

    Attributes:
        identity: the address of the step.
        code: the step code of the fixed form ``def step(page) -> None:``.
        created_at: the date the code was generated (ISO format).
    """

    model_config = ConfigDict(kw_only=True)

    identity: StepIdentity
    code: str
    created_at: str
