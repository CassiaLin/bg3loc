from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from bg3loc.providers.openai_compatible import OpenAICompatibleChatConfig
from bg3loc.research.context_experiment import digest, read_rows, render_pair
from bg3loc.research.context_pilot import (
    build_review, call_order, execute, paired_results, prepare, read_jsonl,
    select_pilot, validate_pair, write_json, write_jsonl,
)
from bg3loc.ruleset_io import load_ruleset

FIXTURE = Path(__file__).parent / "fixtures" / "b1_02"


def phase1_rows(counts=(45, 45, 22)):
    originals = read_rows(FIXTURE / "source_rows.jsonl")
    rules = load_ruleset(FIXTURE / "ruleset.json")
    rows = []
    for category, count in zip(("skill_spell", "item", "quest"), counts):
        original = next(r for r in originals if r["category"] == category)
        for index in range(count):
            target = {k: original[k] for k in ("contentUid", "category", "entityKey", "fieldRole", "sourceText")}
            target.update(contentUid=f"fictional-{category}-{index}", entityKey=f"fictional-entity-{index}")
            target["sourceText"] = ("A fictional source. " * (1 + index % 18)) + "{PLAYER}"
            target["fieldRole"] = "DisplayName" if index % 2 else "Description"
            pack = {"target": target, "structuralEvidence": original["structuralEvidence"],
                    "relatedFields": [{"contentUid": f"fictional-related-{index}-{j}", "fieldRole": "Tooltip",
                                       "sourceText": f"Fictional context {j}.", "truncated": False} for j in range(1 + index % 4)]}
            a, b = render_pair(pack, rules)
            rows.append({"contextPack": pack, "baselinePrompt": a, "contextPrompt": b,
                         "baselinePromptHash": digest(a), "contextPromptHash": digest(b)})
    return rows


def prepared(tmp_path, counts=(2, 2, 2)):
    rows = phase1_rows(counts)
    prompts = tmp_path / "phase1-prompts.jsonl"
    manifest = tmp_path / "phase1-manifest.json"
    write_jsonl(prompts, rows)
    write_json(manifest, {"sampleFingerprint": digest([r["contextPack"] for r in rows]),
                         "rulesetFingerprint": load_ruleset(FIXTURE / "ruleset.json").fingerprint(),
                         "promptVariantHashes": {v: digest([r[p + "PromptHash"] for r in rows])
                                                 for v, p in (("A", "baseline"), ("B", "context"))}})
    output = tmp_path / "pilot"
    prepare(prompts, manifest, output)
    return output


class FakeTransport:
    def __init__(self, failures=(), invalid=False):
        self.calls = []
        self.failures = list(failures)
        self.invalid = invalid

    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["payload"]["messages"][1]["content"])
        if self.failures:
            code = self.failures.pop(0)
            return code, {"error": {"message": "synthetic transient error"}}
        text = "Fictional translated output." if self.invalid else "虛構譯文 {PLAYER}"
        return 200, {"id": f"fictional-request-{len(self.calls)}", "choices": [{"message": {"content": text}}],
                     "usage": {"prompt_tokens": 15 if "relatedFields" in payload else 10,
                               "completion_tokens": 5, "total_tokens": 20 if "relatedFields" in payload else 15}}


def config():
    return OpenAICompatibleChatConfig("https://fictional.test", "fictional-model", "fictional-secret", 10, 200, 0)


def test_pilot_subset_deterministic_and_balanced_order():
    rows = phase1_rows()
    first, second = select_pilot(rows), select_pilot(list(reversed(rows)))
    assert first == second
    assert len(first) == 100
    assert [sum(r["contextPack"]["target"]["category"] == c for r in first)
            for c in ("skill_spell", "item", "quest")] == [40, 40, 20]
    order = call_order(first)
    assert len(order) == 200
    assert sum(order[i][1] == "A" for i in range(0, 200, 2)) == 50
    assert all(order[i][0] == order[i + 1][0] and order[i][1] != order[i + 1][1] for i in range(0, 200, 2))


def test_variant_parity_and_tamper_detection():
    row = phase1_rows((1, 1, 1))[0]
    validate_pair(row)
    row["contextPrompt"][0]["content"] += " changed rules"
    with pytest.raises(ValueError, match="system rules"):
        validate_pair(row)


def test_mock_smoke_then_complete_reuses_smoke_and_usage(tmp_path):
    output = prepared(tmp_path)
    transport = FakeTransport()
    with pytest.raises(ValueError, match="smoke"):
        execute(output, FIXTURE / "ruleset.json", config(), transport=transport)
    smoke = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=transport)
    assert smoke["executedCalls"] == 4
    full = execute(output, FIXTURE / "ruleset.json", config(), transport=transport)
    assert len(transport.calls) == 12
    assert full["pairedSamples"] == 6
    assert full["successfulCalls"] == 12
    assert full["categories"]["item"]["pairedPromptTokenDelta"]["mean"] == 5
    assert full["categories"]["item"]["variants"]["A"]["completionTokens"]["mean"] == 5
    assert all(call["payload"]["temperature"] == 0 and call["payload"]["max_tokens"] == 200 for call in transport.calls)
    execute(output, FIXTURE / "ruleset.json", config(), transport=transport)
    assert len(transport.calls) == 12
    assert "fictional-secret" not in "".join(p.read_text(encoding="utf-8") for p in output.rglob("*.json"))


def test_bounded_retries_and_smoke_failure_stops(tmp_path):
    output = prepared(tmp_path)
    transport = FakeTransport((429, 503, 429, 200))
    report = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=transport, sleeper=lambda _: None)
    assert len(transport.calls) == 3
    assert report["retryCount"] == 2
    assert report["http429Count"] == 2 and report["http5xxCount"] == 1
    assert report["pairedSamples"] == 0


def test_invalid_output_preserved_and_not_retried(tmp_path):
    output = prepared(tmp_path)
    transport = FakeTransport(invalid=True)
    report = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=transport)
    assert len(transport.calls) == 1
    assert report["protectedSyntaxFailures"] == 1
    assert read_jsonl(output / "results.jsonl")[0]["translatedText"] == "Fictional translated output."
    assert report["pairedSamples"] == 0


def test_blind_swapping_hidden_mapping_and_no_variant_leakage(tmp_path):
    sample = select_pilot(phase1_rows((2, 2, 2)))
    results = [{"sampleId": row["sampleId"], "variant": variant, "status": "success",
                "translatedText": f"fictional translation {variant}"} for row in sample for variant in ("A", "B")]
    results[0]["status"] = "invalid"
    assert len(paired_results(results)) == 5
    assert build_review(sample, results, tmp_path) == 5
    blind = json.loads((tmp_path / "blind-review.json").read_text())
    validate(blind, json.loads((Path(__file__).parents[1] / "schemas/research/b1-02-blind-review-v1.schema.json").read_text()))
    hidden = json.loads((tmp_path / "review-key.json").read_text())
    for row in blind["samples"]:
        assert not {"variant", "baselinePrompt", "contextPrompt", "relatedFields"} & row.keys()
        assert row["candidate1"] == "fictional translation " + hidden[row["sampleId"]]["candidate1"]
        assert row["candidate2"] == "fictional translation " + hidden[row["sampleId"]]["candidate2"]
        assert row["preference"] is None and all(v is None for v in row["scores"]["candidate1"].values())


def test_provider_config_locked_after_smoke(tmp_path):
    output = prepared(tmp_path)
    execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=FakeTransport())
    with pytest.raises(ValueError, match="config differs"):
        execute(output, FIXTURE / "ruleset.json", OpenAICompatibleChatConfig("https://other.test", "fictional-model"), transport=FakeTransport())


def test_frozen_sample_id_tampering_rejected(tmp_path):
    output = prepared(tmp_path)
    sample = read_jsonl(output / "pilot-sample.jsonl")
    sample[0]["sampleId"] = "bad-id"
    write_jsonl(output / "pilot-sample.jsonl", sample)
    with pytest.raises(ValueError, match="sample ID"):
        execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=FakeTransport())


def test_quota_exhaustion_stops_without_switching_provider(tmp_path):
    class QuotaTransport:
        def post_json(self, **kwargs):
            return 429, {"error": {"code": "insufficient_quota", "message": "fictional quota exhausted"}}
    output = prepared(tmp_path)
    report = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=QuotaTransport(), sleeper=lambda _: None)
    assert report["providerAttempts"] == 1 and report["retryCount"] == 0


def test_missing_usage_is_unavailable(tmp_path):
    class NoUsageTransport:
        def post_json(self, **kwargs):
            return 200, {"choices": [{"message": {"content": "虛構譯文 {PLAYER}"}}]}
    output = prepared(tmp_path)
    report = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=NoUsageTransport())
    assert report["usageAvailable"] is False
    assert report["billedAttemptUsage"]["promptTokens"] is None


def test_completed_attempts_recovered_without_duplicate_provider_calls(tmp_path):
    output = prepared(tmp_path)
    transport = FakeTransport()
    execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=transport)
    (output / "results.jsonl").unlink()
    summary = execute(output, FIXTURE / "ruleset.json", config(), smoke=True, transport=transport)
    assert summary["successfulCalls"] == 4 and len(transport.calls) == 4
