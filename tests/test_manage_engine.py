from pathlib import Path
import os
import stat
import subprocess
import sys
import unittest
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_SCRIPT = REPO_ROOT / "manage.sh"
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh"
ENV_EXPORT_SCRIPT = REPO_ROOT / "scripts" / "container_env_exports.py"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "cleanup_vllm_hust_engine.sh"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
README = REPO_ROOT / "README.md"
SMOKE_PROFILE = REPO_ROOT / "profiles" / "smoke-qwen2.5-7b-npu1.env"
ENTRYPOINT_PROBE = REPO_ROOT / "scripts" / "check_optimization_entrypoint.py"
OPTIMIZATION_INSTALLER = REPO_ROOT / "scripts" / "prepare_optimization_plugin.py"
OPTIMIZATION_PLUGIN_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "optimization_plugins"
NPU_FAILURE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "npu_allocating_failure.py"
OPTIMIZATION_MANIFEST_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "optimization_manifests" / "bidkv.json"
)


class ManageEngineGuardTests(unittest.TestCase):
    def test_managed_bidkv_apply_disable_restore_rewrites_complete_environment(
        self,
    ) -> None:
        """Exercise the actual manage.sh -> unit env -> container allowlist chain."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            systemctl = bin_dir / "systemctl"
            systemctl.write_text("#!/usr/bin/env bash\nexit 0\n")
            systemctl.chmod(0o755)
            manifest = root / "workspace" / "vllm-hust-bidkv" / ".vllm-hust" / "optimization.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(OPTIMIZATION_MANIFEST_FIXTURE.read_text())
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "XDG_CONFIG_HOME": str(root / "xdg"),
                    "VLLM_ENGINE_SYSTEMD_UNIT": "bidkv-managed-test.service",
                    "VLLM_OPTIMIZATION_WORKSPACE_ROOT": str(root / "workspace"),
                }
            )

            applied = subprocess.run(
                [str(MANAGE_SCRIPT), "start", "--optimization", "bidkv"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            unit_env = root / "xdg/systemd/user/bidkv-managed-test.service.env"
            applied_environment = unit_env.read_text()
            self.assertIn("BIDKV_UTILITY_ENABLE=1", applied_environment)
            self.assertIn("BIDKV_UTILITY_STRATEGY=bidkv", applied_environment)
            self.assertIn(
                "VLLM_ENGINE_EXTRA_ENV_PREFIXES=BIDKV_UTILITY_", applied_environment
            )
            self.assertIn("VLLM_ENGINE_EXTRA_ARGS_JSON=", applied_environment)

            exported = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"set -a; source {unit_env}; set +a; exec {sys.executable} {ENV_EXPORT_SCRIPT}",
                ],
                cwd=REPO_ROOT,
                env={"PATH": env["PATH"]},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertIn("export BIDKV_UTILITY_ENABLE=1", exported.stdout)

            restored = subprocess.run(
                [str(MANAGE_SCRIPT), "restart"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            restored_environment = unit_env.read_text()
            self.assertNotIn("BIDKV_UTILITY_", restored_environment)
            self.assertNotIn("--preemption-policy", restored_environment)

    def test_management_scripts_are_executable_and_syntax_valid(self) -> None:
        for script in (MANAGE_SCRIPT, ENGINE_SCRIPT, CLEANUP_SCRIPT):
            mode = script.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{script} should be executable")
            subprocess.run(["bash", "-n", str(script)], check=True)

    def test_generated_unit_cleans_container_before_process_only_kill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            systemctl = bin_dir / "systemctl"
            systemctl.write_text("#!/usr/bin/env bash\nexit 0\n")
            systemctl.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "XDG_CONFIG_HOME": str(root / "xdg"),
                    "VLLM_ENGINE_SYSTEMD_UNIT": "shutdown-contract.service",
                }
            )

            installed = subprocess.run(
                [str(MANAGE_SCRIPT), "install"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            unit_text = (
                root / "xdg/systemd/user/shutdown-contract.service"
            ).read_text()

            self.assertIn(f"ExecStop={CLEANUP_SCRIPT}", unit_text)
            self.assertIn("KillMode=process", unit_text)
            self.assertNotIn("KillMode=control-group", unit_text)
            self.assertLess(unit_text.index("ExecStop="), unit_text.index("KillMode="))

    def test_legacy_ascend_environment_is_default_off_and_explicit(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn(
            'legacy_ascend_env="${VLLM_ENGINE_ENABLE_LEGACY_ASCEND_ENV:-0}"',
            script,
        )
        self.assertIn(
            "unset VLLM_ASCEND_ENABLE_FLASHCOMM1 VLLM_ASCEND_ENABLE_FUSED_MC2",
            script,
        )
        self.assertIn('if [[ "__ENABLE_LEGACY_ASCEND_ENV__" == "1" ]]', script)
        self.assertNotIn(
            'flashcomm1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-0}"', script
        )
        self.assertNotIn(
            'fused_mc2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-1}"', script
        )

    def test_cleanup_error_documents_canonical_and_legacy_variables(self) -> None:
        script = CLEANUP_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_CONTAINER_NAME", script)
        self.assertIn(
            "legacy fallbacks: VLLM_ENGINE_CONTAINER or DOCKER_CONTAINER", script
        )
        self.assertIn("VLLM_ENGINE_PORT or PORT", script)

    def test_empty_api_key_fails_before_docker_access(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_ENGINE_CONTAINER": "dummy-container",
                "VLLM_HUST_API_KEY": "EMPTY",
            }
        )
        result = subprocess.run(
            [str(ENGINE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("real API key", result.stderr)
        self.assertNotIn("Docker container", result.stderr)

    def test_required_prefix_cache_rejects_disabled_configuration_before_docker(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_ENGINE_CONTAINER": "dummy-container",
                "VLLM_HUST_API_KEY": "test-only-key",
                "VLLM_ENGINE_MODEL_PATH": "/tmp/test-model",
                "VLLM_ENGINE_ENABLE_PREFIX_CACHING": "0",
                "VLLM_ENGINE_REQUIRE_PREFIX_CACHING": "1",
            }
        )
        result = subprocess.run(
            [str(ENGINE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("prefix caching is required", result.stderr)
        self.assertNotIn("Docker container", result.stderr)

    def test_engine_credentials_never_enter_process_arguments(self) -> None:
        launcher = ENGINE_SCRIPT.read_text()
        manager = (REPO_ROOT / "scripts" / "manage-container.sh").read_text()

        self.assertNotIn('--api-key "__API_KEY__"', launcher)
        self.assertNotIn('replace "__API_KEY__"', launcher)
        self.assertIn('export VLLM_API_KEY="$api_key"', launcher)
        self.assertIn("--env VLLM_API_KEY", launcher)

        build_args = manager.split("build_vllm_args()", 1)[1].split(
            "export_engine_env()", 1
        )[0]
        self.assertNotIn("--api-key", build_args)
        self.assertIn('export VLLM_API_KEY="$API_KEY"', manager)

    def test_env_template_exposes_host_managed_docker_knobs(self) -> None:
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_ENGINE_CONTAINER_NAME=vllm-ascend-dev", template)
        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER=true", template)
        self.assertIn(
            "VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env", template
        )
        self.assertIn(
            "VLLM_ENGINE_IMAGE=quay.io/ascend/vllm-ascend:v0.23.0-openeuler", template
        )
        self.assertIn("VLLM_ENGINE_NPU_DEVICES=0,1,2,3", template)
        self.assertIn(
            "VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python", template
        )
        self.assertIn("Leave VLLM_ENGINE_CONDA_ENV unset", template)
        self.assertIn("COMPILE_CUSTOM_KERNELS=0", template)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", template)
        self.assertIn("VLLM_PLUGINS=ascend,ascend_kv_connector,ascend_model", template)
        self.assertIn("VLLM_ENGINE_BASE_PYTHONPATH", template)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", template)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", template)
        self.assertIn("VLLM_OPTIMIZATION_ENTRYPOINT_GROUP", template)
        self.assertIn("VLLM_OPTIMIZATION_AUTO_INSTALL", template)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", template)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", template)
        self.assertIn("VLLM_ENGINE_INHERIT_PYTHONPATH=0", template)
        self.assertIn("VLLM_ENGINE_INSTALLED_MODULES_JSON={}", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", template)
        self.assertIn("VLLM_ENGINE_CONTAINER_HOME", template)
        self.assertIn("VLLM_ENGINE_KV_CACHE_DTYPE", template)
        self.assertIn("VLLM_ENGINE_KV_CACHE_MEMORY_BYTES", template)
        self.assertIn("VLLM_ENGINE_ENABLE_PREFIX_CACHING=1", template)
        self.assertIn("VLLM_ENGINE_REQUIRE_PREFIX_CACHING=1", template)

    def test_readme_documents_one_command_management(self) -> None:
        readme = README.read_text()

        self.assertIn("./manage.sh start", readme)
        self.assertIn("./manage.sh restart", readme)
        self.assertIn("VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env", readme)
        self.assertIn("scripts/run_vllm_hust_engine.sh", readme)
        self.assertIn("pulls/creates it automatically", readme)

    def test_engine_launcher_bootstraps_missing_container(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER", script)
        self.assertIn("scripts/ascend-official-container.sh", script)
        self.assertIn("VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE", script)
        self.assertIn("EnvironmentFile=-", MANAGE_SCRIPT.read_text())
        self.assertIn("write_unit_environment", MANAGE_SCRIPT.read_text())
        self.assertIn('"KEY"', MANAGE_SCRIPT.read_text())
        self.assertIn("v0.23.0-openeuler", script)
        self.assertIn("official image's native Python/CANN runtime", script)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", script)
        self.assertIn("--kv-cache-dtype", script)
        self.assertIn("--kv-cache-memory-bytes", script)
        self.assertIn("VLLM_ENGINE_CONTAINER_LOG_FILE", script)
        self.assertIn("ascend_model_loader", script)

    def test_compile_cache_is_namespaced_by_runtime_identity(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_CACHE_NAMESPACE", script)
        self.assertIn('cache_namespace="image-${expected_image_id#sha256:}"', script)
        self.assertIn(
            'VLLM_CACHE_ROOT="$HOME/.cache/vllm/__CACHE_NAMESPACE__"',
            script,
        )
        self.assertIn('replace "__CACHE_NAMESPACE__" "$cache_namespace"', script)
        self.assertIn("tee -a", script)
        self.assertIn("<redacted>", script)
        self.assertIn("__EXTRA_ENV_EXPORTS__", script)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", script)
        self.assertIn("torch_npu_preflight", script)
        self.assertNotIn(
            'HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"', script
        )
        manage = MANAGE_SCRIPT.read_text()
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", manage)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", manage)
        env_exporter = ENV_EXPORT_SCRIPT.read_text()
        self.assertIn('"VLLM_ASCEND_ENABLE_MLAPO"', env_exporter)
        self.assertIn('"VLLM_ASCEND_KV_CACHE_FREE_MEMORY_FRACTION"', env_exporter)
        self.assertIn('"VLLM_ENGINE_CONTAINER_HOME"', env_exporter)
        self.assertIn("VLLM_ENGINE_ENV_FILE", manage)
        self.assertIn("VLLM_OPTIMIZATION_", manage)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", manage)
        self.assertIn("VLLM_ENGINE_PYTHON", manage)
        self.assertLess(
            manage.index('load_dotenv "$repo_root/.env"'),
            manage.index('unit_name="${VLLM_ENGINE_SYSTEMD_UNIT'),
        )

    def test_engine_launcher_can_skip_repo_env(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_LOAD_REPO_ENV", script)
        self.assertIn('load_dotenv "$repo_root/.env"', script)

    def test_container_runtime_can_keep_alive_without_ssh_env(self) -> None:
        runtime = (REPO_ROOT / "scripts" / "ascend-container-runtime.sh").read_text()

        self.assertIn("CONTAINER_SSH_USER:=shuhao", runtime)
        self.assertNotIn("CONTAINER_SSH_USER:?Error", runtime)

    def test_engine_launcher_stays_repo_agnostic(self) -> None:
        script = ENGINE_SCRIPT.read_text()
        manage = MANAGE_SCRIPT.read_text()
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_PLUGINS", script)
        self.assertIn("ENGINE_PYTHON", script)
        self.assertIn('"$ENGINE_PYTHON"', script)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", script)
        self.assertIn("VLLM_ENGINE_INHERIT_PYTHONPATH", script)
        self.assertIn("reject_engine_sources=True", script)
        self.assertIn("has no declared source root in PYTHONPATH", script)
        self.assertIn("no installed-distribution contract", script)
        self.assertIn("distribution.files", script)
        self.assertIn("actual_version != expected_version", script)
        self.assertIn("unset VLLM_ENGINE_INSTALLED_MODULES_JSON", script)
        self.assertIn("imported from {origin}, expected {expected_root}", script)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", script)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", script)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", script)
        for text in (script, manage, template):
            self.assertNotIn("segment_reuse", text)
            self.assertNotIn("SEGMENT_REUSE", text)

    def test_engine_launcher_has_no_hard_coded_model_default(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_MODEL_PATH or MODEL_ID must be set", script)
        self.assertNotIn(
            'model_path="${VLLM_ENGINE_MODEL_PATH:-${MODEL_ID:-/data/shared_models',
            script,
        )

    def test_smoke_profile_is_non_secret_and_single_npu(self) -> None:
        profile = SMOKE_PROFILE.read_text()

        self.assertIn("VLLM_ENGINE_NPU_DEVICES=1", profile)
        self.assertIn(
            "VLLM_ENGINE_MODEL_PATH=/data/shared_models/Qwen2.5-7B-Instruct",
            profile,
        )
        self.assertIn("VLLM_PLUGINS=ascend", profile)
        self.assertNotIn("VLLM_HUST_API_KEY", profile)
        self.assertNotIn("TOKEN=", profile)
        self.assertNotIn("SECRET=", profile)

    def test_engine_launcher_has_generic_optimization_repo_overlay(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("optimization_repo_container", script)
        self.assertIn("optimization_src_subdir", script)
        self.assertIn("optimization_entrypoint_group", script)
        self.assertIn("optimization_plugin_installed", script)
        self.assertIn("prepare_optimization_plugin.py", OPTIMIZATION_INSTALLER.name)
        self.assertIn("OPTIMIZATION_INSTALL_TARGET", script)
        self.assertIn("cleanup_optimization_install", script)
        self.assertIn("cleanup_container_launch", script)
        self.assertIn("optimization_source_snapshot", script)
        self.assertIn('export PYTHONPATH="$OPTIMIZATION_INSTALL_DIR', script)
        self.assertIn("installation did not register", script)
        self.assertIn("engine_base_pythonpath", script)
        self.assertIn('plugins="ascend,${plugins}"', script)
        self.assertIn('plugins="${plugins},${optimization_plugin}"', script)
        self.assertIn('[[ ",$plugins," != *",$optimization_plugin,"* ]]', script)

    def test_npu_failure_fixture_is_explicit_and_bounded(self) -> None:
        fixture = NPU_FAILURE_FIXTURE.read_text()

        self.assertIn("VLLM_TEST_NPU_ALLOCATION_READY", fixture)
        self.assertIn("VLLM_TEST_NPU_ALLOCATION_MIB", fixture)
        self.assertIn("VLLM_TEST_NPU_HOLD_SECONDS", fixture)
        self.assertIn("raise SystemExit(42)", fixture)

    def test_entrypoint_probe_matches_exact_group_and_name(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(OPTIMIZATION_PLUGIN_FIXTURE)

        for group, name in (
            ("vllm.general_plugins", "sample_general"),
            ("vllm.victim_selector", "sample_selector"),
        ):
            result = subprocess.run(
                [sys.executable, str(ENTRYPOINT_PROBE), group, name],
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"missing {group}:{name}")

        for group, name in (
            ("vllm.general_plugins", "sample_selector"),
            ("vllm.victim_selector", "sample_general"),
            ("vllm.victim_selector", "missing"),
        ):
            result = subprocess.run(
                [sys.executable, str(ENTRYPOINT_PROBE), group, name],
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 1, f"unexpected {group}:{name}")


if __name__ == "__main__":
    unittest.main()
