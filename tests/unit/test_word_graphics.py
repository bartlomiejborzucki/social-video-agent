"""Word graphics: their schemas and limits, their words, their place on the frame."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.motion.anchors import anchor_to_words
from social_video.motion.layout import element_band
from social_video.motion.sfx import sync_sfx
from social_video.qa.motion import check_motion
from social_video.remotion import _element_payload
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan

#: Invented lines: a habit, then what to say instead.
SPOKEN = [("Nie", 1.0, 1.2), ("płacz!", 1.2, 1.7), ("Zamiast", 3.0, 3.4), ("tego", 3.4, 3.6),
          ("powiedz:", 3.6, 4.1), ("widzę,", 4.4, 4.8), ("że", 4.8, 4.9), ("ci", 4.9, 5.0),
          ("smutno.", 5.0, 5.6)]  # fmt: skip


def _track(shift: float = 0.0) -> CaptionTrack:
    words = [CaptionWord(text=w, start=s + shift, end=e + shift) for w, s, e in SPOKEN]
    return CaptionTrack(
        cues=[
            CaptionCue(index=1, start=words[0].start, end=words[-1].end,
                       text=" ".join(w.text for w in words), words=words)
        ]
    )  # fmt: skip


def _strike(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 6.5, "text": "Nie płacz!", "replacement": "Widzę, że ci smutno.",
              "reason": "The habit, crossed out."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.STRIKE, **values)


def test_a_strike_crosses_out_a_short_line_and_replaces_it() -> None:
    strike = _strike()
    assert strike.placement is not None and strike.placement.value == "top"
    assert strike.strike_moments == (pytest.approx(2.2), pytest.approx(2.9))
    with pytest.raises(ValidationError, match="replacement of at most 40"):
        _strike(replacement=None)
    with pytest.raises(ValidationError, match="at most 40"):
        _strike(text="To zdanie jest zdecydowanie za długie na przekreślenie")
    with pytest.raises(ValidationError, match=r"1\.5-10 s"):
        _strike(end=2.0)
    with pytest.raises(ValidationError, match="opening frame"):
        _strike(start=0.0)
    with pytest.raises(ValidationError, match="while it is on screen"):
        _strike(strike_at=5.0, replace_at=4.0)
    with pytest.raises(ValidationError, match="only used by a strike"):
        MotionElement(type="callout", start=1, end=3, text="Pytanie?", replacement="x",
                      reason="r")  # fmt: skip
    with pytest.raises(ValidationError, match="not a callout"):
        MotionElement(type="callout", start=1, end=3, text="Pytanie?", at_word="Nie",
                      reason="r")  # fmt: skip
    _strike(position="center", strike_mark="scissors")
    with pytest.raises(ValidationError, match="accepts position: top, center"):
        _strike(position="above_captions")


def test_the_stroke_and_the_replacement_land_on_their_words() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_strike(start=5.0, end=9.0, at_word="zamiast", replace_at_word="widzę,")],
    )
    anchored, notes = anchor_to_words(plan, _track())

    strike = anchored.elements[0]
    # The word fell outside the strike: it opens STRIKE_LEAD_S before it.
    assert (strike.start, strike.strike_at, strike.replace_at) == pytest.approx((1.8, 3.0, 4.4))
    assert strike.end == pytest.approx(1.8 + 4.0)
    assert notes[:2] == [
        "strike on 'zamiast' crosses out at 3.00s",
        "strike replaced on 'widzę,' at 4.40s",
    ]
    # A word inside the strike keeps its start.
    inside = MotionPlan(rationale="r", elements=[_strike(start=0.5, end=6.0, at_word="zamiast")])
    assert anchor_to_words(inside, _track())[0].elements[0].start == pytest.approx(0.5)
    # A later recompile carries the whole strike with its words.
    moved, _ = anchor_to_words(anchored, _track(shift=0.5))
    again = moved.elements[0]
    assert (again.start, again.strike_at, again.replace_at) == pytest.approx((2.3, 3.5, 4.9))


def test_a_sensitive_reel_takes_no_playful_graphics() -> None:
    with pytest.raises(ValidationError, match="no playful graphics; remove strike"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_strike()])
    calm = MotionElement(type="list", start=1, end=4, items=["Oddech", "Cisza"],
                         item_times=[1.5, 2.5], reason="r")  # fmt: skip
    MotionPlan(rationale="r", sensitive_topic=True, elements=[calm])


def test_a_strike_sits_at_the_top_by_default_and_is_measured_there() -> None:
    top, bottom = element_band(_strike(), height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.25
    middle = element_band(_strike(position="center"), height=1920, margins={})
    assert middle[0] < 0.5 < middle[1]
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    report = check_motion(edl, MotionPlan(rationale="r", elements=[_strike()]), None)
    readable = next(c for c in report.checks if c.name == "strike at 1.00s readable")
    # Both lines count: 10 + 20 characters at 15 per second, plus a glance.
    assert readable.expected == pytest.approx(0.6 + 30 / 15)


def test_the_compositor_and_the_sound_get_the_stroke_moment(tmp_path) -> None:
    strike = _strike(strike_at=2.0)
    payload = _element_payload(strike, MotionPlan(rationale="r"), {})
    assert (payload["strike_at"], payload["replace_at"]) == pytest.approx((2.0, 2.7))
    (tmp_path / "pop.wav").write_bytes(b"RIFF")
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    _updated, added = sync_sfx(edl, MotionPlan(rationale="r", elements=[strike]), tmp_path)
    assert [effect.at for effect in added] == [1.0, 2.0]


def _bubble(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 3.0, "text": "Jeszcze jedna bajka!",
              "reason": "The child's line, as a bubble."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.BUBBLE, **values)


def test_a_bubble_is_something_said_or_written_over_the_head() -> None:
    speech = _bubble(tail="left")
    assert speech.bubble_variant.value == "speech"
    assert speech.placement is not None and speech.placement.value == "top"
    message = _bubble(variant="message", secondary_text="pytanie od obserwatorki")
    payload = _element_payload(message, MotionPlan(rationale="r"), {})
    assert (payload["variant"], payload["tail"], payload["position"]) == ("message", None, "top")
    assert _element_payload(_bubble(), MotionPlan(rationale="r"), {})["tail"] == "speaker"
    with pytest.raises(ValidationError, match="at most 60 characters"):
        _bubble(text="x" * 61)
    with pytest.raises(ValidationError, match="note of at most 40"):
        _bubble(secondary_text="x" * 41)
    with pytest.raises(ValidationError, match="no tail"):
        _bubble(variant="message", tail="left")
    with pytest.raises(ValidationError, match=r"1\.2-6 s"):
        _bubble(end=9.0)
    # Never in the opening frame: the first caption carries the situation there.
    with pytest.raises(ValidationError, match="opening frame"):
        _bubble(start=0.1, end=2.0)
    with pytest.raises(ValidationError, match="accepts position: top"):
        _bubble(position="center")
    with pytest.raises(ValidationError, match="only used by a bubble"):
        _strike(variant="speech")
    with pytest.raises(ValidationError, match="remove bubble"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_bubble()])


def test_a_bubble_pops_in_on_its_word_in_the_top_zone() -> None:
    plan = MotionPlan(rationale="r", elements=[_bubble(at_word="płacz!")])
    anchored, notes = anchor_to_words(plan, _track())
    bubble = anchored.elements[0]
    assert (bubble.start, bubble.end) == pytest.approx((1.2, 3.2))
    assert notes == ["bubble on 'płacz!' placed at 1.20s"]
    top, bottom = element_band(bubble, height=1920, margins={"top": 10})
    assert top == pytest.approx(0.1 + 10 / 1920) and bottom < 0.35


def _process(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 6.0, "text": "Wieczorem",
              "items": ["kolacja", "kąpiel", "bajka", "sen"], "done_text": "gotowe do snu",
              "reason": "The evening routine, stage by stage."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.PROCESS, **values)


def test_a_process_is_two_to_five_short_stages_at_the_top() -> None:
    process = _process()
    assert process.placement is not None and process.placement.value == "top"
    with pytest.raises(ValidationError, match="at most 12 characters"):
        _process(items=["kolacja", "bardzo długa kąpiel"])
    with pytest.raises(ValidationError, match="2 to 5 items"):
        _process(items=["sen"])
    with pytest.raises(ValidationError, match=r"at least 2\.5 s"):
        _process(end=2.0)
    with pytest.raises(ValidationError, match="only used by a process"):
        MotionElement(type="list", start=1, end=4, items=["a", "b"], done_text="ok", reason="r")
    with pytest.raises(ValidationError, match="accepts position: top"):
        _process(position="center")
    with pytest.raises(ValidationError, match="remove process"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_process()])
    top, bottom = element_band(process, height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.3


def test_each_stage_enters_on_its_word() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_process(items=["płacz", "powiedz"], item_at_words=["płacz!", "powiedz:"])],
    )
    anchored, _notes = anchor_to_words(plan, _track())
    assert anchored.elements[0].item_times == pytest.approx([1.2, 3.6])


def test_a_kinetic_word_is_one_short_word_once_a_reel_and_never_calm() -> None:
    from social_video.motion.energy import word_graphic_problems

    word = MotionElement(type="kinetic_word", start=2.0, end=3.5, text="SPOKÓJ",
                         at_word="smutno.", reason="The key word, built.")  # fmt: skip
    with pytest.raises(ValidationError, match="one word of at most 12"):
        MotionElement(type="kinetic_word", start=2, end=3, text="dwa słowa", reason="r")
    with pytest.raises(ValidationError, match="one word of at most 12"):
        MotionElement(type="kinetic_word", start=2, end=3, text="niesamowicieee", reason="r")
    with pytest.raises(ValidationError, match=r"0\.8-2\.5 s"):
        MotionElement(type="kinetic_word", start=2, end=6, text="SPOKÓJ", reason="r")
    with pytest.raises(ValidationError, match="remove kinetic_word"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[word])
    once = MotionPlan(rationale="r", elements=[word])
    later = word.model_copy(update={"start": 4.0, "end": 5.0})
    twice = MotionPlan(rationale="r", elements=[word, later])
    assert word_graphic_problems(once, energy="bold") == []
    assert word_graphic_problems(twice, energy="bold") == [
        "2 kinetic_word(s); motion_energy bold allows 1 per reel"
    ]
    assert word_graphic_problems(once, energy="calm") == [
        "1 kinetic_word(s); motion_energy calm allows 0 per reel"
    ]
    anchored, _ = anchor_to_words(once, _track())
    assert anchored.elements[0].start == pytest.approx(5.0)
    top, bottom = element_band(word, height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.22


def _picture(tmp_path, size=(1080, 1350)):
    from PIL import Image

    path = tmp_path / f"komentarz-{size[0]}x{size[1]}.png"
    Image.new("RGB", size, (240, 240, 240)).save(path)
    return path


def _inset(tmp_path, **fields) -> MotionElement:
    values = {
        "start": 2.0,
        "end": 5.0,
        "image_asset": str(_picture(tmp_path)),
        "rights": "own screenshot, no people",
        "reason": "The comment being answered.",
    }
    values.update(fields)
    return MotionElement(type=MotionElementType.INSET, **values)


def test_an_inset_shows_one_project_picture_with_its_rights(tmp_path) -> None:
    inset = _inset(tmp_path)
    assert inset.size_pct == 70.0 and inset.placement.value == "top"
    with pytest.raises(ValidationError, match="names its rights"):
        _inset(tmp_path, rights=None)
    with pytest.raises(ValidationError, match="child's face is never shown"):
        _inset(tmp_path, child_face_visible=True)
    with pytest.raises(ValidationError, match="one image_asset or one video_asset"):
        _inset(tmp_path, video_asset="klip.mp4")
    with pytest.raises(ValidationError, match="trim an inset's video_asset"):
        _inset(tmp_path, source_start=1.0)
    with pytest.raises(ValidationError, match="after its source_start"):
        _inset(tmp_path, image_asset=None, video_asset="klip.mp4", source_start=3, source_end=2)
    with pytest.raises(ValidationError, match="30-90 %"):
        _inset(tmp_path, size_pct=20)
    with pytest.raises(ValidationError, match="only used by an inset"):
        _strike(rights="mine")
    with pytest.raises(ValidationError, match="at most 30 %"):
        MotionElement(type="sticker", start=1, end=2, emoji="x", size_pct=40, reason="r")
    with pytest.raises(ValidationError, match="remove inset"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[inset])


def test_the_card_follows_the_picture_and_never_takes_the_frame(tmp_path) -> None:
    from social_video.motion.inset import inset_aspect, inset_box

    inset = _inset(tmp_path)
    assert inset_aspect(inset) == pytest.approx(0.8)
    wide = inset_box(inset, 16 / 9, margins={"top": 10})
    assert (wide[0], wide[2]) == pytest.approx((0.15, 0.85))
    assert wide[1] == pytest.approx(0.1 + 10 / 1920) and wide[3] - wide[1] < 0.3
    # A tall picture is capped and narrowed rather than covering the speaker.
    left, top, right, bottom = inset_box(inset, 0.8, margins={"top": 10})
    assert bottom - top == pytest.approx(0.42)
    assert right - left < 0.7 and (left + right) / 2 == pytest.approx(0.5)
    payload = _element_payload(_inset(tmp_path, image_asset=str(_picture(tmp_path, (1600, 900)))),
                               MotionPlan(rationale="r"), {}, margins={"top": 10})  # fmt: skip
    assert payload["box"]["width"] == pytest.approx(0.7) and "rights" not in payload


def test_motion_qa_warns_when_a_card_hides_a_talking_mouth_too_long(tmp_path) -> None:
    from social_video.schemas.brand import BrandProfile, CaptionStyle
    from social_video.schemas.config import BrandContract

    contract = BrandContract(
        project_config_path="c.yaml", project_config_sha256="c" * 64, project_root="/p",
        brand=BrandProfile(captions=CaptionStyle(margin_pct=22)), output_width=1080,
        output_height=1920, output_fps="30/1", safe_margins={"top": 10},
    )  # fmt: skip
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    words = [CaptionWord(text=f"s{n}", start=n * 0.5, end=n * 0.5 + 0.45) for n in range(16)]
    track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=8, text="mowa", words=words)])

    def low_face(_t):
        return [(0.3, 0.45, 0.7, 0.7)]  # the mouth well under a top card

    def high_face(_t):
        return [(0.3, 0.1, 0.7, 0.35)]  # a face high in the frame, mouth under the card

    for faces, passed in ((low_face, True), (high_face, False)):
        plan = MotionPlan(rationale="r", elements=[_inset(tmp_path, image_asset=str(
            _picture(tmp_path, (1600, 900))))])  # fmt: skip
        report = check_motion(edl, plan, contract, captions=track, faces=faces)
        check = next(c for c in report.checks if c.name == "inset at 2.00s off a talking mouth")
        assert check.passed is passed
    assert next(c for c in report.checks if c.name == "inset at 2.00s clear of captions").passed
