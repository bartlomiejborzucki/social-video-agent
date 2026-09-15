"""Construction of ffmpeg filter graphs.

Everything that has to be spliced into a ``-vf`` / ``-filter_complex`` string
goes through here, so the escaping rules live in exactly one tested place.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

# --------------------------------------------------------------------------
# Filter-argument escaping
# --------------------------------------------------------------------------


def escape_filter_path(path: str | Path) -> str:
    """Quote and escape a filesystem path for use as an ffmpeg filter argument.

    Returns the value *including* its surrounding single quotes, so callers
    write ``f"subtitles={escape_filter_path(p)}"`` and never add quotes of their
    own.

    ffmpeg applies two parsing passes (filtergraph, then filter option), which
    is why the apostrophe needs the close-escape-reopen dance rather than a
    plain backslash, and why the order below matters: the backslash
    substitution must run first so it does not double-escape the backslashes
    the later substitutions introduce, and the apostrophe substitution must run
    last for the same reason.

    Upstream video-use (``render.py:644``) escapes only ``:`` and ``'`` and
    never ``\\``, in that order. That breaks on every Windows path and on any
    path containing an apostrophe; there is no test for it upstream. The scheme
    below was derived empirically against ffmpeg 7.1 and is covered by
    ``tests/unit/test_filters.py`` for space, apostrophe, comma, bracket,
    colon, semicolon, equals, backslash, non-ASCII, and combinations.
    """
    s = str(path)
    s = s.replace("\\", "\\\\")  # must be first
    s = s.replace(":", "\\:")
    s = s.replace("=", "\\=")
    s = s.replace("'", "'\\\\\\''")  # must be last
    return "'" + s + "'"


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

#: Transfer characteristics that indicate an HDR source.
#: ``smpte2084`` is PQ (HDR10); ``arib-std-b67`` is HLG.
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})

#: HDR -> SDR Rec.709 tone map.
#: Ported verbatim from browser-use/video-use ``helpers/render.py:96-132``
#: (MIT, Copyright (c) 2026 Browser Use). Requires ffmpeg built with
#: ``--enable-libzimg``; call ``ffmpeg.run.has_libzimg()`` before using it.
TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

#: Length of the fade applied at both edges of every cut, in seconds.
#: 30 ms is upstream's value and it is the right one: long enough to kill the
#: discontinuity click, short enough to be inaudible as a fade.
CUT_FADE_S = 0.030


def audio_cut_fades(duration: float, fade: float = CUT_FADE_S) -> str:
    """Short fades at both edges of a segment, to prevent pops at the splice.

    Concept from browser-use/video-use ``helpers/render.py:270-272`` (MIT).
    Modified: upstream hard-codes 0.03 and, for a segment shorter than twice
    the fade, produces overlapping ramps that audibly duck the whole segment.
    Here the fade is clamped so it never exceeds a third of the segment.
    """
    if duration <= 0:
        raise ValueError(f"segment duration must be positive, got {duration}")
    f = min(fade, duration / 3.0)
    out_start = max(0.0, duration - f)
    return f"afade=t=in:st=0:d={f:.4f},afade=t=out:st={out_start:.4f}:d={f:.4f}"


#: Loudness targets. -14 LUFS / -1 dBTP is the streaming and social norm.
#: Values from browser-use/video-use ``helpers/render.py:491-594`` (MIT).
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def scale_pad_to(width: int, height: int, *, pad_colour: str = "black") -> str:
    """Fit the source inside WxH preserving aspect, padding the remainder.

    Uses ``force_original_aspect_ratio=decrease`` then centres with ``pad``.
    ``-2`` style scaling is avoided here because the output must land on an
    exact canvas: every segment in a render has to share one resolution or the
    stream-copy concat produces a file whose later half will not decode.
    Upstream applies this reasoning to frame rate but never to dimensions.
    """
    if width % 2 or height % 2:
        raise ValueError(f"output dimensions must be even for yuv420p, got {width}x{height}")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_colour},"
        f"setsar=1"
    )


def crop_then_scale(crop_w: int, crop_h: int, x: int, y: int, out_w: int, out_h: int) -> str:
    """Crop a window out of the source and scale it to the output canvas."""
    for name, value in (("crop_w", crop_w), ("crop_h", crop_h), ("out_w", out_w), ("out_h", out_h)):
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value}")
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos,setsar=1"


def crop_position_expression(keyframes: list[tuple[float, int]], *, lo: int, hi: int) -> str:
    """Piecewise-linear ffmpeg expression for an animated crop position.

    ``keyframes`` is ``[(time_seconds, position_pixels), ...]``. Between
    keyframes the position is interpolated linearly; outside the range it holds
    the first or last value. The result is clamped to ``[lo, hi]`` so a crop can
    never run off the edge of the frame regardless of what the planner produced.

    A static value is returned when there is nothing to animate, which keeps the
    common case cheap and the filter graph readable.
    """
    if not keyframes:
        return str(max(lo, min(lo, hi)))

    points = sorted(keyframes, key=lambda kf: kf[0])
    if len(points) == 1:
        return str(_clamp_int(points[0][1], lo, hi))

    # Built inside-out: the innermost fallback is the final position, and the
    # pairs are consumed in reverse so the *earliest* interval ends up as the
    # outermost condition. Building it forwards would make a late condition
    # shadow every earlier one.
    expression = str(_clamp_int(points[-1][1], lo, hi))
    for (t0, p0), (t1, p1) in reversed(list(pairwise(points))):
        span = max(t1 - t0, 1e-6)
        a = _clamp_int(p0, lo, hi)
        b = _clamp_int(p1, lo, hi)
        segment = f"{a}+({b}-{a})*(t-{t0:.4f})/{span:.4f}"
        expression = f"if(lt(t,{t1:.4f}),{segment},{expression})"
    first_t, first_p = points[0]
    if first_t > 0:
        expression = f"if(lt(t,{first_t:.4f}),{_clamp_int(first_p, lo, hi)},{expression})"
    return expression


def _clamp_int(value: int, lo: int, hi: int) -> int:
    if hi < lo:
        return lo
    return max(lo, min(int(value), hi))
