"""The structural element registry: parsing, rendering and guarded capture of the collector records."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from ..driver import PageFacade

logger = logging.getLogger("prettyplay")

#: The marker of an element without a runtime-verified unique selector: the
#: registry still lists the element — it tells the code that a text or
#: role+name locator is the correct anchor for it, not a violation.
_TEXT_ONLY_MARKER = "text only"


class ElementRecord(BaseModel):
    """One interactive element of the page with its runtime-verified selector.

    Attributes:
        tag: the lowercased tag name of the element.
        text: the trimmed visible text of the element (whitespace collapsed,
            bounded by the collector).
        id: the ``id`` attribute of the element; empty when absent.
        testid: the ``data-testid`` attribute of the element; empty when absent.
        name: the ``name`` attribute of the element; empty when absent.
        aria_label: the ``aria-label`` attribute of the element; empty when absent.
        placeholder: the ``placeholder`` attribute of the element; empty when absent.
        classes: the first classes of the element joined by spaces (bounded by
            the collector); empty when absent.
        selector: the first unique selector of the element's candidate ladder
            (data-testid, id, name, aria-label, class chain, parent-id-scoped
            CSS, structural XPath); empty when no candidate proved unique.
        via: the ladder rung the selector came from ({testid, id, name,
            aria-label, class, css, xpath}); empty together with the selector.
    """

    model_config = ConfigDict(kw_only=True, extra="ignore")

    tag: str = ""
    text: str = ""
    id: str = ""
    testid: str = ""
    name: str = ""
    aria_label: str = ""
    placeholder: str = ""
    classes: str = ""
    selector: str = ""
    via: str = ""

    @property
    def descriptor(self) -> str:
        """Return the first non-empty human handle of the record.

        Returns:
            The visible text, else the aria-label, else the placeholder, else
            the name attribute — the ladder the rendered line quotes so the
            step sentence can be matched to the element; empty when the
            element carries none of them.
        """
        for candidate in (self.text, self.aria_label, self.placeholder, self.name):
            if candidate:
                return candidate
        return ""


def parse_element_records(raw: object) -> list[ElementRecord]:
    """Parse the raw collector output into records; malformed entries drop loudly.

    Args:
        raw: the object the in-page collector returned — a list of plain
            dictionaries expected, anything else the page produced.

    Returns:
        The parsed records in collector order; a malformed entry drops with a
        WARNING instead of failing the generation request — the registry is an
        enrichment, a half-empty registry still beats no registry.
    """
    if not isinstance(raw, list):
        logger.warning("structure registry malformed — expected a list of records, got %s", type(raw).__name__)
        return []

    records: list[ElementRecord] = []
    for entry in raw:
        if not isinstance(entry, dict):
            logger.warning("structure registry record malformed — dropped: %r", entry)
            continue
        try:
            records.append(ElementRecord(**{key: value for key, value in entry.items() if isinstance(value, str)}))
        except Exception as failure:  # a malformed record never kills the request
            logger.warning("structure registry record rejected — %s: %r", failure, entry)
    return records


def render_structure_registry(records: list[ElementRecord]) -> str:
    """Render the records as the compact PAGE STRUCTURE block body.

    Args:
        records: the parsed collector records in page order.

    Returns:
        One line per record — ``- button "Sign in" -> #login-submit (testid)``
        with the descriptor quoted and the verified selector with its ladder
        rung; a record without a selector renders the text-only marker instead;
        an empty record list renders an empty string — the request then carries
        no PAGE STRUCTURE block at all.
    """
    lines: list[str] = []
    for record in records:
        descriptor = record.descriptor.replace('"', "'")
        anchor = f"{record.selector} ({record.via})" if record.selector else _TEXT_ONLY_MARKER
        lines.append(f'- {record.tag} "{descriptor}" -> {anchor}')
    return "\n".join(lines)


def capture_structure_registry(page: PageFacade) -> str:
    """Capture and render the structural registry of the live page; a failed read degrades to empty.

    Args:
        page: the live page facade of the test.

    Returns:
        The rendered registry — the PAGE STRUCTURE block body; empty when the
        collector failed on this page: the request then carries no block and
        the generation behaves exactly as before the registry existed.
    """
    try:
        records = page.structure_registry()
    except Exception as failure:  # a dead or weird page never kills the request
        logger.warning("structure registry unavailable", extra={"error": str(failure)})
        return ""

    return render_structure_registry(parse_element_records(records))
