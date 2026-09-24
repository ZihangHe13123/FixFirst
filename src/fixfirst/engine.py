"""Forward-chaining production system: variables, stratified negation and provenance.

Rules live in ``knowledge/rules.toml``. A rule matches patterns over (subject, predicate,
value) facts, binds ``?variables`` and either asserts new facts or proposes an action.
Phases run in order; a negated pattern may only test predicates that no rule in the same
or a later phase can still conclude, so negation-as-failure is always evaluated against a
complete lower stratum.
"""

from dataclasses import dataclass, field
import re

from packaging.version import InvalidVersion, Version

from .models import Fact

PHASES = ("derive", "diagnose", "heuristic", "fallback", "plan")
MAX_FACTS = 20_000
TESTS = ("version_gte", "version_lt", "in", "not_in", "eq", "ne")


def is_var(term) -> bool:
    return isinstance(term, str) and term.startswith("?")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    phase: str
    when: tuple
    then: tuple = ()
    action: dict | None = None
    status: str = "derived"
    description: str = ""
    source: str = ""


def parse_pattern(raw) -> tuple:
    if not isinstance(raw, list) or not all(isinstance(term, str) for term in raw):
        raise ValueError(f"invalid pattern {raw!r}")
    if raw and raw[0] == "not" and len(raw) == 4:
        return ("not", *raw[1:])
    if raw and raw[0] == "test" and len(raw) == 4:
        if raw[1] not in TESTS:
            raise ValueError(f"unknown test {raw[1]!r}")
        return ("test", *raw[1:])
    if len(raw) == 3:
        return ("fact", *raw)
    raise ValueError(f"invalid pattern {raw!r}")


def load_rules(data: dict) -> list[Rule]:
    rules = []
    for row in data.get("rule", []):
        rule = Rule(
            rule_id=row["id"],
            phase=row["phase"],
            when=tuple(parse_pattern(p) for p in row["when"]),
            then=tuple(tuple(t) for t in row.get("then", [])),
            action=row.get("action"),
            status=row.get("status", "derived"),
            description=row.get("description", ""),
            source=row.get("source", ""),
        )
        rules.append(rule)
    validate(rules)
    return rules


def validate(rules: list[Rule]) -> None:
    ids = [r.rule_id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate rule id")
    concluded = {}
    for rule in rules:
        if rule.phase not in PHASES:
            raise ValueError(f"{rule.rule_id}: unknown phase {rule.phase}")
        if rule.status not in ("derived", "hypothesis"):
            raise ValueError(f"{rule.rule_id}: invalid status")
        if (rule.phase == "plan") != bool(rule.action) or (rule.phase == "plan" and rule.then):
            raise ValueError(f"{rule.rule_id}: plan rules propose actions, others assert facts")
        for template in rule.then:
            if len(template) != 3 or is_var(template[1]):
                raise ValueError(f"{rule.rule_id}: conclusions need a constant predicate")
            concluded.setdefault(template[1], set()).add(PHASES.index(rule.phase))
    for rule in rules:
        level = PHASES.index(rule.phase)
        bound = set()
        for pattern in rule.when:
            kind = pattern[0]
            if kind == "fact":
                bound.update(t for t in pattern[1:] if is_var(t))
            elif kind == "not":
                if is_var(pattern[2]) or any(p >= level for p in concluded.get(pattern[2], ())):
                    raise ValueError(
                        f"{rule.rule_id}: negated '{pattern[2]}' is concluded in this or a "
                        "later phase (unstratified negation)"
                    )
            elif any(is_var(a) and a not in bound for a in pattern[2:]):
                raise ValueError(f"{rule.rule_id}: test uses an unbound variable")
        for template in rule.then:
            if any(is_var(t) and t not in bound for t in template):
                raise ValueError(f"{rule.rule_id}: conclusion uses an unbound variable")


class FactBase:
    def __init__(self, facts=()):
        self.facts: list[Fact] = []
        self.keys: set[tuple] = set()
        self.by_predicate: dict[str, list[Fact]] = {}
        for fact in facts:
            self.add(fact)

    def add(self, fact: Fact) -> bool:
        key = (fact.subject, fact.predicate, fact.value)
        if key in self.keys:
            return False
        self.keys.add(key)
        self.facts.append(fact)
        self.by_predicate.setdefault(fact.predicate, []).append(fact)
        return True

    def candidates(self, predicate):
        return self.facts if is_var(predicate) else self.by_predicate.get(predicate, [])

    def values(self, subject, predicate) -> list[str]:
        return [f.value for f in self.candidates(predicate) if f.subject == subject]


def unify(term, value, bindings):
    if term == "?_":
        return bindings
    if is_var(term):
        bound = bindings.get(term)
        if bound is None:
            return {**bindings, term: value}
        return bindings if bound == value else None
    return bindings if term == value else None


def version(value):
    try:
        return Version(value)
    except (InvalidVersion, TypeError):
        return None


def check(op, left, right) -> bool:
    if op in ("version_gte", "version_lt"):
        a, b = version(left), version(right)
        if a is None or b is None:
            return False
        return a >= b if op == "version_gte" else a < b
    options = {item.strip() for item in right.split(",")}
    return {
        "in": left in options,
        "not_in": left not in options,
        "eq": left == right,
        "ne": left != right,
    }[op]


def resolve(term, bindings):
    return bindings.get(term, term) if is_var(term) else term


def matches(patterns, base: FactBase, bindings=None, used=()):
    """Yield (bindings, facts used) for every way the patterns hold in the fact base."""
    bindings = bindings or {}
    if not patterns:
        yield bindings, used
        return
    head, rest = patterns[0], patterns[1:]
    kind = head[0]
    if kind == "fact":
        _, subject, predicate, value = head
        for fact in base.candidates(resolve(predicate, bindings)):
            found = unify(subject, fact.subject, bindings)
            found = found if found is None else unify(predicate, fact.predicate, found)
            found = found if found is None else unify(value, fact.value, found)
            if found is not None:
                yield from matches(rest, base, found, (*used, fact))
    elif kind == "not":
        if next(matches((("fact", *head[1:]),), base, bindings), None) is None:
            yield from matches(rest, base, bindings, used)
    elif check(head[1], resolve(head[2], bindings), resolve(head[3], bindings)):
        yield from matches(rest, base, bindings, used)


def instantiate(template, bindings):
    return tuple(resolve(term, bindings) for term in template)


def run(rules: list[Rule], facts: list[Fact], phases=PHASES[:-1]) -> FactBase:
    """Apply fact-asserting phases to a fixpoint. Terminates: no new constants are created."""
    base = FactBase(facts)
    for phase in phases:
        active = [r for r in rules if r.phase == phase]
        changed = True
        while changed:
            changed = False
            for rule in active:
                for bindings, used in list(matches(rule.when, base)):
                    hypothesis = rule.status == "hypothesis" or any(
                        f.status == "hypothesis" for f in used
                    )
                    for template in rule.then:
                        subject, predicate, value = instantiate(template, bindings)
                        fact = Fact(
                            fact_id=f"{subject}:{predicate}:{value}",
                            subject=subject,
                            predicate=predicate,
                            value=value,
                            status="hypothesis" if hypothesis else "derived",
                            rule_id=rule.rule_id,
                            inputs=[f.fact_id for f in used],
                            evidence_refs=sorted({r for f in used for r in f.evidence_refs}),
                        )
                        if base.add(fact):
                            changed = True
                            if len(base.facts) > MAX_FACTS:
                                raise ValueError("rule base produced too many facts")
    return base


def display(value: str) -> str:
    """Readable form of a typed constant such as ``api:numpy.float``."""
    if value == "dist:python":
        return "Python"
    return re.sub(r"^(module|api|kwarg|dist|config|file|callable):", "", value)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", display(value)).strip("-").lower()


def render(text: str, bindings: dict, identifier=False, filters=None) -> str:
    """Fill ``{?var}`` or ``{?var|filter}`` placeholders from rule bindings."""

    def replace(match):
        value = bindings.get(match.group(1), match.group(0))
        if match.group(2):
            value = (filters or {})[match.group(2)](value)
        return slug(value) if identifier else display(value)

    return re.sub(r"\{(\?\w+)(?:\|(\w+))?\}", replace, text)


@dataclass
class Proposal:
    """An action proposed by one or more rule instantiations, merged by rendered id."""

    action_id: str
    template: dict
    bindings: dict
    rule_ids: list[str] = field(default_factory=list)
    issue_ids: list[str] = field(default_factory=list)
    reason_facts: list[Fact] = field(default_factory=list)


def propose(rules: list[Rule], base: FactBase) -> list[Proposal]:
    proposals: dict[str, Proposal] = {}
    for rule in (r for r in rules if r.phase == "plan"):
        for bindings, used in matches(rule.when, base):
            action_id = render(rule.action["id"], bindings, identifier=True)
            proposal = proposals.setdefault(
                action_id, Proposal(action_id, rule.action, bindings)
            )
            if rule.rule_id not in proposal.rule_ids:
                proposal.rule_ids.append(rule.rule_id)
            issue = resolve(rule.action.get("issue", ""), bindings)
            if issue and issue not in proposal.issue_ids:
                proposal.issue_ids.append(issue)
            known = {f.fact_id for f in proposal.reason_facts}
            proposal.reason_facts += [f for f in used if f.fact_id not in known]
    return sorted(proposals.values(), key=lambda p: p.action_id)
