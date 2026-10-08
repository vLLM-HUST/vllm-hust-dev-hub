#!/usr/bin/env python3
import argparse
import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path


PROMPTS = [
    "Answer in one short sentence: What is the capital of France?",
    "Compute 37 * 19. Give only the integer.",
    "Translate 'distributed systems' into Chinese. Give only the translation.",
    "Name the chemical symbol for gold. Give only the symbol.",
    "In one sentence, explain why the sky looks blue.",
] * 2


def percentile(values, p):
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def run_one(url, model, prompt):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 64,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first = None
    pieces = []
    usage = None
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices") or []
            content = choices[0].get("delta", {}).get("content") if choices else None
            if content:
                if first is None:
                    first = time.perf_counter()
                pieces.append(content)
    ended = time.perf_counter()
    text = "".join(pieces)
    completion_tokens = int((usage or {}).get("completion_tokens", 0))
    return {
        "prompt": prompt,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "usage": usage,
        "ttft_s": None if first is None else first - started,
        "latency_s": ended - started,
        "output_tokens_per_s": (
            completion_tokens / (ended - first)
            if first is not None and ended > first and completion_tokens > 1
            else None
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-30B-A3B")
    parser.add_argument("--url", default="http://127.0.0.1:8001/v1/chat/completions")
    args = parser.parse_args()
    records = [run_one(args.url, args.model, prompt) for prompt in PROMPTS]
    ttft = [r["ttft_s"] for r in records if r["ttft_s"] is not None]
    latency = [r["latency_s"] for r in records]
    throughput = [r["output_tokens_per_s"] for r in records if r["output_tokens_per_s"] is not None]
    summary = {
        "requests": len(records),
        "ttft_p50_s": statistics.median(ttft),
        "ttft_p95_s": percentile(ttft, 0.95),
        "latency_p50_s": statistics.median(latency),
        "latency_p95_s": percentile(latency, 0.95),
        "output_tokens_per_s_p50": statistics.median(throughput),
        "output_tokens_per_s_p95": percentile(throughput, 0.95),
        "output_hashes": [r["text_sha256"] for r in records],
    }
    args.output.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
