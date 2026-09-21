"""Exception types.

Every failure that a user or an agent has to act on carries the information
needed to act. In particular, an ffmpeg failure carries ffmpeg's own stderr:
upstream video-use captures stderr with ``subprocess.PIPE`` at five call sites
and never reads it, so every render failure surfaces as a bare
``CalledProcessError`` with the diagnostic discarded.
"""

from __future__ import annotations


class SocialVideoError(Exception):
    """Base class for every error this package raises deliberately."""


class ToolNotFoundError(SocialVideoError):
    """A required external binary (ffmpeg, ffprobe) could not be located."""


class FFmpegError(SocialVideoError):
    """An ffmpeg or ffprobe invocation failed.

    Carries the exit status, the full argument vector, and the tail of stderr.
    """

    def __init__(
        self,
        message: str,
        *,
        args_used: list[str],
        returncode: int,
        stderr: str = "",
        stderr_tail_lines: int = 30,
    ) -> None:
        self.args_used = args_used
        self.returncode = returncode
        self.stderr = stderr

        tail = "\n".join(stderr.strip().splitlines()[-stderr_tail_lines:])
        detail = f"{message} (exit {returncode})"
        if tail:
            detail += f"\n\nffmpeg said:\n{tail}"
        detail += "\n\ncommand:\n  " + " ".join(_quote(a) for a in args_used)
        super().__init__(detail)


class ValidationError(SocialVideoError):
    """An artifact on disk did not match its schema.

    Raised in preference to letting malformed agent-authored JSON reach ffmpeg.
    """


class ConfigMigrationError(ValidationError):
    """A project config still carries pre-0.4 values that cannot be converted.

    Raised instead of guessing: every value it reports encodes an editorial
    decision, so the message names each field and what to write instead.
    """


class RemotionLicenseError(ValidationError):
    """Remotion was requested without a usable license declaration.

    Carries the whole instruction: which declarations exist, how to record one
    for the project, and how to opt out of Remotion. The CLI never decides
    eligibility, so the message has to be enough for the user to decide.
    """


class CapabilityError(SocialVideoError):
    """The installed ffmpeg lacks a filter or library this operation needs."""


class ImageGenerationError(SocialVideoError):
    """A cloud image provider refused, failed, or returned something unusable."""


class RemotionError(SocialVideoError):
    """The Remotion compositor failed with a concise actionable diagnostic."""


def _quote(arg: str) -> str:
    """Render one argv element readably for a copy-pasteable error message."""
    if arg and not any(c in arg for c in " \t\n\"'\\$`*?[]()<>|&;#~"):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"
