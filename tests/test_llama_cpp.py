from __future__ import annotations

import configparser
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
import llama_cpp_setup


class LlamaCppSetupTests(unittest.TestCase):
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


class FakeRuntime(llama_cpp.LlamaCppRuntime):
    def __init__(self, visual: bool = True):
        super().__init__()
        self.visual = visual
        self.loaded = []
        self.unloaded = []

    def _model(self, model: str, reload: bool = False):
        modalities = ["text", "image"] if self.visual else ["text"]
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

    def test_start_uses_argument_array_and_new_process_group(self):
        runtime = llama_cpp.LlamaCppRuntime()
        settings = llama_cpp.LlamaCppSettings(models_dir="/tmp/models")
        process = Mock()
        process.pid = 123
        process.poll.return_value = None
        process.stdout = []
        with (
            patch.object(llama_cpp, "llama_cpp_settings", return_value=settings),
            patch.object(runtime, "_validate_start", return_value=(llama_cpp.LlamaCppExecutable(Path("/tmp/llama-server"), "configured", (Path("/tmp"),)), "--models-dir --models-max --fit")),
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
        self.assertTrue(kwargs["env"]["LLAMA_API_KEY"])
        self.assertNotIn("shell", kwargs)
        if llama_cpp.os.name != "nt":
            self.assertTrue(kwargs["start_new_session"])


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


if __name__ == "__main__":
    unittest.main()
