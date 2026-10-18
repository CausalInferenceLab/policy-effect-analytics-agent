"""공공데이터 어댑터. 새 소스는 BaseAdapter 를 상속해 fetch() 만 구현하면 된다."""

from .base import BaseAdapter, MissingAPIKey, SourceMeta
from .kosis import KosisAdapter
from .local import LocalFileAdapter
from .molit import MolitAptTradeAdapter
from .seoul_subway import SeoulSubwayDailyAdapter
from .synthetic import SyntheticAdapter, simulate_panel

REGISTRY = {
    "kosis": KosisAdapter,
    "local": LocalFileAdapter,
    "molit": MolitAptTradeAdapter,
    "seoul_subway": SeoulSubwayDailyAdapter,
    "synthetic": SyntheticAdapter,
}

__all__ = [
    "BaseAdapter",
    "SourceMeta",
    "MissingAPIKey",
    "KosisAdapter",
    "LocalFileAdapter",
    "MolitAptTradeAdapter",
    "SeoulSubwayDailyAdapter",
    "SyntheticAdapter",
    "simulate_panel",
    "REGISTRY",
]
