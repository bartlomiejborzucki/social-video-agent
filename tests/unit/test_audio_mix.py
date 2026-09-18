"""Music bed and sound effects: licence gate, policy gate, graph shape."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.edl.render import AudioMix, build_audio_graph
from social_video.errors import ValidationError
from social_video.ffmpeg.probe import MediaInfo
from social_video.pipeline import _check_audio_policy
from social_video.schemas.brand import BrandProfile
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, AudioBed, EDLRange, SoundEffect


def _bed(**kwargs) -> AudioBed:
    base = {"path": "music.m4a", "reason": "Podkład pod montaż.", "license_confirmed": True}
    return AudioBed(**{**base, **kwargs})


def _edl(**kwargs) -> EDL:
    return EDL(ranges=[EDLRange(source="talk", start=0.0, end=10.0)], **kwargs)


def _contract(music: str = "none", sfx: str = "none") -> BrandContract:
    return BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="c" * 64,
        project_root="/p",
        brand=BrandProfile(),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        music_policy=music,
        sfx_policy=sfx,
    )


def test_a_bed_without_a_licence_declaration_is_refused() -> None:
    with pytest.raises(PydanticValidationError, match="license_confirmed"):
        AudioBed(path="music.m4a", reason="r")
    with pytest.raises(PydanticValidationError, match="license_confirmed"):
        SoundEffect(path="ping.wav", at=1.0, reason="r")


def test_a_bed_louder_than_the_voice_is_not_a_bed() -> None:
    with pytest.raises(PydanticValidationError, match="less than or equal to 0"):
        _bed(gain_db=3.0)


def test_an_effect_after_the_output_ends_is_refused() -> None:
    with pytest.raises(PydanticValidationError, match="lands after"):
        _edl(sound_effects=[SoundEffect(path="p.wav", at=40.0, reason="r", license_confirmed=True)])


def _ranges(duration: float = 10.0):
    from social_video.edl.render import RenderRange

    info = MediaInfo(
        path=Path("talk.mp4"),
        duration=duration,
        size_bytes=1,
        format_name="mp4",
        video=None,
        audio=(),
    )
    return [
        RenderRange(
            video_input=0,
            audio_input=None,
            video_info=info,
            audio_info=info,
            fill_input=None,
            fill_info=None,
            target_frames=int(duration * 30),
            target_duration=duration,
        )
    ]


def test_without_music_the_audio_graph_is_untouched() -> None:
    graph, label = build_audio_graph(_edl(), _ranges(), AudioMix())
    assert "sidechaincompress" not in graph
    assert label == "[cam]"


def test_a_ducked_bed_sidechains_the_speech_into_the_compressor() -> None:
    edl = _edl(audio_bed=_bed(gain_db=-20.0, duck=True, duck_ratio=6.0))
    graph, label = build_audio_graph(edl, _ranges(), AudioMix(bed_input=2))
    assert "asplit=2[spmain][spkey]" in graph
    assert "[bedp][spkey]sidechaincompress=" in graph
    assert "ratio=6.00" in graph
    assert "volume=-20.00dB" in graph
    # The bed must be mixed in, not replace the voice.
    assert "amix=inputs=2:duration=first" in graph
    assert label == "[amixout]"


def test_an_undocked_bed_skips_the_sidechain_but_still_mixes() -> None:
    edl = _edl(audio_bed=_bed(duck=False))
    graph, _ = build_audio_graph(edl, _ranges(), AudioMix(bed_input=2))
    assert "sidechaincompress" not in graph
    assert "amix=inputs=2" in graph


def test_effects_are_delayed_to_their_stated_moment() -> None:
    edl = _edl(
        sound_effects=[
            SoundEffect(path="p.wav", at=1.5, reason="Akcent.", license_confirmed=True),
            SoundEffect(path="q.wav", at=4.0, reason="Akcent.", license_confirmed=True),
        ]
    )
    graph, _ = build_audio_graph(edl, _ranges(), AudioMix(sfx_inputs=(2, 3)))
    assert "adelay=1500|1500" in graph
    assert "adelay=4000|4000" in graph
    assert "amix=inputs=3:duration=first" in graph


def test_an_unnormalised_mix_gets_a_limiter_because_nothing_else_caps_it() -> None:
    edl = _edl(audio_bed=_bed(), normalize_audio=False)
    graph, _ = build_audio_graph(edl, _ranges(), AudioMix(bed_input=2))
    assert "alimiter=limit=0.891" in graph
    normalised, _ = build_audio_graph(_edl(audio_bed=_bed()), _ranges(), AudioMix(bed_input=2))
    assert "alimiter" not in normalised


def test_the_project_policy_decides_whether_music_may_be_mixed_at_all() -> None:
    with pytest.raises(ValidationError, match="music_policy: none"):
        _check_audio_policy(_edl(audio_bed=_bed()), _contract(music="none"))
    _check_audio_policy(_edl(audio_bed=_bed()), _contract(music="optional"))
    with pytest.raises(ValidationError, match="music_policy: required"):
        _check_audio_policy(_edl(), _contract(music="required"))


def test_the_sfx_policy_is_enforced_the_same_way() -> None:
    effect = SoundEffect(path="p.wav", at=1.0, reason="Akcent.", license_confirmed=True)
    with pytest.raises(ValidationError, match="sfx_policy: none"):
        _check_audio_policy(_edl(sound_effects=[effect]), _contract(sfx="none"))
    _check_audio_policy(_edl(sound_effects=[effect]), _contract(sfx="optional"))
    with pytest.raises(ValidationError, match="places no effects"):
        _check_audio_policy(_edl(), _contract(sfx="required"))
