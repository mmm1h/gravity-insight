"""Offline CLI surfaces for exact Operator and Model contracts."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping

from .model_registry import ModelRegistry
from .operator_registry import OperatorRegistry


def add_operator_model_commands(commands: Any, add_input: Callable[..., None]) -> None:
    operators = commands.add_parser(
        "operators", help="Inspect exact installed deterministic Operators."
    )
    operator_actions = operators.add_subparsers(
        dest="operators_command", required=True
    )
    operator_list = operator_actions.add_parser("list")
    operator_describe = operator_actions.add_parser("describe")
    operator_describe.add_argument("uri")
    operator_validate = operator_actions.add_parser("validate")
    add_input(operator_validate, required=True)
    for parser in (operator_list, operator_describe, operator_validate):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)

    models = commands.add_parser(
        "models", help="Inspect and evaluate explicit local Model Artifacts."
    )
    model_actions = models.add_subparsers(dest="models_command", required=True)
    model_list = model_actions.add_parser("list")
    _add_model_sources(model_list)
    model_describe = model_actions.add_parser("describe")
    model_describe.add_argument("uri")
    _add_model_sources(model_describe)
    model_evaluate = model_actions.add_parser("evaluate")
    model_evaluate.add_argument("uri")
    _add_model_sources(model_evaluate)
    model_evaluate.add_argument("--at")
    model_evaluate.add_argument("--horizon-days", type=_positive_integer)
    model_evaluate.add_argument("--unit")
    for parser in (model_list, model_describe, model_evaluate):
        parser.set_defaults(network_required=False, _gravity_handler=dispatch)


def dispatch(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]]
) -> dict[str, Any]:
    if args.command == "operators":
        registry = OperatorRegistry()
        if args.operators_command == "list":
            return registry.list()
        if args.operators_command == "describe":
            return registry.describe(args.uri)
        return registry.validate(object_input(args.input))
    registry = ModelRegistry(getattr(args, "model_sources", ()))
    if args.models_command == "list":
        return registry.list()
    if args.models_command == "describe":
        return registry.describe(args.uri)
    return registry.evaluate(
        args.uri,
        at=args.at,
        horizon_days=args.horizon_days,
        unit=args.unit,
    )


def _add_model_sources(parser: Any) -> None:
    parser.add_argument(
        "--source",
        dest="model_sources",
        action="append",
        default=[],
        help="Explicit local gravity.model-artifact.v1 JSON file; may be repeated.",
    )


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("horizon-days must be positive")
    return parsed


__all__ = ["add_operator_model_commands", "dispatch"]
