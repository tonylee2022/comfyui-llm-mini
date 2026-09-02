from __future__ import annotations

import base64
import configparser
import importlib
import io
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import llama_cpp
from core import llama_cpp_install
from core import media
import install as install_hook
import llama_cpp_setup


TEST_PACKAGE = "llama_cpp_provider_test_package"
test_package = types.ModuleType(TEST_PACKAGE)
test_package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules.setdefault(TEST_PACKAGE, test_package)
openai_compatible = importlib.import_module(f"{TEST_PACKAGE}.providers.openai_compatible")


class LlamaCppSetupTests(unittest.TestCase):
    def test_pinned_release_assets_match_tag(self):
        self.assertEqual(llama_cpp_setup.LLAMA_CPP_TAG, "b10753")
        self.assertEqual(llama_cpp_setup.LLAMA_CPP_COMMIT, "69320fef12d3385dcf9ca45db4dcf7eec21d5f71")
        for assets in llama_cpp_setup.ASSETS.values():
            for asset in assets:
                if asset.filename.startswith("llama-b"):
                    self.assertIn(f"llama-{llama_cpp_setup.LLAMA_CPP_TAG}-", asset.filename)
                self.assertRegex(asset.sha256, r"^[0-9a-f]{64}$")

    def test_auto_cuda_requires_driver_and_toolkit(self):
        check = {
            "nvidia_driver": True,
            "nvidia_smi": "/usr/bin/nvidia-smi",
            "nvcc": "",
            "cuda_toolkit": "",
        }
        with patch.object(llama_cpp, "environment_check", return_value=check):
            result = llama_cpp.install_help("auto", "bash", "master")
        self.assertEqual(result["backend"], "cuda")
        self.assertTrue(result["warnings"])
        self.assertIn("-DGGML_CUDA=ON", result["commands"][3])
        self.assertTrue(result["config_examples"])

    def test_cpu_install_help_uses_official_clone_and_standard_cmake(self):
        with patch.object(llama_cpp, "environment_check", return_value={"nvidia_driver": False, "nvcc": "", "cuda_toolkit": ""}):
            result = llama_cpp.install_help("cpu", "bash", "b1234")
        self.assertEqual(result["commands"][0], "git clone https://github.com/ggml-org/llama.cpp.git")
        self.assertEqual(result["commands"][3], "cmake -B build")
        self.assertNotIn("GGML_CUDA", "\n".join(result["commands"]))

    def test_ref_rejects_shell_control_characters(self):
        with self.assertRaises(ValueError):
            llama_cpp.install_help("cpu", "bash", "master; touch bad")

    def test_cli_only_prints_returned_commands(self):
        result = {
            "backend": "cpu", "shell": "bash", "ref": "master", "warnings": [],
            "commands": ["safe command"], "private_install_commands": ["private command"], "config_examples": ["[llama_cpp]"], "note": "display only",
        }
        with (
            patch.object(sys, "argv", ["llama_cpp_setup.py", "print-install"]),
            patch.object(llama_cpp_setup, "install_help", return_value=result),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(llama_cpp_setup.main(), 0)
        self.assertIn("safe command", stdout.getvalue())

    def test_private_install_dry_run_does_not_download(self):
        with (
            patch.object(llama_cpp_setup, "_select_backend", return_value="cpu"),
            patch.object(llama_cpp_setup, "_asset_key", return_value="windows-cpu"),
            patch.object(llama_cpp_setup, "_download") as download,
        ):
            result = llama_cpp_setup.install_runtime("auto", False, False, True, 4)
        self.assertEqual(result["backend"], "cpu")
        download.assert_not_called()

    def test_windows_auto_uses_cuda_release_and_blackwell_package(self):
        check = {"nvidia_driver": True, "gpu_info": "NVIDIA GeForce RTX 5090, 12.0"}
        with (
            patch.object(llama_cpp_setup.platform, "system", return_value="Windows"),
            patch.object(llama_cpp_setup, "_architecture", return_value="x86_64"),
            patch.object(llama_cpp_setup, "environment_check", return_value=check),
        ):
            backend = llama_cpp_setup._select_backend("auto")
            asset_key = llama_cpp_setup._asset_key(backend)
        self.assertEqual(backend, "cuda")
        self.assertEqual(asset_key, "windows-cuda13")

    def test_linux_auto_with_cuda_toolkit_selects_pinned_source(self):
        check = {"nvidia_driver": True, "nvcc": "/usr/local/cuda/bin/nvcc"}
        with (
            patch.object(llama_cpp_setup.platform, "system", return_value="Linux"),
            patch.object(llama_cpp_setup, "environment_check", return_value=check),
        ):
            result = llama_cpp_setup.install_runtime("auto", False, False, True, 4)
        self.assertEqual(result["backend"], "cuda")
        self.assertEqual(result["source"], "pinned-source")

    def test_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(RuntimeError):
                llama_cpp_setup._safe_destination(Path(temp_dir), "../outside")


class LlamaCppSettingsTests(unittest.TestCase):
    def test_runtime_paths_must_be_absolute(self):
        config = configparser.ConfigParser()
        with (
            patch.object(llama_cpp, "load_ini", return_value=config),
            patch.object(llama_cpp, "save_ini"),
            self.assertRaisesRegex(ValueError, "absolute path"),
        ):
            llama_cpp.save_llama_cpp_settings({"executable": "bin/llama-server"})

    def test_private_runtime_uses_relative_config_and_precedes_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = root / "installed" / "bin" / "llama-server"
            server.parent.mkdir(parents=True)
            server.write_text("binary", encoding="utf-8")
            server.chmod(0o755)
            config = root / "runtime_config.json"
            config.write_text(json.dumps({
                "schema_version": 1,
                "executable": "installed/bin/llama-server",
                "library_dirs": ["installed/bin"],
            }), encoding="utf-8")
            with (
                patch.object(llama_cpp, "PRIVATE_RUNTIME_ROOT", root),
                patch.object(llama_cpp, "PRIVATE_RUNTIME_CONFIG", config),
                patch.object(llama_cpp.shutil, "which", return_value="/path/llama-server"),
            ):
                result = llama_cpp.resolve_llama_server_spec(llama_cpp.LlamaCppSettings())
        self.assertEqual(result.source, "private")
        self.assertEqual(result.path, server)

    def test_invalid_configured_executable_falls_back_to_private_discovery(self):
        private = llama_cpp.LlamaCppExecutable(Path("/private/llama-server"), "private")
        with patch.object(llama_cpp, "_private_runtime_spec", return_value=private):
            result = llama_cpp.resolve_llama_server_spec(llama_cpp.LlamaCppSettings(executable="/missing/server"))
        self.assertEqual(result, private)

    def test_model_config_round_trip_and_empty_config_resets(self):
        config = configparser.ConfigParser()
        with patch.object(llama_cpp, "load_ini", return_value=config), patch.object(llama_cpp, "save_ini"):
            saved = llama_cpp.save_llama_cpp_model_config("Qwen/VL", {
                "context_size": "65536",
                "image_max_tokens": "512",
                "flash_attn": "on",
                "cache_type_k": "q8_0",
                "supports_image": "enabled",
                "supports_video": "enabled",
                "advanced": "rope-scaling = yarn",
            })
            self.assertEqual(saved["context_size"], 65536)
            self.assertEqual(saved["image_max_tokens"], 512)
            self.assertEqual(saved["supports_video"], "enabled")
            self.assertEqual(llama_cpp.load_llama_cpp_model_configs()["Qwen/VL"]["flash_attn"], "on")
            llama_cpp.save_llama_cpp_model_config("Qwen/VL", {})
            self.assertEqual(llama_cpp.load_llama_cpp_model_configs(), {})

    def test_model_config_rejects_router_and_duplicate_advanced_parameters(self):
        with self.assertRaisesRegex(ValueError, "cannot be overridden"):
            llama_cpp.normalize_llama_cpp_model_config({"advanced": "host = 0.0.0.0"})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            llama_cpp.normalize_llama_cpp_model_config({"advanced": "rope-scale = 2\nrope-scale = 3"})
        with self.assertRaisesRegex(ValueError, "supports_video"):
            llama_cpp.normalize_llama_cpp_model_config({"supports_video": "maybe"})

    def test_model_preset_uses_global_defaults_and_model_overrides(self):
        config = configparser.ConfigParser()
        config.add_section("llama_cpp")
        config["llama_cpp"][llama_cpp.MODEL_CONFIGS_OPTION] = json.dumps({
            "vision-model": {"context_size": 65536, "n_gpu_layers": 80, "flash_attn": "auto"}
        })
        settings = llama_cpp.LlamaCppSettings(context_size=32768, n_gpu_layers=999)
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(llama_cpp, "load_ini", return_value=config),
                patch.object(llama_cpp, "MODEL_PRESET_PATH", Path(temp_dir) / "models-preset.ini"),
            ):
                path = llama_cpp.write_llama_cpp_model_preset(settings)
                preset = path.read_text(encoding="utf-8")
        self.assertIn("[*]\nctx-size = 32768\nn-gpu-layers = 999", preset)
        self.assertIn("[vision-model]\nctx-size = 65536\nn-gpu-layers = 80\nflash-attn = auto", preset)

    def test_modality_overrides_take_precedence_and_are_not_server_arguments(self):
        record = {"id": "vision-model", "architecture": {"input_modalities": ["text", "image"]}}
        configs = {"vision-model": {"supports_image": "disabled", "supports_video": "enabled"}}
        self.assertEqual(
            llama_cpp.effective_model_input_modalities("vision-model", record, configs),
            ["text", "video"],
        )
        config = configparser.ConfigParser()
        config.add_section("llama_cpp")
        config["llama_cpp"][llama_cpp.MODEL_CONFIGS_OPTION] = json.dumps(configs)
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(llama_cpp, "load_ini", return_value=config),
                patch.object(llama_cpp, "MODEL_PRESET_PATH", Path(temp_dir) / "models-preset.ini"),
            ):
                preset = llama_cpp.write_llama_cpp_model_preset().read_text(encoding="utf-8")
        self.assertNotIn("supports-image", preset)
        self.assertNotIn("supports-video", preset)


class FakeRuntime(llama_cpp.LlamaCppRuntime):
    def __init__(self, visual: bool = True, video: bool = False):
        super().__init__()
        self.visual = visual
        self.video = video
        self.loaded = []
        self.unloaded = []

    def _model(self, model: str, reload: bool = False):
        modalities = ["text"]
        if self.visual:
            modalities.append("image")
        if self.video:
            modalities.append("video")
        return {"id": model, "status": {"value": "unloaded"}, "architecture": {"input_modalities": modalities}}

    def load_model(self, model: str, memory_policy: str | None = None):
        self.loaded.append(model)
        return self._model(model)

    def unload_model(self, model: str, manual: bool = True):
        if manual and self._active.get(model, 0):
            raise llama_cpp.LlamaCppConflictError("active")
        self.unloaded.append(model)

    @property
    def base_url(self):
        return "http://127.0.0.1:12345/"


class LlamaCppLifecycleTests(unittest.TestCase):
    def test_after_run_unloads_when_request_count_returns_to_zero(self):
        runtime = FakeRuntime()
        with runtime.model_session("model", "after_run") as (base_url, token):
            self.assertEqual(runtime._active["model"], 1)
            self.assertTrue(base_url.endswith("/v1/"))
            with self.assertRaises(llama_cpp.LlamaCppConflictError):
                runtime.unload_model("model", manual=True)
        self.assertEqual(runtime.unloaded, ["model"])
        self.assertNotIn("model", runtime._active)

    def test_keep_warm_does_not_unload(self):
        runtime = FakeRuntime()
        with runtime.model_session("model", "keep_warm"):
            pass
        self.assertEqual(runtime.unloaded, [])

    def test_concurrent_sessions_only_unload_after_last_request(self):
        runtime = FakeRuntime()
        with runtime.model_session("model", "after_run"):
            with runtime.model_session("model", "after_run"):
                self.assertEqual(runtime._active["model"], 2)
            self.assertEqual(runtime.unloaded, [])
        self.assertEqual(runtime.unloaded, ["model"])

    def test_after_run_policy_is_honored_when_keep_warm_finishes_last(self):
        runtime = FakeRuntime()
        after_run = runtime.model_session("model", "after_run")
        keep_warm = runtime.model_session("model", "keep_warm")
        after_run.__enter__()
        keep_warm.__enter__()
        after_run.__exit__(None, None, None)
        self.assertEqual(runtime.unloaded, [])
        keep_warm.__exit__(None, None, None)
        self.assertEqual(runtime.unloaded, ["model"])

    def test_idle_policy_schedules_unload(self):
        runtime = FakeRuntime()
        settings = llama_cpp.LlamaCppSettings(idle_unload_seconds=0.01)
        with patch.object(llama_cpp, "llama_cpp_settings", return_value=settings):
            with runtime.model_session("model", "idle"):
                pass
            time.sleep(0.05)
        self.assertEqual(runtime.unloaded, ["model"])

    def test_non_visual_model_rejects_image_before_loading(self):
        runtime = FakeRuntime(visual=False)
        with self.assertRaisesRegex(llama_cpp.LlamaCppError, "does not advertise image"):
            with runtime.model_session("text-only", "after_run", has_images=True):
                pass
        self.assertEqual(runtime.loaded, [])

    def test_model_without_video_modality_rejects_video_before_loading(self):
        runtime = FakeRuntime(visual=True, video=False)
        with self.assertRaisesRegex(llama_cpp.LlamaCppError, "does not advertise video"):
            with runtime.model_session("image-only", "after_run", has_video=True):
                pass
        self.assertEqual(runtime.loaded, [])

    def test_video_model_accepts_video_session(self):
        runtime = FakeRuntime(visual=True, video=True)
        with runtime.model_session("video-model", "after_run", has_video=True):
            pass
        self.assertEqual(runtime.loaded, ["video-model"])

    def test_start_uses_argument_array_and_new_process_group(self):
        runtime = llama_cpp.LlamaCppRuntime()
        settings = llama_cpp.LlamaCppSettings(models_dir="/tmp/models")
        process = Mock()
        process.pid = 123
        process.poll.return_value = None
        process.stdout = []
        with (
            patch.object(llama_cpp, "llama_cpp_settings", return_value=settings),
            patch.object(runtime, "_validate_start", return_value=(llama_cpp.LlamaCppExecutable(Path("/tmp/llama-server"), "configured", (Path("/tmp"),)), "--models-dir --models-max --models-preset --fit")),
            patch.object(llama_cpp, "write_llama_cpp_model_preset", return_value=Path("/tmp/models-preset.ini")),
            patch.object(runtime, "_free_port", return_value=43210),
            patch.object(runtime, "status", return_value={"running": True}),
            patch.object(llama_cpp, "check_interrupted"),
            patch.object(llama_cpp.subprocess, "Popen", return_value=process) as popen,
            patch.object(
                llama_cpp.requests,
                "get",
                return_value=Mock(status_code=200, json=Mock(return_value={"data": []})),
            ),
        ):
            self.assertTrue(runtime.start()["running"])
        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("--api-key", args[0])
        self.assertNotIn("--ctx-size", args[0])
        self.assertNotIn("--n-gpu-layers", args[0])
        self.assertEqual(args[0][args[0].index("--models-preset") + 1], "/tmp/models-preset.ini")
        self.assertTrue(kwargs["env"]["LLAMA_API_KEY"])
        self.assertNotIn("shell", kwargs)
        if llama_cpp.os.name != "nt":
            self.assertTrue(kwargs["start_new_session"])

    def test_maintenance_rejects_active_requests_and_blocks_start(self):
        runtime = llama_cpp.LlamaCppRuntime()
        runtime._active["model"] = 1
        with self.assertRaises(llama_cpp.LlamaCppConflictError):
            runtime.begin_maintenance()
        runtime._active.clear()
        runtime.begin_maintenance()
        try:
            with self.assertRaises(llama_cpp.LlamaCppConflictError):
                runtime.start()
        finally:
            runtime.end_maintenance()


class LlamaCppInstallManagerTests(unittest.TestCase):
    class FakeRuntime:
        def __init__(self, conflict: bool = False):
            self.conflict = conflict
            self.maintenance = False
            self.stopped = False

        def begin_maintenance(self):
            if self.conflict:
                raise llama_cpp.LlamaCppConflictError("active")
            self.maintenance = True

        def stop(self):
            self.stopped = True

        def end_maintenance(self):
            self.maintenance = False

    def test_active_request_conflict_is_returned_before_thread_starts(self):
        manager = llama_cpp_install.LlamaCppInstallManager()
        runtime = self.FakeRuntime(conflict=True)
        plan = {"backend": "cpu", "source": "official-release", "runtime_dir": "/runtime", "tag": "b1"}
        with (
            patch.object(manager, "plan", return_value=plan),
            patch.object(llama_cpp_install, "RUNTIME", runtime),
            self.assertRaises(llama_cpp.LlamaCppConflictError),
        ):
            manager.start("auto")
        self.assertIsNone(manager._thread)

    def test_async_install_reports_progress_and_success(self):
        manager = llama_cpp_install.LlamaCppInstallManager()
        runtime = self.FakeRuntime()
        plan = {"backend": "cpu", "source": "official-release", "runtime_dir": "/runtime", "tag": "b1"}

        def install_runtime(backend, offline, force, dry_run, jobs, progress=None):
            progress("validating", "validating")
            return {"backend": "cpu", "executable": "/runtime/llama-server"}

        with (
            patch.object(manager, "plan", return_value=plan),
            patch.object(llama_cpp_install, "RUNTIME", runtime),
            patch.object(llama_cpp_install.llama_cpp_setup, "install_runtime", side_effect=install_runtime),
            patch.object(llama_cpp_install, "_private_runtime_metadata", return_value={"tag": "b1"}),
        ):
            manager.start("auto")
            manager._thread.join(timeout=2)
        state = manager.status()
        self.assertEqual(state["state"], "succeeded")
        self.assertEqual(state["phase"], "complete")
        self.assertTrue(runtime.stopped)
        self.assertFalse(runtime.maintenance)

    def test_failed_install_redacts_credentials_and_releases_maintenance(self):
        manager = llama_cpp_install.LlamaCppInstallManager()
        runtime = self.FakeRuntime()
        plan = {"backend": "cpu", "source": "official-release", "runtime_dir": "/runtime", "tag": "b1"}
        with (
            patch.object(manager, "plan", return_value=plan),
            patch.object(llama_cpp_install, "RUNTIME", runtime),
            patch.object(
                llama_cpp_install.llama_cpp_setup,
                "install_runtime",
                side_effect=RuntimeError("token=secret-value build failed"),
            ),
        ):
            manager.start("auto")
            manager._thread.join(timeout=2)
        state = manager.status()
        self.assertEqual(state["state"], "failed")
        self.assertNotIn("secret-value", state["error"])
        self.assertFalse(runtime.maintenance)


class InstallHookTests(unittest.TestCase):
    def test_first_install_failure_does_not_block_manager(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(install_hook, "PRIVATE_RUNTIME_ROOT", root),
                patch.object(install_hook.llama_cpp_setup, "install_runtime", side_effect=RuntimeError("offline")) as install_runtime,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                self.assertEqual(install_hook.main(), 0)
            install_runtime.assert_called_once()
            self.assertIn("不会阻止节点安装", stdout.getvalue())

    def test_existing_private_runtime_skips_first_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "installed").mkdir()
            with (
                patch.object(install_hook, "PRIVATE_RUNTIME_ROOT", root),
                patch.object(install_hook.llama_cpp_setup, "install_runtime") as install_runtime,
            ):
                self.assertEqual(install_hook.main(), 0)
            install_runtime.assert_not_called()


class LlamaCppMemoryPolicyTests(unittest.TestCase):
    def _modules(self, free_bytes: int):
        torch_module = types.ModuleType("torch")
        torch_module.cuda = Mock()
        torch_module.cuda.is_available.return_value = True
        torch_module.cuda.mem_get_info.return_value = (free_bytes, free_bytes)
        comfy_module = types.ModuleType("comfy")
        comfy_module.__path__ = []
        management = types.ModuleType("comfy.model_management")
        management.unload_all_models = Mock()
        management.soft_empty_cache = Mock()
        return {"torch": torch_module, "comfy": comfy_module, "comfy.model_management": management}, management

    def test_auto_releases_comfy_models_when_estimate_exceeds_free_vram(self):
        runtime = llama_cpp.LlamaCppRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            model = Path(temp_dir) / "model.gguf"
            projector = Path(temp_dir) / "mmproj-model.gguf"
            model.write_bytes(b"m" * 32)
            projector.write_bytes(b"p" * 32)
            modules, management = self._modules(0)
            with patch.dict(sys.modules, modules):
                runtime._maybe_release_comfy_memory({"path": str(model)}, "auto")
        management.unload_all_models.assert_called_once_with()
        management.soft_empty_cache.assert_called_once_with()

    def test_keep_policy_never_releases_comfy_models(self):
        runtime = llama_cpp.LlamaCppRuntime()
        modules, management = self._modules(0)
        with patch.dict(sys.modules, modules):
            runtime._maybe_release_comfy_memory({"path": "/missing/model.gguf"}, "keep")
        management.unload_all_models.assert_not_called()


class LlamaCppVideoInputTests(unittest.TestCase):
    def test_video_input_preserves_original_bytes_and_enforces_size_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "source.webm"
            payload = b"original-video"
            path.write_bytes(payload)
            encoded = media.video_input_to_base64(path, max_bytes=64)
            self.assertEqual(base64.b64decode(encoded), payload)
            with self.assertRaisesRegex(ValueError, "too large"):
                media.video_input_to_base64(path, max_bytes=4)

    def test_video_descriptor_cannot_escape_comfy_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder_paths = types.SimpleNamespace(
                get_temp_directory=lambda: temp_dir,
                get_output_directory=lambda: temp_dir,
                get_input_directory=lambda: temp_dir,
            )
            descriptor = {"video": [{"type": "input", "subfolder": "..", "filename": "outside.mp4"}]}
            with patch.dict(sys.modules, {"folder_paths": folder_paths}):
                with self.assertRaisesRegex(ValueError, "resolve"):
                    media.video_input_to_base64(descriptor)


class LlamaCppChatThinkingTests(unittest.TestCase):
    def test_disabled_thinking_uses_llama_server_request_parameters(self):
        result = openai_compatible.apply_llama_cpp_thinking_level(
            {"temperature": 0.7, "extra_body": {"custom": True}},
            "disabled",
        )
        self.assertEqual(result["reasoning_effort"], "none")
        self.assertFalse(result["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        self.assertTrue(result["extra_body"]["custom"])

    def test_auto_thinking_does_not_add_llama_server_parameters(self):
        original = {"temperature": 0.7}
        self.assertEqual(openai_compatible.apply_llama_cpp_thinking_level(original, "auto"), original)

    def test_reasoning_only_response_raises_without_exposing_reasoning(self):
        secret_reasoning = "private chain of thought"
        with self.assertRaises(RuntimeError) as raised:
            openai_compatible.validate_llama_cpp_final_text("", secret_reasoning)
        self.assertIn("reasoning but no final response", str(raised.exception))
        self.assertNotIn(secret_reasoning, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
