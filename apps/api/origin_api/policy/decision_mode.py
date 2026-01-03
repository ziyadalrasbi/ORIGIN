"""Decision mode enumeration for policy engine."""

from enum import Enum


class DecisionMode(str, Enum):
    """Decision evaluation modes."""

    SCORE_FIRST = "score_first"
    RULE_OVERRIDE = "rule_override"
    ANOMALY_ESCALATION = "anomaly_escalation"
    SYNTHETIC_ESCALATION = "synthetic_escalation"
    LABEL_FIRST = "label_first"

