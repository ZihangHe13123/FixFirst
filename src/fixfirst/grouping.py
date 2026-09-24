import hashlib
import re
from functools import lru_cache

from .models import Event, Issue, Run


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:14]


def normalize(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"\b\d{4}-\d\d-\d\d[T ][\d:.+Z-]+", "<time>", text)
    text = re.sub(r"(?:/private)?/tmp/[^\s:]+", "<temporary-path>", text)
    text = re.sub(r"(?<= object at )0x[0-9a-fA-F]+(?=>)", "<address>", text)
    return " ".join(text.split())


def member_key(item: Event) -> str:
    # Preserve paths, versions and the full missing import name. Group != root cause.
    return digest(
        "|".join(
            (
                item.tool,
                item.stage,
                item.kind,
                item.component,
                item.location,
                item.code,
                normalize(item.message),
            )
        )
    )


def block_key(item: Event) -> tuple:
    versions = tuple(re.findall(r"\b\d+(?:\.\d+)+(?:[\w.+-]*)", item.message))
    location = item.location if item.tool == "ruff" or not item.component else ""
    return item.tool, item.stage, item.kind, item.component, versions, location


@lru_cache(maxsize=2)
def load_sbert(path):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(path, local_files_only=True, device="cpu", trust_remote_code=False)


def similarity(texts, method, model_path=None):
    if method == "exact":
        return [[float(a == b) for b in texts] for a in texts]
    if method == "sbert":
        if not model_path:
            raise ValueError("SBERT needs --sbert-model pointing to a downloaded local model directory")
        model = load_sbert(model_path)
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors @ vectors.T
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    try:
        vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(texts)
        return cosine_similarity(vectors)
    except ValueError:
        return [[float(a == b) for b in texts] for a in texts]


def complete_link(matrix, threshold):
    """Deterministic complete-link threshold grouping, never single-link chaining."""
    groups = []
    for i in range(len(matrix)):
        for group in groups:
            if all(matrix[i][j] >= threshold for j in group):
                group.append(i)
                break
        else:
            groups.append([i])
    return groups


def group_events(
    events: list[Event], run: Run, method="tfidf", threshold=0.82, model_path=None
) -> list[Issue]:
    blocks = {}
    for item in events:
        blocks.setdefault(block_key(item), []).append(item)
    issues = []
    for _, block in sorted(blocks.items()):
        block.sort(key=lambda item: (normalize(item.message), item.location, item.line))
        # Bound all-pairs work on verbose logs. Chunk boundaries may reduce recall, never accuracy.
        for offset in range(0, len(block), 250):
            chunk = block[offset : offset + 250]
            texts = [normalize(item.message) for item in chunk]
            matrix = similarity(texts, method, model_path)
            for indexes in complete_link(matrix, threshold):
                members = [chunk[i] for i in indexes]
                first = members[0]
                keys = sorted(set(member_key(item) for item in members))
                fingerprint = digest("|".join(keys))
                score = min(float(matrix[i][j]) for i in indexes for j in indexes)
                issues.append(
                    Issue(
                        issue_id="issue-" + fingerprint,
                        fingerprint=fingerprint,
                        tool=first.tool,
                        stage=first.stage,
                        kind=first.kind,
                        component=first.component,
                        title=(
                            f"Assertion failed · {first.location}"
                            if first.kind == "test_assertion"
                            else f"{first.code or first.stage} · {first.location}"
                            if first.kind == "test_runtime_error"
                            else re.sub(r" \((?:/|<|[A-Za-z]:\\)[^()]*\)$", "", first.message)[:240]
                        ),
                        event_ids=[item.event_id for item in members],
                        evidence_refs=sorted(
                            {ref for item in members for ref in item.evidence_refs}
                        ),
                        member_keys=keys,
                        scope=run.scope,
                        environment_id=run.environment_id,
                        group_score=round(score, 4),
                        targets=sorted(
                            {
                                m.location
                                for m in members
                                if m.tool == "pytest_run"
                                and m.stage in ("setup", "call", "teardown")
                                and "::" in m.location
                            }
                        ),
                    )
                )
    return issues
