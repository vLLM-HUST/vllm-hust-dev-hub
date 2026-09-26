"""Render the complete measured Tiering/Native pair and its evidence links."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CAMPAIGN = "qwen35-managed-tiering-20260926"
ARTIFACTS = "../reports/frontier-managed-tiering-20260926"


def main(site):
    data = json.loads((site / "data/leaderboard_frontier.json").read_text())
    points = [
        p
        for p in data["points"]
        if p["evidence"].get("benchmark_protocol", {}).get("campaign") == CAMPAIGN
    ]
    if len(points) != 10:
        raise ValueError("Render only the complete ten-point matched pair")
    groups = {}
    for arm, mods in (("native", []), ("tiering", ["kv-tiering-migration"])):
        rows = sorted(
            (p for p in points if p["configuration"]["mods"] == mods),
            key=lambda p: p["load"]["concurrency"],
        )
        if [p["load"]["concurrency"] for p in rows] != [1, 2, 4, 8, 16]:
            raise ValueError("Missing or duplicated concurrency observation")
        if any(p["configuration"]["hardware"]["accelerator_count"] != 2 for p in rows):
            raise ValueError("Mismatched serving chip budget")
        groups[arm] = rows
    fig, ax = plt.subplots(figsize=(9, 5.8), layout="constrained")
    for arm, color, marker, offset in (
        ("native", "#2563eb", "o", (5, 8)),
        ("tiering", "#d97706", "^", (5, -14)),
    ):
        rows = groups[arm]
        x = [p["metrics"]["decode_p90_tps"] for p in rows]
        y = [p["metrics"]["output_tps"] / 2 for p in rows]
        ax.plot(
            x,
            y,
            marker=marker,
            color=color,
            label="Native" if arm == "native" else "KV Tiering",
        )
        for p, px, py in zip(rows, x, y):
            ax.annotate(
                f"C{p['load']['concurrency']}",
                (px, py),
                textcoords="offset points",
                xytext=offset,
                color=color,
                fontsize=9,
            )
    ax.set_title("Qwen3.5-35B-A3B BF16 · matched TP2 observations")
    ax.set_xlabel("P90 decode speed (output tokens/s/user)")
    ax.set_ylabel("Output throughput (tokens/s/chip)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.2)
    ax.legend()
    fig.supxlabel(
        "One 900-second observation per point; lines connect measured concurrency levels.",
        fontsize=9,
    )
    for extension in ("svg", "png"):
        fig.savefig(
            site / f"assets/frontier-qwen35-tiering-paired.{extension}", dpi=160
        )
    plt.close(fig)
    lines = [
        "# KV Tiering 同配置对照：Qwen3.5-35B-A3B",
        "",
        "本表和曲线均来自真实在线运行，每点为一次 900 秒观测，未拼接不同窗口的指标。",
        "Native 与 Tiering 使用相同的 Host 修复和运行配置：BF16、TP2、256K 上下文、",
        "APC、MTP2、异步调度、FULL_AND_PIECEWISE、max-seqs 16、batch-tokens 4096，",
        "每卡 KV 预算 26,038,239,232 字节。Tiering 另使用 8 GiB CPU 层及文件存储。",
        "",
        "两组分别通过 26 项检索检查和前缀复用检查，再依次测 C1/2/4/8/16；档位之间不重置缓存。",
        "这不是一般答案质量认证。吞吐仅计正式窗口内 token，传输计数包含在途请求收尾。",
        "一次观测的差异不能证明稳定加速；NPU/CPU 恢复字节也不能单独证明磁盘命中或性能收益。",
        "",
        "![同配置并发曲线](../assets/frontier-qwen35-tiering-paired.svg)",
        "",
        "| 并发 | Native 总吞吐 tok/s | Tiering 总吞吐 tok/s | 吞吐差 | 恢复 MiB | Tiering 传输状态 |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for native, candidate in zip(groups["native"], groups["tiering"]):
        n, c = native["metrics"]["output_tps"], candidate["metrics"]["output_tps"]
        effect = candidate["configuration"]["parameters"]["mod_runtime_effectiveness"]
        label = {
            "store-only": "仅保存",
            "restore-observed": "观察到恢复",
            "not-exercised": "未触发",
        }[effect["status"]]
        lines.append(
            f"| {native['load']['concurrency']} | {n:.2f} | {c:.2f} | {(c / n - 1) * 100:+.2f}% "
            f"| {effect['load_bytes'] / 1024**2:.2f} | {label} |"
        )
    lines += ["", "原始证据：", ""]
    for arm in ("native", "tiering"):
        lines.append(
            f"- {arm}: [运行清单]({ARTIFACTS}/metadata-{arm}.json)、[检索与释放回执]({ARTIFACTS}/{arm}-qualification.json)、[检索原始响应]({ARTIFACTS}/{arm}-retrieval.json.gz)"
        )
        for c in (1, 2, 4, 8, 16):
            lines.append(
                f"- {arm} C{c}: [请求与流式 token 时刻]({ARTIFACTS}/{arm}-c{c}-requests.jsonl.gz)、[计数起点]({ARTIFACTS}/{arm}-c{c}-before.prom)、[计数终点]({ARTIFACTS}/{arm}-c{c}-after.prom)"
            )
    lines += [
        "",
        "指标和原始请求 SHA256 见 [逐点证据](../data/leaderboard_frontier_swe_evidence.json)。",
        "修复来源：[Tiering PR #3](https://github.com/vLLM-HUST/vllm-hust-kv-tiering/pull/3)、",
        "[Host #40](https://github.com/vLLM-HUST/vllm-hust/issues/40)。",
        "",
    ]
    (site / "docs/FRONTIER-KV-TIERING-20260926.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, type=Path)
    main(parser.parse_args().site)
