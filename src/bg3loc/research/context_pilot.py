"""Offline preparation and isolated provider execution for B1-02 Phase 2.

Reuses the existing OpenAI-compatible provider with pre-rendered Phase 1 messages.
No production state, prompt assembly, retry policy, or provider code is modified.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import mean, median
import time
from urllib.parse import urlsplit

from bg3loc.execution_runner import TranslationSuccess
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.providers.openai_compatible import (
    OpenAICompatibleChatConfig, OpenAICompatibleChatProvider, UrllibJsonTransport,
    openai_compatible_execution_config_hash,
)
from bg3loc.research.context_experiment import CATEGORIES, SAFETY, canonical, digest
from bg3loc.ruleset_io import load_ruleset
from bg3loc.translation_request import TranslationRequest

COUNTS = {"skill_spell": 40, "item": 40, "quest": 20}
SELECTION = "actual field role:length(<80,<250,>=250):related count; sorted strata round robin; SHA256 target then ContentUid"
ORDER = "sort sampleId by SHA256; alternating A-B and B-A (balanced); independent requests"
DIMENSIONS = ("meaning", "naturalness", "terminology", "entityField", "contamination")


def read_jsonl(path: Path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def validate_pair(row):
    """Check that the frozen Phase 1 treatment changes only source context."""
    pack = row["contextPack"]
    a, b = row["baselinePrompt"], row["contextPrompt"]
    if ([m["role"] for m in a] != ["system", "user"]
            or [m["role"] for m in b] != ["system", "user"]):
        raise ValueError("expected two independent system/user messages")
    if b[0]["content"] != a[0]["content"] + "\n\n" + "\n".join(SAFETY):
        raise ValueError("A/B system rules differ beyond context safety")
    a_payload, b_payload = json.loads(a[1]["content"]), json.loads(b[1]["content"])
    fields = b_payload.pop("relatedFields", None)
    entity_type = b_payload.pop("entityType", None)
    expected = [{key: field[key] for key in ("fieldRole", "sourceText", "truncated")} for field in pack["relatedFields"]]
    if a_payload != b_payload or "relatedFields" in a_payload or fields != expected:
        raise ValueError("A/B user payload parity failure")
    if entity_type != pack["structuralEvidence"]["entityType"]:
        raise ValueError("context entity type differs")
    target = pack["target"]
    if a_payload.get("sourceText") != target["sourceText"] or a_payload.get("targetFieldRole") != target["fieldRole"]:
        raise ValueError("target binding failure")
    for variant, messages in (("baseline", a), ("context", b)):
        if row[variant + "PromptHash"] != digest(messages):
            raise ValueError("Phase 1 prompt fingerprint mismatch")


def select_pilot(rows):
    buckets = defaultdict(list)
    seen = set()
    for row in rows:
        validate_pair(row)
        target = row["contextPack"]["target"]
        key = (target["category"], target["contentUid"])
        if key in seen:
            raise ValueError("duplicate Phase 1 target UID")
        seen.add(key)
        size = len(target["sourceText"])
        length = "short" if size < 80 else "medium" if size < 250 else "long"
        stratum = (target["category"], target["fieldRole"], length, len(row["contextPack"]["relatedFields"]))
        buckets[stratum].append(row)
    result = []
    for category in CATEGORIES:
        keys = sorted(k for k in buckets if k[0] == category)
        for key in keys:
            buckets[key].sort(key=lambda row: (digest(row["contextPack"]["target"]), row["contextPack"]["target"]["contentUid"]))
        selected = 0
        while selected < COUNTS[category]:
            progress = False
            for key in keys:
                if buckets[key] and selected < COUNTS[category]:
                    row = dict(buckets[key].pop(0))
                    row["sampleId"] = digest(row["contextPack"]["target"])
                    result.append(row)
                    selected += 1
                    progress = True
            if not progress:
                break
    return result


def call_order(sample):
    ordered = sorted(sample, key=lambda row: (sha256(row["sampleId"].encode()).hexdigest(), row["sampleId"]))
    return [(row, variant) for index, row in enumerate(ordered)
            for variant in (("A", "B") if index % 2 == 0 else ("B", "A"))]


def prepare(prompts: Path, phase1_manifest: Path, output: Path):
    rows = read_jsonl(prompts)
    phase1 = json.loads(phase1_manifest.read_text(encoding="utf-8"))
    if not rows or digest([r["contextPack"] for r in rows]) != phase1["sampleFingerprint"]:
        raise ValueError("Phase 1 sample fingerprint mismatch")
    for variant, prefix in (("A", "baseline"), ("B", "context")):
        if digest([r[prefix + "PromptHash"] for r in rows]) != phase1["promptVariantHashes"][variant]:
            raise ValueError("Phase 1 prompt set fingerprint mismatch")
    sample = select_pilot(rows)
    fingerprint = digest([r["contextPack"] for r in sample])
    manifest_path = output / "b1-02-phase2-pilot-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["pilotSampleFingerprint"] != fingerprint:
            raise ValueError("refusing to replace frozen pilot sample")
        if "maxAttempts" not in manifest:
            manifest["maxAttempts"] = 3
            write_json(manifest_path, manifest)
        return manifest
    manifest = {"schemaVersion": "b1-02-phase2/1", "phase1SampleFingerprint": phase1["sampleFingerprint"],
                "pilotSampleFingerprint": fingerprint, "rulesetFingerprint": phase1["rulesetFingerprint"],
                "sampleCounts": dict(Counter(r["contextPack"]["target"]["category"] for r in sample)),
                "selectionPolicy": SELECTION, "callOrderingPolicy": ORDER,
                "callOrderFingerprint": digest([(r["sampleId"], v) for r, v in call_order(sample)]),
                "promptVariantFingerprints": {v: digest([r[p + "PromptHash"] for r in sample]) for v, p in (("A", "baseline"), ("B", "context"))},
                "plannedCalls": len(sample) * 2, "providerExecutionConfigFingerprint": None,
                "provider": None, "model": None, "maxAttempts": 3, "smokeComplete": False, "executionStatus": "PREPARED"}
    write_jsonl(output / "pilot-sample.jsonl", sample)
    write_json(manifest_path, manifest)
    return manifest


class FrozenPromptTransport:
    """Research-only transport wrapper; existing provider handles parsing and validation."""
    def __init__(self, messages, delegate, request_path, response_path):
        self.messages, self.delegate = messages, delegate
        self.request_path, self.response_path = request_path, response_path
        self.quota_exhausted = False
        self.text = None

    def post_json(self, *, url, headers, payload, timeout_seconds):
        payload = {**payload, "messages": self.messages}
        write_json(self.request_path, payload)  # Never store headers, keys, or transport exceptions.
        result = self.delegate.post_json(url=url, headers=headers, payload=payload, timeout_seconds=timeout_seconds)
        status, response = result[:2]
        err = response.get("error", {})
        code = str(err.get("code", "")) if isinstance(err, dict) else ""
        self.quota_exhausted = code in {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"}
        choices = response.get("choices", [])
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                self.text = message["content"]
        usage = response.get("usage", {})
        safe_usage = {key: value for key, value in usage.items()
                      if key in {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
                      and isinstance(value, int) and not isinstance(value, bool) and value >= 0} if isinstance(usage, dict) else {}
        write_json(self.response_path, {"httpStatus": status, "providerRequestId": response.get("id"),
                                      "translatedText": self.text, "usage": safe_usage or None,
                                      "quotaExhausted": self.quota_exhausted})
        return result


def metrics(values):
    values = sorted(v for v in values if v is not None)
    return {"count": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None,
            "p95": values[(len(values) * 95 + 99) // 100 - 1] if values else None}


def paired_results(results):
    grouped = defaultdict(dict)
    for row in results:
        grouped[row["sampleId"]][row["variant"]] = row
    return {key: rows for key, rows in grouped.items()
            if set(rows) == {"A", "B"} and all(row["status"] == "success" for row in rows.values())}


def build_review(sample, results, output):
    pairs = paired_results(results)
    blind, hidden, diagnostics = [], {}, []
    for row in sample:
        sid = row["sampleId"]
        if sid not in pairs:
            continue
        target = row["contextPack"]["target"]
        variants = ("B", "A") if int(sha256(sid.encode()).hexdigest(), 16) & 1 else ("A", "B")
        blind.append({"sampleId": sid, "sourceText": target["sourceText"], "category": target["category"],
                      "fieldRole": target["fieldRole"], "protectedTokens": extract_protected_tokens(target["sourceText"]),
                      "candidate1": pairs[sid][variants[0]]["translatedText"],
                      "candidate2": pairs[sid][variants[1]]["translatedText"],
                      "scores": {candidate: {dimension: None for dimension in DIMENSIONS} for candidate in ("candidate1", "candidate2")},
                      "preference": None, "contamination": {"candidate1": None, "candidate2": None}, "notes": ""})
        hidden[sid] = {"candidate1": variants[0], "candidate2": variants[1]}
        diagnostics.append({"sampleId": sid, "contextPack": row["contextPack"],
                            "heuristicHints": {v: contamination_hints(pairs[sid][v]["translatedText"], row["contextPack"]) for v in ("A", "B")}})
    write_json(output / "blind-review.json", {"schemaVersion": "b1-02-blind-review/1", "samples": blind})
    write_json(output / "review-key.json", hidden)
    write_json(output / "diagnostics.json", diagnostics)
    return len(blind)


def contamination_hints(text, pack):
    hints = []
    for field in pack["relatedFields"]:
        if field["fieldRole"] in text:
            hints.append("context-field-label")
        if len(field["sourceText"]) >= 8 and field["sourceText"] in text and field["sourceText"] not in pack["target"]["sourceText"]:
            hints.append("verbatim-related-source")
    return sorted(set(hints))


def report(output, manifest, sample, results, attempts):
    paired = paired_results(results)
    categories = {}
    for category in CATEGORIES:
        rows = [r for r in results if r["category"] == category]
        ids = [r["sampleId"] for r in sample if r["contextPack"]["target"]["category"] == category]
        complete = [paired[sid] for sid in ids if sid in paired]
        deltas = [pair["B"]["promptTokens"] - pair["A"]["promptTokens"] for pair in complete
                  if pair["A"]["promptTokens"] is not None and pair["B"]["promptTokens"] is not None]
        categories[category] = {"sampleCount": len(ids), "pairedSuccess": len(complete),
                               "variants": {v: {"successful": sum(r["status"] == "success" for r in rows if r["variant"] == v),
                                                "failed": sum(r["status"] != "success" for r in rows if r["variant"] == v),
                                                "promptTokens": metrics([r["promptTokens"] for r in rows if r["variant"] == v]),
                                                "completionTokens": metrics([r["completionTokens"] for r in rows if r["variant"] == v]),
                                                "latencySeconds": metrics([r["latencySeconds"] for r in rows if r["variant"] == v])} for v in ("A", "B")},
                               "pairedPromptTokenDelta": metrics(deltas)}
    logical = {(row["sampleId"], row["variant"]) for row in attempts}
    summary = {"plannedCalls": manifest["plannedCalls"], "executedCalls": len(results), "providerAttempts": len(attempts),
               "successfulCalls": sum(r["status"] == "success" for r in results),
               "failedCalls": sum(r["status"] != "success" for r in results), "pairedSamples": len(paired),
               "retryCount": len(attempts) - len(logical), "http429Count": sum(r["errorCode"] == "HTTP_429" for r in attempts),
               "http5xxCount": sum(str(r["errorCode"]).startswith("HTTP_5") for r in attempts),
               "protectedSyntaxFailures": sum(r["errorCode"] == "OUTPUT_VALIDATION_FAILED" for r in attempts),
               "categories": categories, "usageAvailable": any(r["promptTokens"] is not None for r in attempts),
               "billedAttemptUsage": {"promptTokens": sum(r["promptTokens"] or 0 for r in attempts) if any(r["promptTokens"] is not None for r in attempts) else None,
                                      "completionTokens": sum(r["completionTokens"] or 0 for r in attempts) if any(r["completionTokens"] is not None for r in attempts) else None,
                                      "promptUsageReportedAttempts": sum(r["promptTokens"] is not None for r in attempts),
                                      "completionUsageReportedAttempts": sum(r["completionTokens"] is not None for r in attempts)},
               "cost": "NOT MEASURED: pricing not supplied", "qualityEvaluation": "PENDING"}
    summary["reviewablePairedSamples"] = build_review(sample, results, output)
    write_json(output / "usage-summary.json", summary)
    lines = ["# B1-02 Provider A/B Pilot Execution", "", f"Status: {manifest['executionStatus']}",
             f"Planned: {summary['plannedCalls']}; executed: {summary['executedCalls']}; successful: {summary['successfulCalls']}; failed: {summary['failedCalls']}; paired: {summary['pairedSamples']}.",
             f"Retries: {summary['retryCount']}; 429: {summary['http429Count']}; 5xx: {summary['http5xxCount']}; syntax failures: {summary['protectedSyntaxFailures']}.",
             "", "| Category | Sample | Paired | A failures | B failures | Mean token delta | Median | P95 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for category, data in categories.items():
        delta = data["pairedPromptTokenDelta"]
        lines.append(f"| {category} | {data['sampleCount']} | {data['pairedSuccess']} | {data['variants']['A']['failed']} | {data['variants']['B']['failed']} | {delta['mean']} | {delta['median']} | {delta['p95']} |")
    lines += ["", "Reviewer handoff: share blind-review.json only. Keep review-key.json and diagnostics.json separate.",
              "Score each candidate 0=bad/wrong, 1=acceptable, 2=strong for meaning, naturalness, terminology, entity-field consistency, and contamination (2=no contamination).",
              "Set contamination YES/NO separately. Preference: candidate1, candidate2, tie, or both_bad. Leave all scoring to a human reviewer.",
              "Human Quality Evaluation = PENDING. Production Integration = NOT STARTED."]
    (output / "execution-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def execute(output: Path, ruleset_path: Path, config: OpenAICompatibleChatConfig, *, smoke=False,
            transport=None, sleeper=time.sleep, monotonic=time.monotonic):
    manifest_path = output / "b1-02-phase2-pilot-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = read_jsonl(output / "pilot-sample.jsonl")
    if digest([r["contextPack"] for r in sample]) != manifest["pilotSampleFingerprint"]:
        raise ValueError("frozen pilot sample fingerprint mismatch")
    for row in sample:
        validate_pair(row)
        if row["sampleId"] != digest(row["contextPack"]["target"]):
            raise ValueError("sample ID differs from target fingerprint")
    if digest([(r["sampleId"], v) for r, v in call_order(sample)]) != manifest["callOrderFingerprint"]:
        raise ValueError("frozen call ordering fingerprint mismatch")
    for variant, prefix in (("A", "baseline"), ("B", "context")):
        if digest([r[prefix + "PromptHash"] for r in sample]) != manifest["promptVariantFingerprints"][variant]:
            raise ValueError("frozen pilot prompt fingerprint mismatch")
    ruleset = load_ruleset(ruleset_path)
    if ruleset.fingerprint() != manifest["rulesetFingerprint"]:
        raise ValueError("ruleset differs from Phase 1")
    parsed = urlsplit(config.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not config.model.strip():
        raise ValueError("provider endpoint and model must be valid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, query, or fragment")
    config_hash = openai_compatible_execution_config_hash(config, ruleset)
    if manifest["providerExecutionConfigFingerprint"] not in (None, config_hash):
        raise ValueError("provider execution config differs from frozen pilot")
    manifest.update({"providerExecutionConfigFingerprint": config_hash, "provider": "openai-compatible",
                     "model": config.model, "executionConfig": {"baseUrl": config.base_url.rstrip("/"), "temperature": config.temperature,
                     "maxOutputTokens": config.max_output_tokens, "timeoutSeconds": config.timeout_seconds},
                     "determinismLimitation": "temperature zero does not guarantee provider determinism"})
    results = read_jsonl(output / "results.jsonl")
    attempts = read_jsonl(output / "attempts.jsonl")
    done = {(r["sampleId"], r["variant"]) for r in results}
    smoke_ids = {next(r["sampleId"] for r in sample if r["contextPack"]["target"]["category"] == c) for c in ("skill_spell", "item")}
    smoke_rows = [r for r in results if r["sampleId"] in smoke_ids]
    if not smoke and (not manifest["smokeComplete"] or len(smoke_rows) != 4 or any(r["status"] != "success" for r in smoke_rows)):
        raise ValueError("four-call smoke must succeed before full pilot")
    stop_reason = None
    write_json(manifest_path, manifest)
    for row, variant in call_order(sample):
        sid = row["sampleId"]
        if (smoke and sid not in smoke_ids) or (sid, variant) in done:
            continue
        target = row["contextPack"]["target"]
        prefix = "baseline" if variant == "A" else "context"
        past = [r for r in attempts if r["sampleId"] == sid and r["variant"] == variant]
        previous_attempts = len(past)
        last = past[-1] if past else None
        last_retryable = last is not None and (last["errorCode"] in {"HTTP_429", "PROVIDER_TRANSPORT_ERROR"}
                                               or str(last["errorCode"]).startswith("HTTP_5"))
        final = last if last and (not last_retryable or previous_attempts >= 3 or last.get("quotaExhausted")) else None
        for attempt in (() if final is not None else range(previous_attempts + 1, 4)):
            stem = f"{sid}-{variant}-{attempt}"
            frozen = FrozenPromptTransport(row[prefix + "Prompt"], transport or UrllibJsonTransport(),
                                           output / "requests" / (stem + ".json"), output / "responses" / (stem + ".json"))
            provider = OpenAICompatibleChatProvider(config=config, ruleset=ruleset, transport=frozen)
            request = TranslationRequest(target["contentUid"], "research-pilot", attempt, row[prefix + "PromptHash"],
                                         target["sourceText"], target["category"], "", (), tuple(extract_protected_tokens(target["sourceText"])))
            started = monotonic()
            outcome = provider(request)
            latency = monotonic() - started
            usage = asdict(outcome.usage) if outcome.usage else {}
            ok = isinstance(outcome, TranslationSuccess)
            code = None if ok else outcome.error_code
            final = {"sampleId": sid, "contentUid": target["contentUid"], "category": target["category"], "fieldRole": target["fieldRole"],
                     "variant": variant, "promptFingerprint": row[prefix + "PromptHash"], "provider": "openai-compatible", "model": config.model,
                     "translatedText": outcome.text if ok else frozen.text, "providerRequestId": outcome.provider_request_id,
                     "promptTokens": usage.get("prompt_tokens"), "completionTokens": usage.get("completion_tokens"), "totalTokens": usage.get("total_tokens"),
                     "latencySeconds": latency, "status": "success" if ok else "invalid" if code == "OUTPUT_VALIDATION_FAILED" else "failed",
                     "errorCode": code, "attempt": attempt, "quotaExhausted": frozen.quota_exhausted}
            attempts.append(final)
            write_jsonl(output / "attempts.jsonl", attempts)
            retryable = not ok and outcome.retryable and (code in {"HTTP_429", "PROVIDER_TRANSPORT_ERROR"} or str(code).startswith("HTTP_5"))
            if frozen.quota_exhausted:
                stop_reason = "quota-exhausted"
                break
            if not retryable or attempt == 3:
                if code == "HTTP_429":
                    stop_reason = "persistent-429"
                break
            sleeper(min(30, outcome.retry_after_seconds if outcome.retry_after_seconds is not None else 2 ** attempt))
        if final is None:
            final = next((r for r in reversed(attempts) if r["sampleId"] == sid and r["variant"] == variant), None)
        if final is None:
            raise ValueError("missing attempt record")
        results.append(final)
        done.add((sid, variant))
        write_jsonl(output / "results.jsonl", results)
        if final.get("quotaExhausted"):
            stop_reason = "quota-exhausted"
        elif final["errorCode"] == "HTTP_429":
            stop_reason = "persistent-429"
        if smoke and final["status"] != "success" and not stop_reason:
            stop_reason = "smoke-failed"
        if final["errorCode"] in {"HTTP_400", "HTTP_401", "HTTP_403", "PROVIDER_CONFIG_INVALID"}:
            stop_reason = "provider-config-or-account-failure"
        if stop_reason:
            break
    smoke_rows = [r for r in results if r["sampleId"] in smoke_ids]
    manifest["smokeComplete"] = len(smoke_rows) == 4 and all(r["status"] == "success" for r in smoke_rows)
    manifest["executionStatus"] = "COMPLETE" if len(results) == manifest["plannedCalls"] and all(r["status"] == "success" for r in results) else "SMOKE_COMPLETE" if smoke and manifest["smokeComplete"] else "PARTIAL"
    manifest["stopReason"] = stop_reason
    write_json(manifest_path, manifest)
    return report(output, manifest, sample, results, attempts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "smoke", "run"))
    parser.add_argument("--output", type=Path, default=Path("workspace/b1-02/phase2"))
    parser.add_argument("--phase1-prompts", type=Path, default=Path("workspace/b1-02/b1-02-prompts.jsonl"))
    parser.add_argument("--phase1-manifest", type=Path, default=Path("workspace/b1-02/b1-02-experiment-manifest.json"))
    parser.add_argument("--ruleset", type=Path, default=Path("docs/lstp/ruleset-example.json"))
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env")
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.mode == "prepare":
        manifest = prepare(args.phase1_prompts, args.phase1_manifest, args.output)
        print(canonical({k: manifest[k] for k in ("pilotSampleFingerprint", "sampleCounts", "plannedCalls")}))
        return
    if not args.base_url or not args.model:
        parser.error("execution requires base URL and model")
    secret = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not secret:
        parser.error("API key environment variable is not set")
    if args.max_output_tokens <= 0 or args.timeout <= 0:
        parser.error("output token limit and timeout must be positive")
    summary = execute(args.output, args.ruleset, OpenAICompatibleChatConfig(
        base_url=args.base_url.rstrip("/"), model=args.model, api_key=secret, temperature=0,
        max_output_tokens=args.max_output_tokens, timeout_seconds=args.timeout), smoke=args.mode == "smoke")
    print(canonical({k: summary[k] for k in ("plannedCalls", "executedCalls", "successfulCalls", "failedCalls", "pairedSamples")}))


if __name__ == "__main__":
    main()
