import importlib.util
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch
from equitylab.data import ROOT

spec = importlib.util.spec_from_file_location(
    "tested_private_runtime", ROOT / "scripts/local-research.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class GpuRuntimeTests(unittest.TestCase):
    def test_idle_gpu_requires_memory_and_no_compute_process(self):
        with patch.object(
            runtime.subprocess,
            "run",
            side_effect=[SimpleNamespace(stdout="2\n"), SimpleNamespace(stdout="")],
        ):
            self.assertTrue(runtime.gpu_available())
        with patch.object(
            runtime.subprocess,
            "run",
            side_effect=[
                SimpleNamespace(stdout="304\n"),
                SimpleNamespace(stdout="12345\n"),
            ],
        ):
            self.assertFalse(runtime.gpu_available())

    def test_large_allocation_and_missing_gpu_do_not_qualify(self):
        for text in ["5732\n", ""]:
            with patch.object(
                runtime.subprocess, "run", return_value=SimpleNamespace(stdout=text)
            ) as run:
                self.assertFalse(runtime.gpu_available())
                self.assertEqual(run.call_count, 1)

    def test_probe_failure_is_not_an_idle_gpu(self):
        with patch.object(
            runtime.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "nvidia-smi"),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.gpu_available()

    def test_waits_for_completion_without_mutating_other_processes(self):
        with patch.object(
            runtime, "gpu_available", side_effect=[False, True]
        ), patch.object(runtime.time, "monotonic", side_effect=[0, 0]), patch.object(
            runtime.time, "sleep"
        ) as sleep:
            runtime.wait_for_gpu(60)
            sleep.assert_called_once_with(30)

    def test_bounded_wait_expires_without_starting_a_runtime(self):
        with patch.object(runtime, "gpu_available", return_value=False), patch.object(
            runtime.time, "monotonic", side_effect=[0, 0, 5]
        ), patch.object(runtime.time, "sleep") as sleep, patch.object(
            runtime.subprocess, "Popen"
        ) as start:
            with self.assertRaisesRegex(RuntimeError, "wait expired"):
                runtime.wait_for_gpu(5)
            sleep.assert_called_once_with(5)
            start.assert_not_called()

    def test_negative_wait_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime.wait_for_gpu(-1)

    def test_metadata_and_unload_only_do_not_wait_or_load_a_gpu(self):
        client = runtime.GpuGatedClient(wait_gpu_seconds=60)
        with patch.object(runtime, "wait_for_gpu") as wait, patch.object(
            runtime.LocalClient, "call", return_value={}
        ) as call:
            client.call("version")
            client.call("tags")
            client.call("ps")
            client.call("generate", {"model": "qwen3:8b", "keep_alive": 0})
            wait.assert_not_called()
            self.assertEqual(call.call_count, 4)
            self.assertFalse(client.gpu_checked)

    def test_first_real_request_waits_before_http_and_critic_reuses_runtime(self):
        client = runtime.GpuGatedClient(wait_gpu_seconds=60)
        calls = []
        with patch.object(
            runtime, "wait_for_gpu", side_effect=lambda _: calls.append("gpu")
        ), patch.object(
            runtime.LocalClient, "call", side_effect=lambda *args: calls.append("http")
        ):
            client.call("chat", {"messages": [{"role": "user", "content": "test"}]})
            client.call("chat", {"messages": [{"role": "user", "content": "critic"}]})
        self.assertEqual(calls, ["gpu", "http", "http"])

    def test_failed_gpu_wait_never_sends_inference_even_with_zero_keep_alive(self):
        client = runtime.GpuGatedClient(wait_gpu_seconds=0)
        with patch.object(
            runtime, "wait_for_gpu", side_effect=RuntimeError("GPU busy")
        ), patch.object(runtime.LocalClient, "call") as call:
            with self.assertRaisesRegex(RuntimeError, "GPU busy"):
                client.call(
                    "generate",
                    {
                        "model": "qwen3:8b",
                        "keep_alive": 0,
                        "prompt": "actual inference",
                    },
                )
            call.assert_not_called()
            self.assertFalse(client.gpu_checked)

    def test_expired_runtime_does_not_wait_again_for_each_company(self):
        client = runtime.GpuGatedClient(wait_gpu_seconds=600)
        with patch.object(
            runtime, "wait_for_gpu", side_effect=RuntimeError("GPU wait expired")
        ) as wait, patch.object(runtime.LocalClient, "call", return_value={}) as call:
            for company in ["AMD", "GE", "005930"]:
                with self.assertRaisesRegex(RuntimeError, "wait expired"):
                    client.call("chat", {"prompt": company})
            wait.assert_called_once_with(600)
            call.assert_not_called()
            client.call("tags")
            client.call("generate", {"model": "qwen3:8b", "keep_alive": 0})
            self.assertEqual(call.call_count, 2)
            self.assertFalse(client.gpu_checked)
