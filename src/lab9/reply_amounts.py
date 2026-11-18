"""Extract amounts asserted as the current completed refund in reply text."""

from __future__ import annotations

from dataclasses import dataclass
import re

_NUMBER = r"[+\-−]?\d+(?:[.,\s\u00a0\u202f]+\d+)*"
_CURRENCY = r"(?:₫|đồng|đ(?!\w)|vnd(?!\w)|vnđ(?!\w))"
_MONEY = re.compile(
    rf"(?:(?P<prefix>₫|vnd|vnđ)\s*(?P<prefix_number>{_NUMBER})|"
    rf"(?P<number>{_NUMBER})\s*(?P<scale>nghìn|ngàn|k)\b\s*(?:{_CURRENCY})?|"
    rf"(?P<amount>{_NUMBER})\s*{_CURRENCY})",
    re.IGNORECASE,
)
_SPLIT_CLAUSES = re.compile(
    r"(?<=[!?;\n])\s+|\.(?=\s+)|,(?=\s+[^\d\s])|"
    r"\s+(?:nhưng|but|however|yet)\s+|\s+(?:và\s+sẽ|and\s+will)\s+|"
    r"\s+(?:trên|on)\s+(?:phí\s+gốc|the\s+original\s+fee)\b\s*|"
    r"\s+(?:so\s+với|compared\s+(?:to|with))\s+|"
    r"\s+và\s+(?=(?:đã\s+)?(?:chuyển|gửi)\s+yêu\s+cầu\b)", re.I
)
_PRIOR = re.compile(r"\b(?:trước\s+đó|đã\s+từng|lần\s+trước|previously|earlier|prior\s+refund)\b", re.I)
_COMPLETED = (
    r"\bđã\s+(?:(?:được|xử\s+lý)\s+)?hoàn\b|"
    r"\b(?:refund\s+processed|payment\s+sent)\b|"
    r"(?<!not )(?<!n't )\b(?:refunded|paid|credited)\b|"
    r"(?<!not )(?<!n't )\bissued\s+(?:(?:a|the|your)\s+)?refund\b|"
    r"\brefund\s+of\b.+?\b(?:was|has\s+been)\s+issued\b"
)
_PAID = re.compile(
    rf"{_COMPLETED}|"
    r"\bhoàn(?:\s+của\s+đơn)?\s*(?::|\blà\b)|"
    r"\brefund(?:\s+amount)?\s*(?::|\bis\b)|"
    r"(?<!yêu cầu )\bhoàn\s+[+-]?\d", re.I,
)
_PAID_TRANSFER = re.compile(
    rf"\bđã\s+chuyển\s+(?:{_NUMBER}\s*(?:{_CURRENCY})?\s+tiền\s+hoàn|"
    rf"tiền\s+hoàn\s+{_NUMBER})\b", re.I,
)
_FUTURE = re.compile(r"\b(?:nếu|sẽ|pending|requested|yêu\s+cầu)\b", re.I)
_EXPLICIT_COMPLETED = re.compile(_COMPLETED, re.I)
_PARTIAL_DENIAL = re.compile(r"\bkhông\s+(?:hoàn|được\s+hoàn)\s+thêm\b", re.I)
_NEGATED_PAID = re.compile(
    r"\bkhông\s+(?:được\s+)?hoàn\b|\b(?:was\s+)?not\s+(?:refunded|paid|credited)\b|\bwasn't\s+(?:refunded|paid|credited)\b", re.I
)
_FULL_REFUSAL = re.compile(
    r"\b(?:chưa\s+đủ\s+điều\s+kiện|không\s+(?:thể|được)\s+hoàn|"
    r"từ\s+chối\s+hoàn|không\s+hoàn|not\s+eligible|cannot\s+refund|refund\s+denied)\b|"
    r"\bkhông\s+hoàn\s+(?:bất\s+kỳ|any)\b|\b(?:was\s+)?not\s+(?:refunded|paid|credited)\b|\bwasn't\s+(?:refunded|paid|credited)\b", re.I,
)
_FEE_PAREN = re.compile(r"\([^()]*\b(?:phí|fee)\b[^()]*\)", re.I)
_ORIGINAL_FEE = re.compile(r"\b(?:original|initial)\s+(?:fee|charge)\b|\bphí\s+(?:gốc|ban\s+đầu)\b", re.I)
_REFUND_WORD = re.compile(r"\b(?:hoàn|refund|refunded)\b", re.I)


@dataclass(frozen=True)
class ReplyClaims:
    amounts: tuple[int, ...]
    paid_claim: bool
    unparseable_paid_claim: bool
    full_refusal: bool


def _number_value(raw: str) -> int | None:
    """Parse an integer VND figure, allowing unambiguous zero decimals."""
    sign = -1 if raw.startswith(("-", "−")) else 1
    digits = raw.lstrip("+-−").replace("\u00a0", " ").replace("\u202f", " ")
    if any(char.isspace() for char in digits):
        groups = re.split(r"\s+", digits.strip())
        if not groups or not groups[0].isdigit() or not 1 <= len(groups[0]) <= 3:
            return None
        if any(not group.isdigit() or len(group) != 3 for group in groups[1:]):
            return None
        return sign * int("".join(groups))

    separators = {char for char in digits if char in ".,"}
    if not separators:
        return sign * int(digits)
    if len(separators) == 1:
        sep = next(iter(separators))
        groups = digits.split(sep)
        if all(len(group) == 3 for group in groups[1:]) and 1 <= len(groups[0]) <= 3:
            return sign * int("".join(groups))
        if len(groups) == 2 and len(groups[1]) in (1, 2) and set(groups[1]) <= {"0"}:
            return sign * int(groups[0])
        return None

    # Mixed separators need an unambiguous zero fractional suffix.
    last = max(digits.rfind("."), digits.rfind(","))
    fraction = digits[last + 1 :]
    integer_part = digits[:last]
    if len(fraction) in (1, 2) and fraction and set(fraction) == {"0"}:
        groups = re.split(r"[.,]", integer_part)
        if 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
            return sign * int("".join(groups))
    # Mixing dot and comma as grouping marks is ambiguous (2,345.678).
    return None


def parse_reply_claims(text: str) -> ReplyClaims:
    """Return only current completed-refund amounts plus fail-closed claim flags."""
    amounts: list[int] = []
    paid = False
    unparseable = False
    refusal = False
    for clause in _SPLIT_CLAUSES.split(text):
        clause = clause.strip()
        if not clause or _PRIOR.search(clause):
            continue
        claim_text = _FEE_PAREN.sub(" ", clause)
        if _ORIGINAL_FEE.search(claim_text) and not _REFUND_WORD.search(claim_text):
            continue
        partial_denial = bool(_PARTIAL_DENIAL.search(clause))
        if _FULL_REFUSAL.search(clause) and not partial_denial:
            refusal = True

        is_paid = bool(_PAID.search(claim_text) or _PAID_TRANSFER.search(claim_text))
        if is_paid and _NEGATED_PAID.search(claim_text) and not _EXPLICIT_COMPLETED.search(claim_text):
            is_paid = False
        if is_paid and _FUTURE.search(claim_text) and not _EXPLICIT_COMPLETED.search(claim_text):
            is_paid = False
        if not is_paid:
            continue
        paid = True
        matches = list(_MONEY.finditer(claim_text))
        if not matches:
            unparseable = True
            continue
        for match in matches:
            raw = match.group("prefix_number") or match.group("number") or match.group("amount")
            value = _number_value(raw)
            if match.group("scale"):
                value = value * 1000 if value is not None else None
            if value is None:
                unparseable = True
            else:
                amounts.append(value)
    return ReplyClaims(tuple(amounts), paid, unparseable, refusal)
