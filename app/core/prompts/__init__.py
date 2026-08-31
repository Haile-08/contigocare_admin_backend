"""Prompt loading, versioned.

Prompts are files rather than string literals so that a change to one is a
reviewable diff, and they are *versioned* so that a run recorded last month can
be attributed to the exact wording that produced it. Without the version stamp,
"the agent got worse" is unattributable — you cannot tell a prompt edit from
model drift, and the improvement loop stops working.

Adding a version means adding ``extraction_v2.md`` and pointing
``ANALYSIS_PROMPT_VERSION`` at ``v2``. The old file stays, so old runs remain
explicable and the eval harness can score both against the same golden set.
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


def load_extraction_prompt(document_text: str, version: str = "v1") -> str:
    """Build the first-pass extraction prompt.

    Args:
        document_text: The redacted policy text.
        version: Prompt version, matching a ``extraction_<version>.md`` file.

    Returns:
        str: The complete prompt.
    """
    template = _read_template(f"extraction_{version}.md")
    return template.format(
        current_date=datetime.now().strftime("%Y-%m-%d"),
        document_text=_neutralize_delimiters(document_text),
    )


def load_critique_prompt(document_text: str, draft_json: str, version: str = "v1") -> str:
    """Build the self-critique prompt.

    Args:
        document_text: The same redacted text the draft was built from.
        draft_json: The first pass's output, serialised.
        version: Prompt version.

    Returns:
        str: The complete prompt.
    """
    template = _read_template(f"critique_{version}.md")
    return template.format(
        document_text=_neutralize_delimiters(document_text),
        draft_json=draft_json,
    )
