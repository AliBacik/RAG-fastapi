import html
import re

_BLOCK_TAG_RE = re.compile(
    r"</?\s*(br|p|div|tr|li|h[1-6]|blockquote)\b[^>]*>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def format_value(value):
    if value is None or value == "":
        return "UNKNOWN"
    return str(value)


def strip_html(text: str) -> str:
    """Convert HTML thread content (Zoho Desk) into plain text.

    Zoho returns thread content as HTML. Leaving the markup in place adds noise
    to the model context, so block-level tags become line breaks and the rest
    are dropped. Plain-text input passes through essentially unchanged.
    """
    if not text or "<" not in text:
        return text

    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL
    )
    with_breaks = _BLOCK_TAG_RE.sub("\n", without_scripts)
    without_tags = _TAG_RE.sub("", with_breaks)
    unescaped = html.unescape(without_tags)

    lines = [line.strip() for line in unescaped.split("\n")]
    collapsed = "\n".join(lines)
    return _EXCESS_BLANK_LINES_RE.sub("\n\n", collapsed).strip()
