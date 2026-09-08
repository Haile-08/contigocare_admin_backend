"""Prompt loading, versioned.

Prompts are files rather than string literals so that a change to one is a
reviewable diff, and they are *versioned* so that a run recorded last month can
be attributed to the exact wording that produced it. Without the version stamp,
"the agent got worse" is unattributable — you cannot tell a prompt edit from
model drift, and the improvement loop stops working.

``v1`` is the current wording and the only version on disk: the seven-category
extraction a broker reads a policy in. Adding a version means adding
``extraction_v2.md`` and pointing ``ANALYSIS_PROMPT_VERSION`` at ``v2``. The
previous file stays while it is still *runnable*, so old runs remain explicable
and the eval harness can score both against the same golden set.

A version stops being runnable when the schema moves out from under it. The
output contract is not written in the prompt file — it is generated from
:class:`AnalisisGMM` and appended at call time — so a prompt that names sections
the schema no longer has is not "an older answer", it is prose describing one
contract paired with a machine-readable demand for another. The model resolves
that quietly and returns something plausible and wrong. When a schema change
retires a version this way, delete the file with the change: a stored run's
``prompt_version`` is then a label with no file behind it, which is a smaller
loss than a version somebody can still select and get a wrong analysis from.

Renumbering an existing version is the one edit to avoid. The label is stamped
onto every stored run, so moving the current wording to a number that already
meant something else makes two different prompts indistinguishable in the
table — and the improvement loop reads that column to attribute a regression.
"""

import os
import re
from datetime import datetime
from functools import lru_cache

_PROMPTS_DIR = os.path.dirname(__file__)

# The document is delimited by <documento_poliza> tags so the model can tell
# instructions from content. A document that itself contains the closing tag
# would end the block early and put the rest of its text where instructions
# live — which is the one prompt-injection primitive a delimiter is supposed to
# remove. Neutralising the sequence costs nothing and is invisible in the
# analysis, since no real policy contains it.
_DELIMITER_BREAKOUT = re.compile(r"</?\s*documento_poliza\s*>", re.IGNORECASE)

# Matches the extraction half of a version pair, which is what names a version.
_VERSION_FILE = re.compile(r"^extraction_(v\d+)\.md$")


def available_versions() -> list[str]:
    """Every prompt version that is actually runnable, oldest first.

    A version counts only when *both* halves are on disk. The critique pass runs
    only when verify finds something wrong, so a half-shipped version survives a
    smoke test on a clean document and fails hours later on the first policy that
    needs repairing — long after whoever deployed it has stopped watching.

    Returns:
        list[str]: Runnable version labels, e.g. ``["v1"]``.
    """
    names = set(os.listdir(_PROMPTS_DIR))
    versions = [
        match.group(1)
        for name in names
        if (match := _VERSION_FILE.match(name)) and f"critique_{match.group(1)}.md" in names
    ]
    return sorted(versions, key=lambda version: int(version[1:]))


def assert_version_available(version: str) -> None:
    """Refuse a prompt version that is not on disk.

    Called at startup so a bad ``ANALYSIS_PROMPT_VERSION`` fails the deploy
    rather than the request. The alternative is what it replaces: the service
    boots clean, serves auth and extraction normally, and raises
    ``FileNotFoundError`` inside the agent only once an operator has uploaded a
    policy and approved its redactions — the most expensive possible moment to
    discover a one-word config error, and a bare 500 when it happens.

    Drift between the credential and the repository is the live risk here rather
    than typos: production settings arrive as an encrypted systemd credential,
    so a version that no longer exists is invisible in a diff and shows up only
    as a refusal to boot.

    Args:
        version: The configured version label.

    Raises:
        RuntimeError: If no such version is fully present.
    """
    runnable = available_versions()
    if version in runnable:
        return

    raise RuntimeError(
        f"ANALYSIS_PROMPT_VERSION is {version!r}, which is not on disk. "
        f"Runnable versions: {', '.join(runnable) or 'none'}. "
        "In production this setting comes from the encrypted systemd credential, not "
        "from a file in the repository — check there first, or unset it to take the default."
    )


def _neutralize_delimiters(text: str) -> str:
    """Strip sequences that would close the document block early.

    Args:
        text: The redacted document text.

    Returns:
        str: The text with delimiter-like sequences defanged.
    """
    return _DELIMITER_BREAKOUT.sub("[etiqueta removida]", text)


@lru_cache(maxsize=16)
def _read_template(name: str) -> str:
    """Read and cache a prompt file.

    Args:
        name: Filename inside the prompts directory.

    Returns:
        str: File contents.

    Raises:
        FileNotFoundError: If the named prompt version does not exist. Failing
            at startup is right — a missing prompt must not degrade into an
            empty one at request time.
    """
    path = os.path.join(_PROMPTS_DIR, name)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_extraction_prompt(document_text: str, version: str) -> str:
    """Build the first-pass extraction prompt.

    Args:
        document_text: The redacted policy text.
        version: Prompt version, matching a ``extraction_<version>.md`` file.
            Required rather than defaulted: a default is a version number
            written down in a second place, and the moment it falls behind
            ``ANALYSIS_PROMPT_VERSION`` it silently pairs old wording with the
            current schema — which produces a plausible, wrong analysis rather
            than an error.

    Returns:
        str: The complete prompt.
    """
    template = _read_template(f"extraction_{version}.md")
    return template.format(
        current_date=datetime.now().strftime("%Y-%m-%d"),
        document_text=_neutralize_delimiters(document_text),
    )


def load_critique_prompt(document_text: str, draft_json: str, version: str) -> str:
    """Build the self-critique prompt.

    Args:
        document_text: The same redacted text the draft was built from.
        draft_json: The first pass's output, serialised.
        version: Prompt version. Required, for the reason in
            :func:`load_extraction_prompt`.

    Returns:
        str: The complete prompt.
    """
    template = _read_template(f"critique_{version}.md")
    return template.format(
        document_text=_neutralize_delimiters(document_text),
        draft_json=draft_json,
    )
