"""A post description template: the order of a reel's caption copy, not its words.

The description is editorial: the code never writes it. What it can do is lay
out the parts in the order that works for a short (the hook, two to four
sentences, a share call to action, the author's credibility line, a source)
and fill only what already exists: the hook title from the motion plan, the
first spoken sentence from the captions, and the call to action and signature
from the project config. Everything else is a ``[[placeholder]]`` for a person
to write, and `deliver --publish` refuses copy that still holds one.
"""

from __future__ import annotations

import re
from pathlib import Path

from social_video.schemas.base import load_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.motion import MotionElementType, MotionPlan
from social_video.workspace.layout import Workspace

#: What a placeholder looks like; copy that still holds one is not ready.
PLACEHOLDER = re.compile(r"\[\[[^\[\]]{1,120}\]\]")

_LABELS = {
    "pl": {
        "title": "tytuł: pytanie, polecenie, liczba albo wybór",
        "body": "2-4 zdania: co widz z tego ma, konkretnie",
        "cta": "prośba o wysłanie: Wyślij tę rolkę komuś, kto…",
        "signature": "podpis wiarygodności: kim jesteś w tym temacie",
        "source": "źródło, jeśli jest; inaczej usuń ten wiersz",
    },
    "en": {
        "title": "title: a question, an instruction, a number or a choice",
        "body": "2-4 sentences: what the viewer gets from it, concretely",
        "cta": "share ask: Send this to someone who…",
        "signature": "credibility line: who you are on this subject",
        "source": "source, if any; otherwise delete this line",
    },
}


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text or "")


def description_template(workspace: Workspace, *, language: str | None = None) -> str:
    """The template as Markdown, filled only from the plan, captions and config."""
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    hook, spoken_language = _spoken_hook(workspace)
    code = (language or spoken_language or "pl").split("-")[0].casefold()
    labels = _LABELS.get(code, _LABELS["en"])
    title = None
    if workspace.motion_plan.is_file():
        plan = load_artifact(MotionPlan, workspace.motion_plan)
        title = next(
            (e.text for e in plan.elements if e.type is MotionElementType.HOOK_TITLE), None
        )

    def slot(value: str | None, label: str) -> str:
        return value.strip() if value and value.strip() else f"[[{label}]]"

    lines = [
        f"# {slot(title, labels['title'])}",
        "",
        slot(title or hook, labels["title"]),
        "",
        f"[[{labels['body']}]]",
        "",
        slot(contract.share_cta if contract else None, labels["cta"]),
        "",
        slot(contract.author_signature if contract else None, labels["signature"]),
        "",
        f"[[{labels['source']}]]",
        "",
    ]
    if hook:
        lines += [f"<!-- spoken_hook: {hook} -->", ""]
    return "\n".join(lines)


def write_template(workspace: Workspace, *, language: str | None = None) -> Path:
    """Write ``publish.template.md``; never over one a person may have filled in."""
    from social_video.errors import ValidationError

    target = workspace.root / "publish.template.md"
    if target.exists():
        raise ValidationError(
            f"{target} already exists and may hold written copy; move or delete it to "
            "start a new template"
        )
    target.write_text(description_template(workspace, language=language), encoding="utf-8")
    return target


def _spoken_hook(workspace: Workspace) -> tuple[str | None, str | None]:
    """The first caption, as said, and the captions' language. Quoted, never written."""
    from social_video.schemas.captions import CaptionTrack
    from social_video.schemas.edl import EDL

    if not workspace.edl.is_file():
        return None, None
    edl = load_artifact(EDL, workspace.edl)
    if not edl.captions:
        return None, None
    track_path = Path(edl.captions).with_suffix(".json")
    if not track_path.is_file():
        return None, None
    track = load_artifact(CaptionTrack, track_path)
    return (track.cues[0].text if track.cues else None), track.language
