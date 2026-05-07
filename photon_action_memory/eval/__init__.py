"""Offline and shadow evaluation utilities."""

from photon_action_memory.eval.anvil_feedback import (
    EXCLUDED_QUALITY_STATUSES,
    EvidenceFeedback,
    PackFeedback,
    aggregate_anvil_feedback,
)
from photon_action_memory.eval.comparison import (
    COMPARISON_REPORT_SCHEMA,
    EVAL_CONDITIONS,
    ComparisonRecord,
    ComparisonReport,
    ConditionSummary,
    build_comparison_report,
)
from photon_action_memory.eval.local_llm import (
    LOCAL_LLM_REPORT_SCHEMA,
    LocalLLMModelMeta,
    LocalLLMRecord,
    LocalLLMReport,
    build_local_llm_report,
)
from photon_action_memory.eval.metrics import (
    EvalAction,
    EvalSuggestion,
    EvalWarning,
    MetricsReport,
    ShadowEvalRecord,
    build_metrics_report,
)
from photon_action_memory.eval.pollution import (
    PollutionRecord,
    PollutionReport,
    build_pollution_report,
    measure_context_pack,
)
from photon_action_memory.eval.runner import (
    load_fixture,
    run_comparison,
    run_comparison_fixture,
    run_eval,
    run_fixture,
    run_local_llm,
    run_local_llm_fixture,
    write_comparison_report,
    write_local_llm_report,
    write_metrics_report,
)
from photon_action_memory.eval.summary_fidelity import SummaryFidelityChecker

__all__ = [
    "COMPARISON_REPORT_SCHEMA",
    "EXCLUDED_QUALITY_STATUSES",
    "EvidenceFeedback",
    "PackFeedback",
    "aggregate_anvil_feedback",
    "EVAL_CONDITIONS",
    "LOCAL_LLM_REPORT_SCHEMA",
    "EvalAction",
    "EvalSuggestion",
    "EvalWarning",
    "ComparisonRecord",
    "ComparisonReport",
    "ConditionSummary",
    "LocalLLMModelMeta",
    "LocalLLMRecord",
    "LocalLLMReport",
    "MetricsReport",
    "PollutionRecord",
    "PollutionReport",
    "ShadowEvalRecord",
    "SummaryFidelityChecker",
    "build_comparison_report",
    "build_local_llm_report",
    "build_metrics_report",
    "build_pollution_report",
    "load_fixture",
    "measure_context_pack",
    "run_comparison",
    "run_comparison_fixture",
    "run_eval",
    "run_fixture",
    "run_local_llm",
    "run_local_llm_fixture",
    "write_comparison_report",
    "write_local_llm_report",
    "write_metrics_report",
]
