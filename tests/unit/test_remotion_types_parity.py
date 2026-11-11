"""The compositor's TypeScript types say what the Python schemas send.

`remotion/types.ts` is written by hand next to `schemas/motion.py`. Nothing
generated one from the other, so a new element type, a new enum value or a new
field could reach the compositor undeclared and be ignored there without a
word. These tests read the TypeScript as text and hold the two together.
"""

from __future__ import annotations

import inspect
import re
import types as pytypes
from enum import Enum
from pathlib import Path
from typing import Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from social_video import remotion
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.config import ProjectVideoConfig
from social_video.schemas.motion import Effect, MotionElement, PunchIn, Shake, Transition

TYPES = Path(__file__).resolve().parents[2] / "remotion" / "types.ts"

#: Sent because the element is dumped whole, read only on the Python side: they
#: place the element in time or pick an asset, and the compositor gets the
#: resolved result (`item_times`, `strike_at`, `image_source`, ...).
PYTHON_ONLY = {
    "animated_emoji",
    "at_source",
    "at_word",
    "child_face_visible",
    "emphasis_words",
    "from_end",
    "item_at_words",
    "occurrence",
    "prop",
    "replace_at_word",
    "replace_occurrence",
    "series",
    "until_source",
}


def _block(name: str) -> str:
    """The body of ``export type <name> = {...};`` with nested braces kept."""
    text = TYPES.read_text(encoding="utf-8")
    start = text.index(f"export type {name} = {{")
    depth = 0
    for index in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[text.index("{", start) + 1 : index]
    raise AssertionError(f"type {name} is not closed")


def _statements(name: str) -> dict[str, str]:
    """Top-level ``field: type`` statements of a type, comments removed."""
    body = re.sub(r"/\*.*?\*/", "", _block(name), flags=re.DOTALL)
    statements: dict[str, str] = {}
    depth = 0
    current = ""
    for char in body:
        depth += {"{": 1, "}": -1}.get(char, 0)
        if char == ";" and depth == 0:
            field, _, declared = current.strip().partition(":")
            statements[field.strip().rstrip("?")] = declared.strip()
            current = ""
        else:
            current += char
    return statements


def _literals(declared: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", declared))


def _alias(name: str) -> set[str]:
    text = TYPES.read_text(encoding="utf-8")
    match = re.search(rf"export type {name} = ([^;{{]+);", text)
    assert match, name
    return _literals(match.group(1))


def _python_values(model: type[BaseModel], field: str) -> set[str]:
    """The strings a schema field can hold: an enum's values or a Literal's."""

    def values(annotation) -> set[str]:
        if inspect.isclass(annotation) and issubclass(annotation, Enum):
            return {str(member.value) for member in annotation}
        if get_origin(annotation) is Literal:
            return {str(value) for value in get_args(annotation)}
        if get_origin(annotation) in (Union, pytypes.UnionType):
            found: set[str] = set()
            for part in get_args(annotation):
                found |= values(part)
            return found
        return set()

    return values(model.model_fields[field].annotation)


def _sent(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields) - {"schema_version"}


def test_every_string_union_of_an_element_matches_its_schema_enum() -> None:
    checked = []
    for field, declared in _statements("MotionElement").items():
        expected = _literals(declared)
        if not expected or field not in MotionElement.model_fields:
            continue
        actual = _python_values(MotionElement, field)
        if not actual:
            continue
        assert expected == actual, f"MotionElement.{field}: types.ts {expected} != schema {actual}"
        checked.append(field)

    # Guards the test itself: a parser that finds nothing would pass anything.
    assert {
        "type",
        "position",
        "layout",
        "animation",
        "strike_mark",
        "variant",
        "tail",
        "title_style",
        "entry",
        "cut_style",
        "prop_style",
    } <= set(checked)
    assert len(_literals(_statements("MotionElement")["type"])) >= 28


@pytest.mark.parametrize(
    ("ts_type", "ts_field", "model", "field"),
    [
        ("PictureEffect", "type", Effect, "type"),
        ("Transition", "style", Transition, "style"),
        ("CaptionStyle", "background_style", CaptionStyle, "background_style"),
        ("CaptionStyle", "position", CaptionStyle, "position"),
        ("CaptionStyle", "mode", CaptionStyle, "mode"),
        ("SocialVideoProps", "logoUsage", ProjectVideoConfig, "logo_usage"),
        ("SocialVideoProps", "labelStyle", ProjectVideoConfig, "label_style"),
    ],
)
def test_the_other_string_unions_match_their_schema(ts_type, ts_field, model, field) -> None:
    expected = _literals(_statements(ts_type)[ts_field])
    actual = _python_values(model, field)

    assert expected and expected == actual, f"{ts_type}.{ts_field}: {expected} != {actual}"


def test_the_emphasis_mark_alias_matches_the_caption_schema() -> None:
    assert _alias("EmphasisMark") == _python_values(CaptionStyle, "emphasis_mark")


def test_every_element_field_sent_is_declared_or_known_to_stay_in_python() -> None:
    declared = set(_statements("MotionElement"))
    excluded = {"image_asset", "video_asset", "rights"}  # `_element_payload` drops these
    sent = _sent(MotionElement) - excluded

    undeclared = sent - declared - PYTHON_ONLY
    assert not undeclared, (
        f"sent to the compositor but not in remotion/types.ts: {sorted(undeclared)}. "
        "Declare it there, or add it to PYTHON_ONLY if the compositor never reads it."
    )
    assert not (PYTHON_ONLY - sent), "PYTHON_ONLY names a field the schema no longer has"
    assert not (PYTHON_ONLY & declared), "PYTHON_ONLY names a field types.ts declares"


def test_every_element_field_the_compositor_declares_is_sent() -> None:
    declared = set(_statements("MotionElement"))
    source = inspect.getsource(remotion._element_payload) + inspect.getsource(
        remotion.title_payload
    )
    computed = set(re.findall(r'payload\["(\w+)"\]', source)) | set(
        re.findall(r'^\s+"(\w+)": ', inspect.getsource(remotion.title_payload), re.MULTILINE)
    )

    never_sent = declared - _sent(MotionElement) - computed
    assert not never_sent, f"declared in types.ts and never sent: {sorted(never_sent)}"


@pytest.mark.parametrize(
    ("ts_type", "model"),
    [("Transition", Transition), ("PunchIn", PunchIn), ("PictureEffect", Effect)],
)
def test_timeline_items_carry_exactly_the_declared_fields(ts_type, model) -> None:
    # A word anchor is resolved to `start` and `end` before the compositor runs.
    assert set(_statements(ts_type)) == _sent(model) - {"at_word", "occurrence", "at_source"}


def test_a_shake_carries_exactly_the_declared_fields() -> None:
    text = TYPES.read_text(encoding="utf-8")
    match = re.search(r"export type Shake = \{([^}]+)\};", text)
    assert match
    declared = {part.split(":")[0].strip() for part in match.group(1).split(";") if part.strip()}

    assert declared <= _sent(Shake)


def test_every_caption_style_field_the_compositor_declares_exists() -> None:
    assert set(_statements("CaptionStyle")) <= _sent(CaptionStyle)
