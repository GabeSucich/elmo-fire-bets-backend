import logging

from .correction_analysis.client import get_client

logger = logging.getLogger(__name__)

# Deliberately small and non-reasoning: this runs inside the submit request, where the
# person is waiting, and titling one sentence needs nothing more. Measured at roughly
# 1.5-2.5s, which is why the timeout below is a real cap rather than a safety net.
TITLE_MODEL = "gpt-4o-mini"

# A title is a handful of words; letting it generate more only costs latency.
TITLE_MAX_OUTPUT_TOKENS = 32

MAX_TITLE_LENGTH = 80

# A backstop, not a target. The model usually answers in about a second and is allowed to
# take longer; this only stops a submission hanging on a request that will never return.
# The client's own default is ten minutes, which is no use to someone waiting on a button.
TITLE_TIMEOUT_SECONDS = 20.0

TITLE_PROMPT = f"""\
Name the feature described in a piece of product feedback about a sports betting app.

Write a noun phrase naming the thing itself, not the work of building it. Titles sit in a
list where every entry is a request, so words like add, build, support or allow say nothing
and crowd out the words that do.

Rules:
- A noun phrase. Never start with a verb.
- Three to six words. At most {MAX_TITLE_LENGTH} characters.
- Use the person's own terms for anything specific to the app.
- No quotes, no trailing full stop, no prefix like "Feedback:".
- Plain sentence case.

Examples:
- "Add a weekly recap feature to track individual betting performance"
  -> Weekly recap of pick performance
- "It would be great if the slip reader could handle DraftKings screenshots too"
  -> DraftKings screenshot support
- "I want to be able to see how someone did on all their Josh Allen picks"
  -> Per-player pick history

Reply with the title and nothing else."""

# The prompt asks for a noun phrase and mostly gets one, but the imperative is the shape
# every feature request is written in and it leaks back through. Stripped here rather than
# by asking the model again, which would cost a second round trip on a submit.
LEADING_VERBS = (
    "add", "allow", "build", "create", "enable", "implement",
    "introduce", "let", "make", "provide", "show", "support",
)


def fallback_title(comment: str) -> str:
    """The first sentence, trimmed to length on a word boundary.

    Used whenever the model is slow, unavailable or unhelpful. A blunt title beats a
    failed submission, and the author can edit it afterwards.
    """
    first = comment.strip().split("\n")[0].split(". ")[0].strip()
    if len(first) <= MAX_TITLE_LENGTH:
        return first or comment.strip()[:MAX_TITLE_LENGTH]

    # The ellipsis counts: 80 is the column's limit, not a target to overshoot.
    budget = MAX_TITLE_LENGTH - 3
    clipped = first[:budget]
    spaced = clipped.rsplit(" ", 1)[0]
    return (spaced if len(spaced) > budget // 2 else clipped).rstrip(" ,;:-") + "..."


def drop_leading_verb(title: str) -> str:
    """Turns `Add weekly recaps` into `Weekly recaps`.

    Only fires on the whole first word, so a title that genuinely opens on one of these as
    part of a compound — "Add-on markets" — is left alone. If nothing survives the cut the
    title is kept as it was.
    """
    head, _, rest = title.partition(" ")
    if head.lower() not in LEADING_VERBS or not rest.strip():
        return title
    trimmed = rest.strip()
    # "Allow a gambler to..." reads no better than the verb did.
    for article in ("a ", "an ", "the "):
        if trimmed.lower().startswith(article):
            trimmed = trimmed[len(article):]
            break
    return trimmed[:1].upper() + trimmed[1:] if trimmed else title


def clean_title(raw: str, comment: str) -> str:
    title = drop_leading_verb(raw.strip().strip('"').strip("'").rstrip(".").strip())
    if not title:
        return fallback_title(comment)
    if len(title) > MAX_TITLE_LENGTH:
        # Trust the length rule over the model, which does occasionally run long.
        return fallback_title(title)
    return title


async def generate_title(comment: str) -> str:
    """A title for a new piece of feedback.

    Never raises: submitting feedback is the user's action, and it should not fail because
    a model was slow or a key was missing.
    """
    try:
        response = await get_client().responses.create(
            model=TITLE_MODEL,
            max_output_tokens=TITLE_MAX_OUTPUT_TOKENS,
            timeout=TITLE_TIMEOUT_SECONDS,
            input=[
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": comment},
            ],
        )
        return clean_title(response.output_text or "", comment)
    except Exception:
        logger.warning("Falling back to a derived feedback title", exc_info=True)
        return fallback_title(comment)
