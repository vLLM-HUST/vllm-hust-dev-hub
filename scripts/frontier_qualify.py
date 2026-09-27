#!/usr/bin/env python3
"""Bounded retrieval gate; these diagnostic requests are not Frontier scores."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import aiohttp
from transformers import AutoTokenizer


async def qualify(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    prefix = tokenizer.encode(
        "Read the record and return its secret phrase exactly.\n"
        "The secret phrase is cobalt-seven-42.\nUnrelated notes:\n",
        add_special_tokens=False,
    )
    filler = tokenizer.encode("The weather is mild today.\n", add_special_tokens=False)
    # Fixed prompt-token shapes preserve exact repeated prefixes for the warm gate.
    suffix = tokenizer.encode(
        "\nWhat is the secret phrase? Reply only with the phrase.",
        add_special_tokens=False,
    )
    template = tokenizer.apply_chat_template(
        [{"role": "user", "content": "FRONTIER_INSERT_HERE"}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    assert template.count("FRONTIER_INSERT_HERE") == 1
    before, after = template.split("FRONTIER_INSERT_HERE")
    prefix = tokenizer.encode(before, add_special_tokens=False) + prefix
    suffix += tokenizer.encode(after, add_special_tokens=False)
    results = []
    stamp = str(time.time_ns())

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=args.timeout)
    ) as session:

        async def request(length, label, salt):
            pad = length - len(prefix) - len(suffix)
            assert pad >= 0
            tokens = prefix + (filler * (pad // len(filler) + 1))[:pad] + suffix
            payload = {
                "model": args.model,
                "prompt": tokens,
                "max_tokens": 48,
                "temperature": 0,
                "cache_salt": salt,
                "return_token_ids": True,
                "stream": False,
            }
            row = {"label": label, "prompt_tokens": length, "passed": False}
            try:
                async with session.post(args.endpoint, json=payload) as response:
                    response.raise_for_status()
                    data = await response.json()
                text = data["choices"][0]["text"].strip()
                row.update(text=text, usage=data.get("usage"), response=data)
                row["passed"] = text.strip("\"' .\n") == "cobalt-seven-42"
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                KeyError,
                ValueError,
            ) as exc:
                row["error"] = str(exc)
            results.append(row)
            (output / f"{label}.json").write_text(json.dumps(row, indent=2) + "\n")
            return row["passed"]

        for length in args.lengths:
            salt = f"frontier-gate-{stamp}-{length}"
            for phase in ("cold", "warm"):
                if not await request(length, f"{phase}-{length}", salt):
                    break
            if not results[-1]["passed"]:
                break
        if all(r["passed"] for r in results):
            await asyncio.gather(
                *[
                    request(1024 + 256 * i, f"concurrent-{i}", f"{stamp}-lane-{i}")
                    for i in range(args.concurrency)
                ]
            )
    expected = 2 * len(args.lengths) + args.concurrency
    summary = {
        "kind": "retrieval-qualification-not-performance",
        "passed": len(results) == expected and all(r["passed"] for r in results),
        "expected_requests": expected,
        "completed_requests": len(results),
        "failed_labels": [r["label"] for r in results if not r["passed"]],
        "thinking": False,
        "scope": "Exact marker retrieval only; not general answer quality or SWE solving",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--lengths", type=int, nargs="+", default=[1024, 8192, 32768, 131072, 262080]
    )
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    if args.concurrency < 1 or any(n < 256 or n > 262080 for n in args.lengths):
        parser.error("Require positive concurrency and prompt lengths in [256, 262080]")
    raise SystemExit(0 if asyncio.run(qualify(args)) else 1)
