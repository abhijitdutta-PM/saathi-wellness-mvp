"""Conservative baseline triage rules for an MVP. Not a clinical risk model."""
import re
from dataclasses import dataclass

RULE_VERSION = "keyword-rules-v1"

URGENT_PATTERNS = [
    ("self_harm_or_suicide", r"\b(kill myself|want to die|i want to die|end my life|suicid(?:e|al)|hurt myself|harm myself|cut myself|self[- ]harm|don't want to live|do not want to live|no reason to live)\b"),
    ("immediate_danger", r"\b(going to kill (him|her|them|someone)|i will kill (him|her|them|someone)|about to hurt (myself|someone)|in immediate danger|someone is hurting me right now)\b"),
]
SIGNIFICANT_PATTERNS = [
    ("possible_abuse_or_unsafe_home", r"\b(abuse|abused|being hurt at home|not safe at home|unsafe at home|touching me|sexually abused|forced me to|threatened me)\b"),
    ("bullying_or_threats", r"\b(bully|bullying|being bullied|threaten(?:ed|ing)? me|they hit me|someone hit me|blackmail)\b"),
    ("serious_distress", r"\b(hopeless|worthless|can't go on|cannot go on|nobody would care|no one would care|trapped and scared)\b"),
]
DISTRESS_TERMS = re.compile(r"\b(sad|lonely|anxious|worried|scared|stressed|overwhelmed|upset|panic|afraid|crying|isolated)\b", re.I)

@dataclass
class Assessment:
    urgency: str
    category: str
    matched_terms: list[str]
    reason: str
    create_case: bool


def assess_text(text: str, recent_distress_count: int = 0) -> Assessment:
    normalized = " ".join((text or "").lower().split())
    for category, pattern in URGENT_PATTERNS:
        match = re.search(pattern, normalized, re.I)
        if match:
            return Assessment("immediate", category, [match.group(0)], "The message contains language that warrants urgent human safety review.", True)
    for category, pattern in SIGNIFICANT_PATTERNS:
        match = re.search(pattern, normalized, re.I)
        if match:
            return Assessment("human_review", category, [match.group(0)], "The message may describe a safeguarding concern and needs a trained person's review.", True)
    matches = sorted({m.group(0).lower() for m in DISTRESS_TERMS.finditer(normalized)})
    if matches and recent_distress_count >= 2:
        return Assessment("human_review", "recurring_distress", matches, "Repeated expressions of distress may warrant a supportive human check-in.", True)
    if matches:
        return Assessment("routine", "emotional_distress", matches, "The message expresses difficult feelings; offer supportive reflection without assigning a diagnosis.", False)
    return Assessment("routine", "general_wellbeing", [], "No rule-based safety trigger was detected. This does not establish that a student is safe.", False)


def safe_buddy_fallback(message: str, age_band: str | None = None) -> str:
    lowered = (message or "").lower()
    if age_band == "6-10":
        return "Thank you for telling me. Big feelings can be hard to carry alone. Can you tell me what happened, one small part at a time? If you feel unsafe, please tell a safe grown-up now."
    if any(term in lowered for term in ("exam", "test", "marks", "grade", "homework", "school")):
        return "It sounds like this has been weighing on you. One difficult day doesn't define you. Would it help to separate what you can influence today from what you can't, then choose one small next step?"
    if any(term in lowered for term in ("sad", "lonely", "upset", "cry", "left out", "friend")):
        return "I'm glad you shared that with me. It can hurt when things feel this way. You don't have to solve everything at once. Would you rather tell me a little more, or try a short grounding exercise together?"
    if any(term in lowered for term in ("angry", "fight", "annoyed", "frustrated")):
        return "That sounds frustrating. Before deciding what to do, it may help to pause and name what mattered most to you in that moment. What part felt hardest?"
    return "Thank you for sharing that with me. I want to understand before jumping to advice. What part of this has been weighing on you the most? We can take it one step at a time."


def urgent_support_message(support_instructions: str | None = None) -> str:
    custom = (support_instructions or "").strip()
    base = (
        "I'm glad you told me. You deserve support with this now. Please reach out to a trusted adult or your school's designated support person immediately. "
        "If you may be in immediate danger, contact local emergency services. This app cannot guarantee an immediate human response, so please don't wait here for help."
    )
    if custom:
        return base + "\n\nSupport information for your school: " + custom[:500]
    return base
