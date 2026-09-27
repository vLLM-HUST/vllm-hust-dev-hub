"""Collect a completed Mooncake pair and validate a publication proposal."""
import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REMOTE = '/home/coder/frontier-mods-qwen35-20260925/phase8'
SSH = ['ssh', '-p', '31769', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@223.92.35.180']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output):
    state = dict(passed=False, published=False, stage='waiting')
    def write():
        temp = output / 'status.tmp'
        temp.write_text(json.dumps(state, indent=2) + '\n')
        temp.replace(output / 'status.json')
    try:
        lock = json.loads((output / 'manifest.json').read_text())
        for path, expected in lock['source_sha256'].items():
            if digest(output / path) != expected:
                raise RuntimeError(f'Collector source changed: {path}')
        deadline = time.monotonic() + 6 * 3600
        while True:
            result = subprocess.run(SSH + [f'cat {REMOTE}/receipts/matched-curves-r1/status.json'], capture_output=True, text=True, timeout=30, check=True)
            pair = json.loads(result.stdout)
            state['pair'] = pair
            write()
            if pair.get('error'):
                raise RuntimeError('Pair failed; no performance points exported')
            if pair.get('passed') is True:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Pair did not finish within six hours')
            time.sleep(30)
        state['stage'] = 'collecting'
        write()
        archive = output / 'phase8.tar.gz'
        with archive.open('xb') as stream:
            subprocess.run(SSH + [f"tar -C {REMOTE.rsplit('/', 1)[0]} --exclude='*.sock' --exclude='__pycache__' -czf - phase8"], stdout=stream, check=True, timeout=240)
        state['archive_sha256'] = digest(archive)
        with tarfile.open(archive) as source:
            members = source.getmembers()
            for member in members:
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'phase8' or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected archive member')
            source.extractall(output, members=members)
        state['stage'] = 'validating'
        write()
        windows = [str(output / 'phase8/receipts' / f'{arm}-measured-r1' / f'c{c}') for arm in ('mooncake', 'native') for c in (1, 2, 4, 8, 16)]
        subprocess.run([sys.executable, str(output / 'scripts/frontier_tiering/verify_latency_metrics.py'), *windows, '--output', str(output / 'latency-audit.json')], check=True)
        subprocess.run([sys.executable, str(output / 'scripts/frontier_mooncake/import_results.py'), '--site', str(output / 'site'), '--artifacts', str(output / 'phase8'), '--output', str(output / 'export'), '--evidence-url', 'https://github.com/vLLM-HUST/vllm-hust-website/blob/main/docs/FRONTIER-MOONCAKE-20260926.md', '--artifact-base-url', 'https://vllm-hust.sage.org.ai/reports/frontier-managed-mooncake-20260926'], check=True)
        state.update(passed=True, stage='ready-for-review', published=False)
    except BaseException as exc:
        state.update(stage='failed', error=f'{type(exc).__name__}: {exc}')
        (output / 'FAILED.txt').write_text(state['error'] + '\n')
        raise
    finally:
        write()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output.resolve())
