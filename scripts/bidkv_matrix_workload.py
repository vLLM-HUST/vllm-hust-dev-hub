#!/usr/bin/env python3
"""Bounded streaming workload for cell-scoped BidKV TP4 graph qualification."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path

import httpx


PARAGRAPH = (
    "Cache scheduling evidence preserves request identity, progress, fairness, "
    "and deterministic recomputation under pressure. "
)
SPECIAL_TOKEN_MARKERS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>")
SEMANTIC_TERMS = ("request", "cache", "schedul", "preempt", "progress", "fair")


def output_validity(output: str, exact_expected: str | None) -> dict[str, object]:
    normalized = output.strip()
    special_token_leaks = [
        marker for marker in SPECIAL_TOKEN_MARKERS if marker in output
    ]
    semantic_hits = [term for term in SEMANTIC_TERMS if term in normalized.lower()]
    return {
        "exact_expected": exact_expected,
        "exact_match": exact_expected is None or normalized == exact_expected,
        "special_token_leaks": special_token_leaks,
        "semantic_terms_observed": semantic_hits,
        "semantic_valid": (
            bool(normalized)
            and not special_token_leaks
            and (
                exact_expected is not None
                or (len(normalized) >= 32 and len(semantic_hits) >= 2)
            )
        ),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def api_key() -> str:
    for name in ("VLLM_HUST_API_KEY", "VLLM_API_KEY", "DIGITAL_TWIN_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    env_path = Path("/home/shuhao/sage-mate/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DIGITAL_TWIN_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("managed Sage Mate API key is required")


def workload(name: str, concurrency: int) -> tuple[list[str], list[float]]:
    if name == "correctness":
        prompts = [
            f"Return exactly this text and nothing else: BIDKV_MATRIX_WARMUP_{index}"
            for index in range(concurrency)
        ]
        return prompts, [0.0] * concurrency
    if name == "homogeneous-long":
        repeats = [700] * concurrency
        delays = [0.0] * concurrency
    elif name == "homogeneous-ultralong":
        repeats = [1500] * concurrency
        delays = [0.0] * concurrency
    elif name == "mixed-length":
        # Keep the aggregate prompt+decode footprint above the 1-GiB lane's
        # measured 55,050-token capacity while preserving a broad length mix.
        # Interleave lengths so the longest request is not also FCFS's tail;
        # otherwise the baseline and utility policies choose it by construction.
        pattern = [1500, 600, 1200, 900]
        repeats = [pattern[index % len(pattern)] for index in range(concurrency)]
        delays = [0.0] * concurrency
    elif name == "mixed-length-ascending-trigger":
        # Regression cell that reliably exposed the requester self-preemption
        # loop in the pre-fix policy. Keep it separate from the interleaved
        # effectiveness workload: ordering is deliberately adversarial here.
        pattern = [400, 650, 850, 1100]
        repeats = [pattern[index % len(pattern)] for index in range(concurrency)]
        delays = [0.0] * concurrency
    elif name == "interactive-batch":
        pattern = [12, 620, 20, 900, 30, 500, 16, 700]
        repeats = [pattern[index % len(pattern)] for index in range(concurrency)]
        delays = [0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 4.0, 4.0][:concurrency]
    elif name == "burst-cancel-recovery":
        pattern = [900, 700, 500, 380]
        repeats = [pattern[index % len(pattern)] for index in range(concurrency)]
        delays = [
            0.0 if index < concurrency // 2 else 2.0 for index in range(concurrency)
        ]
    else:
        raise ValueError(f"unknown workload: {name}")
    prompts = [
        PARAGRAPH * repeat
        + f"\nSynthetic lane {index}; continue with numbered scheduling observations."
        for index, repeat in enumerate(repeats)
    ]
    return prompts, delays


async def request(
    client: httpx.AsyncClient,
    url: str,
    model: str,
    prompt: str,
    index: int,
    delay: float,
    max_tokens: int,
    *,
    exact_expected: str | None = None,
) -> dict[str, object]:
    await asyncio.sleep(delay)
    started = time.perf_counter()
    first: float | None = None
    content: list[str] = []
    usage: dict[str, int] = {}
    status: int | None = None
    error: str | None = None
    cancelled = False
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "seed": 7,
            "max_tokens": max_tokens,
            "ignore_eos": exact_expected is None,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with client.stream("POST", url, json=payload) as response:
            status = response.status_code
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                event = json.loads(raw)
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices", []):
                    text = (choice.get("delta") or {}).get("content") or ""
                    if text:
                        first = first or time.perf_counter()
                        content.append(text)
    except asyncio.CancelledError:
        cancelled = True
    except Exception as exc:  # evidence must retain failures
        error = f"{type(exc).__name__}: {exc}"
    ended = time.perf_counter()
    output = "".join(content)
    validity = output_validity(output, exact_expected)
    completion = int(usage.get("completion_tokens", 0))
    ttft = None if first is None else first - started
    tpot = (
        None
        if ttft is None or completion <= 1
        else (ended - started - ttft) / (completion - 1)
    )
    return {
        "index": index,
        "status_code": status,
        "error": error,
        "cancelled": cancelled,
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": completion,
        "ttft_s": ttft,
        "tpot_s": tpot,
        "latency_s": ended - started,
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_prefix": output[:120],
        "output_text": output,
        **validity,
    }


async def main_async(args: argparse.Namespace) -> dict[str, object]:
    prompts, delays = workload(args.workload, args.concurrency)
    headers = {"Authorization": f"Bearer {api_key()}"}
    url = f"{args.base_url.rstrip('/')}/chat/completions"
    started = time.perf_counter()
    async with httpx.AsyncClient(headers=headers, timeout=None) as client:
        tasks = [
            asyncio.create_task(
                request(
                    client,
                    url,
                    args.model,
                    prompt,
                    index,
                    delays[index],
                    args.max_tokens,
                    exact_expected=(
                        f"BIDKV_MATRIX_WARMUP_{index}"
                        if args.workload == "correctness"
                        else None
                    ),
                )
            )
            for index, prompt in enumerate(prompts)
        ]
        if args.cancel_after_s:
            await asyncio.sleep(args.cancel_after_s)
            for task in tasks[::2]:
                task.cancel()
        results = await asyncio.gather(*tasks)
        recovery = None
        if args.cancel_after_s:
            recovery = await request(
                client,
                url,
                args.model,
                "Return exactly: BIDKV_MATRIX_CANCEL_RECOVERY_OK",
                -1,
                0,
                16,
                exact_expected="BIDKV_MATRIX_CANCEL_RECOVERY_OK",
            )
    wall = time.perf_counter() - started
    completed = [
        item
        for item in results
        if item["status_code"] == 200 and not item["error"] and not item["cancelled"]
    ]
    ttfts = [float(item["ttft_s"]) for item in completed if item["ttft_s"] is not None]
    tpots = [float(item["tpot_s"]) for item in completed if item["tpot_s"] is not None]
    latencies = [float(item["latency_s"]) for item in completed]
    rates = [
        int(item["completion_tokens"]) / float(item["latency_s"]) for item in completed
    ]
    total_completion = sum(int(item["completion_tokens"]) for item in completed)
    slo_completed = [
        item
        for item in completed
        if item["ttft_s"] is not None
        and float(item["ttft_s"]) <= args.slo_ttft_s
        and item["tpot_s"] is not None
        and float(item["tpot_s"]) <= args.slo_tpot_s
        and float(item["latency_s"]) <= args.slo_e2e_s
    ]
    fairness = (
        None
        if not rates or not sum(rate * rate for rate in rates)
        else sum(rates) ** 2 / (len(rates) * sum(rate * rate for rate in rates))
    )
    result: dict[str, object] = {
        "schema": "sage-mate.bidkv-matrix-workload/v1",
        "cell": args.cell,
        "arm": args.arm,
        "workload": args.workload,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "cancel_after_s": args.cancel_after_s,
        "wall_s": wall,
        "completed": len(completed),
        "cancelled": sum(bool(item["cancelled"]) for item in results),
        "failed_or_starved": sum(bool(item["error"]) for item in results),
        "total_prompt_tokens": sum(int(item["prompt_tokens"]) for item in completed),
        "total_completion_tokens": total_completion,
        "output_throughput_tokens_s": total_completion / wall,
        "goodput_requests_s": len(completed) / wall,
        "slo": {
            "ttft_s": args.slo_ttft_s,
            "tpot_s": args.slo_tpot_s,
            "e2e_s": args.slo_e2e_s,
        },
        "slo_goodput_requests_s": len(slo_completed) / wall,
        "jain_output_rate_fairness": fairness,
        "latency_mean_s": statistics.fmean(latencies) if latencies else None,
        "requests": results,
        "recovery": recovery,
    }
    for name, values in (("ttft", ttfts), ("tpot", tpots), ("latency", latencies)):
        for label, fraction in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
            result[f"{name}_{label}_s"] = percentile(values, fraction)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.8-27B")
    parser.add_argument("--cell", required=True)
    parser.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--cancel-after-s", type=float)
    parser.add_argument("--slo-ttft-s", type=float, default=60.0)
    parser.add_argument("--slo-tpot-s", type=float, default=0.2)
    parser.add_argument("--slo-e2e-s", type=float, default=600.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(main_async(args))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"requests"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
