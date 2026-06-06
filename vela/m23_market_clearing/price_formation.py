"""
Price formation models for electricity markets.

Models how wholesale prices form under different market designs:
pay-as-bid, uniform price, Vickrey auctions, and bilateral markets.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class AuctionType(str, Enum):
    UNIFORM_PRICE = "uniform_price"
    PAY_AS_BID = "pay_as_bid"
    VICKREY = "vickrey"


@dataclass
class PriceFormationResult:
    clearing_price: float
    cleared_quantity_mw: float
    consumer_surplus: float
    producer_surplus: float
    total_welfare: float
    uplift_mw: float = 0.0    # Out-of-merit dispatch


def uniform_price_clear(
    bids: List[Tuple[float, float]],    # (price, quantity) demand
    offers: List[Tuple[float, float]],  # (price, quantity) supply
) -> PriceFormationResult:
    """
    Uniform-price auction (standard ISO energy market design).

    All accepted sellers receive the clearing price (marginal cost).
    Efficient — maximizes total welfare.
    """
    sorted_bids = sorted(bids, key=lambda b: -b[0])
    sorted_offers = sorted(offers, key=lambda o: o[0])

    clearing_price = 0.0
    cleared_mw = 0.0
    demand_remaining = sum(q for _, q in sorted_bids)

    for offer_price, offer_qty in sorted_offers:
        if demand_remaining <= 0:
            break
        accepted = min(offer_qty, demand_remaining)
        clearing_price = offer_price
        cleared_mw += accepted
        demand_remaining -= accepted

    consumer_surplus = sum(
        (p - clearing_price) * q for p, q in sorted_bids if p >= clearing_price
    )
    producer_surplus = sum(
        (clearing_price - p) * q for p, q in sorted_offers if p <= clearing_price
    )

    return PriceFormationResult(
        clearing_price=clearing_price,
        cleared_quantity_mw=cleared_mw,
        consumer_surplus=max(0.0, consumer_surplus),
        producer_surplus=max(0.0, producer_surplus),
        total_welfare=max(0.0, consumer_surplus + producer_surplus),
    )


def pay_as_bid_clear(
    bids: List[Tuple[float, float]],
    offers: List[Tuple[float, float]],
) -> PriceFormationResult:
    """
    Pay-as-bid auction: each seller is paid their own offer price.

    Used in some UK capacity and ancillary service markets.
    Encourages strategic bidding above marginal cost.
    """
    sorted_bids = sorted(bids, key=lambda b: -b[0])
    sorted_offers = sorted(offers, key=lambda o: o[0])

    demand_remaining = sum(q for _, q in sorted_bids)
    cleared_mw = 0.0
    total_payment = 0.0
    last_price = 0.0

    for offer_price, offer_qty in sorted_offers:
        if demand_remaining <= 0:
            break
        accepted = min(offer_qty, demand_remaining)
        total_payment += accepted * offer_price
        cleared_mw += accepted
        last_price = offer_price
        demand_remaining -= accepted

    avg_price = total_payment / max(cleared_mw, 1e-9)
    return PriceFormationResult(
        clearing_price=avg_price,
        cleared_quantity_mw=cleared_mw,
        consumer_surplus=0.0,
        producer_surplus=0.0,
        total_welfare=0.0,
    )


class RealTimePriceEngine:
    """
    Computes 5-minute real-time LMPs from system conditions.

    Applies scarcity pricing function per NERC standard MKT-001.
    """

    def __init__(self, scarcity_threshold_mw: float = 500.0) -> None:
        self.scarcity_threshold = scarcity_threshold_mw

    def compute_rtlmp(
        self,
        base_lmp: float,
        available_reserves_mw: float,
        system_load_mw: float,
        installed_capacity_mw: float,
    ) -> float:
        """
        Compute real-time LMP with scarcity adder.

        ERCOT-style scarcity pricing:
        - Operating Reserve Demand Curve (ORDC) adds $/MWh based on reserve margin.
        """
        reserve_margin = available_reserves_mw / max(system_load_mw, 1.0)
        if reserve_margin < 0.03:
            scarcity_adder = 9000.0  # Near price cap
        elif reserve_margin < 0.058:
            scarcity_adder = 5000.0
        elif reserve_margin < 0.10:
            scarcity_adder = 300.0 * (0.10 - reserve_margin) / 0.04
        else:
            scarcity_adder = 0.0
        return base_lmp + scarcity_adder
