"""Before you install: what a plugin does with your data, from its own catalog disclosure.

Catalog rule 13 asks every plugin to disclose network calls, credentials, shell commands and
reads outside its own data. Most do, in a "Disclosure" section of their catalog description.
This turns that text into one short line per pick. It only restates what the plugin itself
declares; it never guesses. A plugin with no disclosure is called out as such.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from . import sanitize
except ImportError:  # loaded as a plain module (tests)
    import sanitize

# Any two-letter country ending (evil.ru counts) plus common longer endings. File names such as
# USER.md or plugin.yaml and setting keys such as plugins.isolation are not domains.
_LONG_TLDS = {"com", "net", "org", "edu", "gov", "mil", "int", "info", "biz", "app", "dev", "cloud",
              "tech", "xyz", "site", "online", "store", "live", "run", "page", "tools", "space", "website",
              "email", "chat", "group", "digital", "network", "systems", "software", "solutions",
              "services", "agency", "studio", "design", "news", "blog", "media", "date", "codes", "link"}
_LONG_TLDS |= {"top", "club", "shop", "icu", "vip", "work", "today", "world", "life", "pro", "fun", "lol",
               "wtf", "ninja", "rocks", "zone", "host", "cyou", "buzz", "click", "monster", "bond", "sbs"}
# Endings that are also common file names (USER.md, setup.sh, main.py). They count as a domain
# only in a full host name with at least three parts, such as files.evil.pl.
_FILE_ENDINGS = {"md", "py", "js", "ts", "db", "rs", "cs", "hs", "pl", "rb", "pm", "go", "sh"}
_IP = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_HOST = r"(?:[a-z0-9-]{1,63}\.){1,6}[a-z]{2,24}"  # bounded: no slow backtracking on long dotted text
_DOMAIN = re.compile(r"\b(" + _HOST + r")\b", re.IGNORECASE)
_SENDS = re.compile(r"\bsends?\s+((?:your\s+)?[A-Za-z0-9 ,_/\-]{3,70}?)\s+to\s+(" + _HOST + r")\b", re.IGNORECASE)


def _is_domain(host: str) -> bool:
    parts = host.lower().split(".")
    tld = parts[-1]
    if tld in _FILE_ENDINGS:
        return len(parts) >= 3
    if len(tld) == 2:
        return True
    return tld in _LONG_TLDS
_LOCAL = re.compile(r"\bno network\b|\bmakes no network\b|\bzero network\b|\blocal[- ]only\b|"
                    r"\bno (?:outbound|external) (?:calls|requests)\b|\bnever leaves? (?:your|the) (?:machine|computer)\b",
                    re.IGNORECASE)
_FACTS = [  # (pattern in the disclosure, plain words for you), most serious first
    (re.compile(r"\bmoves? real (?:funds|money)\b|\b(?:release|transfer|send)s? real (?:funds|money)\b|"
                r"\bmoney-moving tools\b|\bsend (?:evm|solana|crypto) transfers\b|\bbuy\w* with (?:a |your )?saved card\b|"
                r"\bpayments plugin\b|\bxstocks trading\b|\bcan (?:trade|place orders|make payments)\b", re.IGNORECASE),
     "can move real money"),
    (re.compile(r"\b(?:reads?|read)\b[^.;]{0,40}\bconversation history\b|\breads?\b[^.;]{0,30}\b(?:your )?(?:chats|messages)\b",
                re.IGNORECASE), "can read your conversations"),
    (re.compile(r"\bsend messages as\b|\bsends? messages on your behalf\b|\bpost(?:s)? as you\b", re.IGNORECASE),
     "can send messages as you"),
    (re.compile(r"\bruns?\b[^.;]{0,25}\b(?:code|shell commands?|commands)\b|\bshell\b|\bsubprocess", re.IGNORECASE),
     "runs commands or code on your computer"),
    (re.compile(r"\bdownloads?\b[^.;]{0,40}\b(?:release|binary|executable|model)\b|"
                r"\binstalls?\b[^.;]{0,40}\b(?:chromium|playwright|browser|packages?|dependencies)\b", re.IGNORECASE),
     "downloads extra software"),
    (re.compile(r"\bsubmits? forms\b|\bfill\w*,? (?:click and )?submit\b|\bfill\w* and submit\w*\b", re.IGNORECASE),
     "can fill in and submit web forms"),
    (re.compile(r"\b(?:uploads?|posts?|transmits?|exfiltrat\w*|sends?|syncs?|copies)\b[^.;:]{0,40}?"
                r"\b(?:your|the user's|user)\b[^.;:]{0,25}?\b(?:files?|notes?|data|messages?|conversations?|"
                r"history|documents?|photos?|memory|memories|contacts)\b", re.IGNORECASE),
     "sends your data off your computer"),
    (re.compile(r"\bbilled\b|\bbillable\b|\bspend\w*\b[^.;]{0,20}\bcredits?\b|\bcredits?\b|\bquota\b|\bpay per\b",
                re.IGNORECASE), "can cost money or use up credits"),
]
MAX_FACTS = 3
# A negation word on its own: "no-frills" and "not only" are not negations.
_NEGATION = re.compile(r"\b(?:no|never|not(?!\s+only)|cannot|without|zero|nor|blocks?|refuses?)\b(?!-)|n't\b",
                       re.IGNORECASE)


# Words that start a new statement. "Without extra setup it moves real money": the "it" means the
# negation belongs to "extra setup", not to moving money.
_RESTART = re.compile(r"\b(?:it|they|this|that|which|will|can|could|may|might|does|do|is|are|was|"
                      r"then|but|however|unless|except|when|if|also|still)\b", re.IGNORECASE)


def _stated(disc: str, match: "re.Match[str]") -> bool:
    """True unless a negation directly governs it ("no network calls, credentials, shell commands").

    A safety check should prefer a false alarm over a false all-clear, so a negation only counts
    when nothing that starts a new statement sits between it and the fact.
    """
    start = max(disc.rfind(";", 0, match.start()), disc.rfind(". ", 0, match.start()), match.start() - 60, 0)
    before = disc[start:match.start()]
    negations = list(_NEGATION.finditer(before))
    if not negations:
        return True
    between = before[negations[-1].end():]
    # a colon or bracket starts a new statement too ("Never fails: reads your history")
    return bool(_RESTART.search(between)) or any(c in between for c in ":()")


# Facts whose own sentence can carry the negation ("never uploads your files")
_SELF_NEGATING = {"sends your data off your computer"}


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def disclosure_text(entry: dict[str, Any]) -> str:
    """The part of the description after the word "Disclosure", or empty."""
    desc = entry.get("description") or ""
    i = desc.lower().find("disclosure")
    return desc[i + len("disclosure"):].lstrip(" :-\u2014\u2013") if i >= 0 else ""


def before_you_install(entry: dict[str, Any]) -> str:
    """One plain line about data, credentials, commands and cost. Empty only if nothing applies."""
    disc = disclosure_text(entry)
    keys = list((entry.get("capabilities") or {}).get("requires_env") or [])
    facts: list[str] = []
    if disc:
        sent = next((m for m in _SENDS.finditer(disc) if _stated(disc, m) and _is_domain(m.group(2))), None)
        if sent:
            what = sanitize.clean(sent.group(1), 70).rstrip(",")
            facts.append(f"sends {what} to {sent.group(2).lower()}")
        else:
            domains = list(dict.fromkeys(
                [d.lower() for d in _DOMAIN.findall(disc) if _is_domain(d) and not d.lower().endswith("nousresearch.com")]
                + _IP.findall(disc)))  # a raw IP address is a destination too
            if domains:
                more = f" and {len(domains) - 1} more" if len(domains) > 1 else ""
                facts.append(f"contacts {domains[0]}{more}")
        for pattern, words in _FACTS:
            if words not in facts and any(_stated(disc, m) and not (words in _SELF_NEGATING and _NEGATION.search(m.group(0)))
                                          for m in pattern.finditer(disc)):
                facts.append(words)
    if keys and not any(k in " ".join(facts) for k in keys):
        facts.append(f"needs your {keys[0]}" + (f" and {len(keys) - 1} more key" + ("s" if len(keys) > 2 else "")
                                                if len(keys) > 1 else ""))
    name = entry.get("name", "")
    if facts:
        return _first_upper("; ".join(facts[:MAX_FACTS])) + "."
    if disc and _LOCAL.search(disc):
        return "Its disclosure says it makes no network calls."
    if not disc:
        return f"Its catalog entry has no disclosure. Check its README first: hermes plugins info {name}"
    # Never claim a plugin is safe: say only that nothing specific was found, and where to look.
    return f"Nothing specific flagged; read its disclosure first: hermes plugins info {name}"
