"""Conservative extraction of directly stated, durable user facts."""

import re


SENSITIVE = re.compile(
    r"\b(password|passcode|pin|secret|token|api key|social security|ssn|"
    r"credit card|debit card|bank|account number|address|phone number|email)\b",
    re.IGNORECASE,
)
ALLOWED_KEYS = re.compile(
    r"^(name|speaker|music service|time\s*zone|city|occupation|"
    r"(?:favorite|preferred|main) [a-z][a-z\s-]{1,50})$",
    re.IGNORECASE,
)


def stable_facts(text: str) -> list[tuple[str, str]]:
    """Return a small set of facts from plain first-person statements only."""
    if "?" in text or SENSITIVE.search(text):
        return []
    facts = []
    for sentence in re.split(r"[.!\n]+", text):
        sentence = sentence.strip()
        match = re.fullmatch(r"[Mm]y ([a-z][a-z\s-]{1,50}) is ([^;]{1,100})", sentence)
        if match:
            key, value = match.group(1).strip().lower(), match.group(2).strip()
            if ALLOWED_KEYS.fullmatch(key) and not SENSITIVE.search(value):
                facts.append((key, value))
        match = re.fullmatch(r"[Ii] use ([A-Za-z][\w .-]{1,50}) for music", sentence)
        if match:
            facts.append(("music service", match.group(1).strip()))
        match = re.fullmatch(r"[Mm]y ([a-zA-Z][a-zA-Z\s-]{1,45}(?:codebase|project)) uses (Java|Python|JavaScript|TypeScript|C\+\+|C#|Rust|Go|Kotlin|Swift)", sentence)
        if match:
            facts.append((match.group(1).strip().lower() + " language", match.group(2)))
        if len(facts) >= 2:
            break
    return facts
