"""Versioned benchmark suites that are physically separate from training data."""

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite, SuiteValidationError
from local_ai_lab.benchmark.real import RealBenchmarkSuite, RealBenchmarkValidationError

__all__ = [
    "ControlledCorpusSuite", "RealBenchmarkSuite", "RealBenchmarkValidationError",
    "SuiteValidationError",
]
