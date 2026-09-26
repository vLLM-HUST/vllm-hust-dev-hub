import pytest

from transfer_receipt import receipt


def test_missing_reset_and_store_only_do_not_claim_restored_cache(tmp_path):
    before, after = tmp_path / "before.prom", tmp_path / "after.prom"

    def write(path, load, store):
        path.write_text(
            f'vllm:kv_offload_load_bytes_total{{engine="0"}} {load}\n'
            f'vllm:kv_offload_store_bytes_total{{engine="0"}} {store}\n'
        )

    write(before, 10, 20)
    write(after, 10, 80)
    assert receipt(before, after)["status"] == "store-only"
    write(after, 15, 80)
    assert receipt(before, after)["load_bytes"] == 5
    write(after, 0, 80)
    with pytest.raises(ValueError, match="reset"):
        receipt(before, after)
    after.write_text("")
    with pytest.raises(ValueError, match="Missing"):
        receipt(before, after)
