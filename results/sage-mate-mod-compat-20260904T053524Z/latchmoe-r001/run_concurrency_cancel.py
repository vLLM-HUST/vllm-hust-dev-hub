#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import time
import urllib.request
from pathlib import Path


def request_json(url, model, prompt, max_tokens=24):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.load(response)
        status = response.status
    return {
        "status": status,
        "latency_s": time.perf_counter() - started,
        "text": body["choices"][0]["message"]["content"],
        "finish_reason": body["choices"][0]["finish_reason"],
        "usage": body.get("usage"),
    }


def cancel_after_first_chunk(url, model):
    payload = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": "Write a detailed 1000-word explanation of distributed consensus.",
        }],
        "temperature": 0,
        "max_tokens": 512,
        "stream": True,
    }).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    response = urllib.request.urlopen(request, timeout=300)
    first_data = None
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            first_data = line[6:]
            break
    response.close()
    return {
        "first_chunk_received": first_data is not None,
        "client_closed_after_s": time.perf_counter() - started,
    }


def running_requests(metrics_url):
    with urllib.request.urlopen(metrics_url, timeout=10) as response:
        text = response.read().decode("utf-8")
    total = 0.0
    for line in text.splitlines():
        if line.startswith("vllm:num_requests_running{"):
            total += float(line.rsplit(" ", 1)[1])
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-30B-A3B")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8001/v1/chat/completions"
    )
    args = parser.parse_args()

    prompts = [
        "Compute 11 * 13. Give only the integer.",
        "Compute 17 * 23. Give only the integer.",
        "Name the chemical symbol for gold. Give only the symbol.",
        "Translate distributed systems into Chinese. Give only the translation.",
    ]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        concurrent_results = list(
            executor.map(lambda prompt: request_json(args.url, args.model, prompt), prompts)
        )
    concurrent_wall_s = time.perf_counter() - started

    cancellation = cancel_after_first_chunk(args.url, args.model)
    drain_samples = []
    drain_deadline = time.monotonic() + 30
    while time.monotonic() < drain_deadline:
        running = running_requests("http://127.0.0.1:8001/metrics")
        drain_samples.append({"elapsed_s": 30 - (drain_deadline - time.monotonic()), "running": running})
        if running == 0:
            break
        time.sleep(0.5)
    recovery_prompt = "Reply with exactly: LATCHMOE_R011_RECOVERY_OK"
    recovery = [
        request_json(args.url, args.model, recovery_prompt, max_tokens=24)
        for _ in range(2)
    ]
    result = {
        "concurrency": 4,
        "concurrent_wall_s": concurrent_wall_s,
        "concurrent_results": concurrent_results,
        "cancellation": cancellation,
        "drain_samples": drain_samples,
        "drained": bool(drain_samples and drain_samples[-1]["running"] == 0),
        "recovery": recovery,
        "recovery_identical": recovery[0]["text"] == recovery[1]["text"],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
