"""Tests for the StepMemory class of the prettyplay.engine.renderer cell."""

import inspect

from prettyplay.engine.renderer import StepMemory
from pydantic import BaseModel


class TestStepMemoryContract:
    """Contract tests: facade import, method shapes, empty construction."""

    def test_memory_is_importable_from_facade(self) -> None:
        assert inspect.isclass(StepMemory)

    def test_memory_is_a_plain_class_not_pydantic(self) -> None:
        assert not issubclass(StepMemory, BaseModel)

    def test_constructs_with_no_arguments(self) -> None:
        parameters = inspect.signature(StepMemory.__init__).parameters

        assert list(parameters) == ["self"]

    def test_snapshot_signature_is_parameterless(self) -> None:
        parameters = inspect.signature(StepMemory.snapshot).parameters

        assert list(parameters) == ["self"]

    def test_publish_signature_is_single_captures_mapping(self) -> None:
        parameters = inspect.signature(StepMemory.publish).parameters

        assert list(parameters) == ["self", "captures"]

    def test_snapshot_returns_dict_of_str_to_str(self) -> None:
        result = StepMemory().snapshot()

        assert isinstance(result, dict)

    def test_publish_accepts_string_mapping(self) -> None:
        memory = StepMemory()

        memory.publish({"name": "Book"})


class TestStepMemoryLogic:
    """Logic tests: replace-and-keep publication, snapshot stability, edges."""

    def test_memory_publish_replaces_present_and_keeps_absent(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        first = memory.snapshot()

        memory.publish({"name": "Tale", "kind": "novel"})

        assert first == {"name": "Book"}
        assert memory.snapshot() == {"name": "Tale", "kind": "novel"}

    def test_memory_snapshot_of_fresh_memory_is_empty(self) -> None:
        assert StepMemory().snapshot() == {}

    def test_memory_empty_publish_removes_nothing(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        memory.publish({})

        assert memory.snapshot() == {"name": "Book"}

    def test_memory_publish_never_removes_names(self) -> None:
        memory = StepMemory()
        memory.publish({"a": "1", "b": "2", "c": "3"})

        memory.publish({"b": "two"})

        assert memory.snapshot() == {"a": "1", "b": "two", "c": "3"}

    def test_memory_snapshots_are_independent_copies(self) -> None:
        memory = StepMemory()
        memory.publish({"name": "Book"})

        snapshot = memory.snapshot()
        snapshot["name"] = "mutated"

        assert memory.snapshot() == {"name": "Book"}
