"""The single visibility point of prettyplay: the ``prettyplay`` logger plus hook fan-out."""

import logging

from .hooks import StepHooks

#: Events written at WARNING; every other event is step/generation/healing lifecycle INFO.
_WARNING_EVENTS = frozenset({"on_cache_skipped"})

#: Attributes Logger.makeRecord forbids overwriting: collision keys get a ``ctx_`` prefix
#: in the log record only — hooks always receive the original payload kwargs.
_LOG_RECORD_RESERVED = frozenset(
    {
        "name",
        "msg",
        "message",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "funcName",
        "lineno",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "process",
        "processName",
        "stack_info",
        "asctime",
        "taskName",
    }
)


class StepReporter:
    """Dispatches every step, generation, healing and cache event to the logger and hooks."""

    def __init__(self, hooks: list[StepHooks]) -> None:
        """Keep the hooks list by reference in the public ``hooks`` attribute.

        Args:
            hooks: callback implementations registered by the integrator; may be empty.
                ``add_hooks`` of the main object appends into this same list.
        """
        self.hooks = hooks
        self._logger = logging.getLogger("prettyplay")

    def emit(self, event: str, payload: dict[str, str | int]) -> None:
        """Dispatch one event to the logger and to every hook, in registration order.

        Args:
            event: the event name — equals a ``StepHooks`` method name exactly.
            payload: the payload fields of the event; values are strings, the
                attempt counter is an int.
        """
        level = logging.WARNING if event in _WARNING_EVENTS else logging.INFO
        extra = {f"ctx_{key}" if key in _LOG_RECORD_RESERVED else key: value for key, value in payload.items()}

        self._logger.log(level, event, extra=extra)

        for hook in self.hooks:
            try:
                getattr(hook, event)(**payload)
            except Exception:
                self._logger.warning("hook call failed", extra={"event": event, "hook": type(hook).__name__})
