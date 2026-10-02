"""AgentCore code-based evaluator entry point. The detection logic lives in leakage.py."""

from bedrock_agentcore.evaluation.custom_code_based_evaluators import (
    EvaluatorInput,
    EvaluatorOutput,
    custom_code_based_evaluator,
)

from leakage import evaluate


@custom_code_based_evaluator()
def handler(input: EvaluatorInput, context) -> EvaluatorOutput:
    return EvaluatorOutput(**evaluate(input.session_spans))
