"""Stable identities shared by Operator contracts and built-in implementations."""

RETURNED_DIMENSION_CHANGE_URI = "operator://gravity/returned-dimension-change@1"
RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA = (
    "gravity.operator-result.returned-dimension-change.v1"
)

GOVERNED_METHOD_INPUT_SCHEMA = "gravity.operator-input.governed-method.v1"
GOVERNED_METHOD_RESULT_SCHEMA = "gravity.operator-result.governed-method.v1"
GOVERNED_METHOD_URIS = {
    "campaign-outcome-evaluation": "operator://gravity/campaign-outcome-evaluation@1",
    "churn-segment-profile": "operator://gravity/churn-segment-profile@1",
    "funnel-diagnosis": "operator://gravity/funnel-diagnosis@1",
    "ltv-payback-period": "operator://gravity/ltv-payback-period@1",
    "metric-decomposition": "operator://gravity/metric-decomposition@1",
    "price-elasticity": "operator://gravity/price-elasticity@1",
    "retention-curve": "operator://gravity/retention-curve@1",
    "scenario-projection": "operator://gravity/scenario-projection@1",
    "sentiment-aggregation": "operator://gravity/sentiment-aggregation@1",
}

__all__ = [
    "GOVERNED_METHOD_INPUT_SCHEMA",
    "GOVERNED_METHOD_RESULT_SCHEMA",
    "GOVERNED_METHOD_URIS",
    "RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA",
    "RETURNED_DIMENSION_CHANGE_URI",
]
