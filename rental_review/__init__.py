"""中国内地及香港合同风险审查（租房 / 健身培训 / 采购 / 劳动合同）。"""

from .pipeline import (
    CONTRACT_TYPES,
    DEFAULT_CONTRACT_TYPE,
    DEFAULT_REGION,
    DISCLAIMER,
    REGIONS,
    review_contract,
    review_parsed,
)
from .parser import parse_contract

__all__ = [
    'CONTRACT_TYPES',
    'DEFAULT_CONTRACT_TYPE',
    'DEFAULT_REGION',
    'DISCLAIMER',
    'REGIONS',
    'parse_contract',
    'review_contract',
    'review_parsed',
]
