"""Runpod provisioner tests — all offline, no network.

Every cost-incurring operation must refuse without confirm=True. These
tests enforce that contract; if a future refactor breaks it, the suite
fails loudly before anyone burns GPU hours.
"""
from __future__ import annotations

import pytest

from runner import runpod_provisioner as rp


def test_gpu_types_contain_expected_keys():
    assert "H100_SXM" in rp.GPU_TYPES
    assert "H200" in rp.GPU_TYPES
    assert "B200" in rp.GPU_TYPES
    assert rp.GPU_TYPES["H100_SXM"] == "NVIDIA H100 80GB HBM3"
    assert rp.GPU_TYPES["B200"] == "NVIDIA B200"


def test_arch_mapping_h200_is_hopper_not_blackwell():
    """Regression guard against the user-reported architecture confusion."""
    assert rp.ARCH_BY_GPU[rp.GPU_TYPES["H200"]] == "sm_90a"  # Hopper
    assert rp.ARCH_BY_GPU[rp.GPU_TYPES["B200"]] == "sm_100"  # Blackwell
    # The two must differ — H200 is emphatically not Blackwell.
    assert rp.ARCH_BY_GPU[rp.GPU_TYPES["H200"]] != rp.ARCH_BY_GPU[rp.GPU_TYPES["B200"]]


def test_podspec_defaults_are_safe():
    spec = rp.PodSpec()
    body = spec.to_body()
    assert body["cloudType"] == "SECURE"  # needed for ncu counters
    assert body["computeType"] == "GPU"
    assert body["gpuCount"] >= 1
    assert "NVIDIA H100 80GB HBM3" in body["gpuTypeIds"]


def test_create_pod_without_confirm_is_dry_run():
    """create_pod without confirm=True must NOT call the API."""
    spec = rp.PodSpec(name="test")
    result = rp.create_pod(spec, confirm=False, dry_run_print=False)
    assert result["dry_run"] is True
    assert "body" in result


def test_delete_pod_without_confirm_is_dry_run():
    result = rp.delete_pod("fake-id", confirm=False)
    assert result["dry_run"] is True


def test_stop_pod_without_confirm_is_dry_run():
    result = rp.stop_pod("fake-id", confirm=False)
    assert result["dry_run"] is True


def test_start_pod_without_confirm_is_dry_run():
    result = rp.start_pod("fake-id", confirm=False)
    assert result["dry_run"] is True


def test_require_api_key_raises_without_env(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(rp.RunPodError, match="RUNPOD_API_KEY"):
        rp._require_api_key()


def test_environment_report_is_safe_without_key(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    report = rp.environment_report()
    assert report["api_key_present"] is False
    # Must not try to list pods when key missing.
    assert "list_ok" not in report


def test_podspec_to_body_excludes_none_values():
    spec = rp.PodSpec()
    body = spec.to_body()
    assert None not in body.values()
