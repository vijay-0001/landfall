"""Deterministic guards for the assistant: what it refuses before any model call, and what it replaces after one."""
from __future__ import annotations

import re

_VERBS = r"(accept|approve|decide|choose|pick|select|override|submit|confirm|sign|click|press)"

# Requests to act or to decide.
DECIDE = re.compile(
    rf"\b{_VERBS}\b.{{0,60}}\b(for me|for us|on my behalf|on our behalf)\b|\b(for me|on my behalf)\b.{{0,30}}\b{_VERBS}\b"
    rf"|\b(you|assistant)\b.{{0,15}}\b(decide|choose|pick|accept|override|approve)\b|\bclick\b.{{0,20}}\b(accept|override|submit|confirm)\b"
    r"|\bjust (accept|pick|choose|decide|approve|do it)\b|\baccept (it|this|all|everything)\b|\bdecide (it|this|for)\b|\bwhich one should i (pick|choose|select|accept)\b"
    r"|\bmake the (call|decision)\b|\bbe the declarant\b|\btake (the )?(responsibility|liability|risk)\b|\bi authori[sz]e you\b|\bchoose for me\b",
    re.I | re.S)

# Requests to pay less than is due, or to bend the facts.
CHEAT = re.compile(
    r"\b(pay|paying|owe)\b.{0,25}\b(less|lower|least|nothing|zero|no)\b.{0,20}\b(duty|duties|tax|tariff)\b|\bavoid\b.{0,15}\b(duty|duties|tariff|customs)\b|\bevade\b"
    r"|\bunder-?(declare|value|state)\b|\b(lowest|cheapest|smallest|lower)\b.{0,25}\b(duty|rate|tariff|code)\b|\bdeclare\b.{0,20}\b(less|lower|cheaper|as made in|as if)\b"
    r"|\bpretend\b|\blie\b|\bfake\b|\bmislabel\b|\bsay (it|that)('s| is| was) made in\b",
    re.I | re.S)

# Attempts to change the assistant's rules or role.
INJECTION = re.compile(
    r"ignore (all |the |your |any |previous |prior |above )+(instructions|rules|prompt)|disregard (all |the |your )+(instructions|rules)|you are now|new (instructions|rules|role)"
    r"|system prompt|developer mode|jailbreak|act as (a |an )?(customs|broker|lawyer|different)|forget (everything|your rules)",
    re.I)

# A model answer that claims to have acted or decided.
ACTED = re.compile(
    r"\bi(?:'ve| have|’ve)? (accepted|approved|submitted|overridden|overrode|decided|chosen|selected|clicked)\b"
    r"|\bi(?:'ll|’ll| will| am going to| can) (accept|approve|submit|override|decide|choose|select|click)\b"
    r"|\bi(?:'ve| have) (gone ahead|made the decision)\b|\bdone\.? (the )?(product|code|recommendation) (is|has been) (accepted|approved)\b",
    re.I)

# A model answer that sounds like a ruling or tells the seller what to declare.
DIRECTIVE = re.compile(
    r"\byou should (definitely |just |simply )?(accept|override|declare|choose|pick|select|go with)\b|\bthe (correct|right|final) (code|answer) is\b|\bmy ruling\b|\bi rule\b"
    r"|\bit is (definitely|certainly|legally) \d{4}", re.I)
