"""Build CAISO/ERCOT market offers from optimizer output."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple
import uuid

import numpy as np

from .bid_models import EnergyBid, AncillaryBid, BidType

logger = logging.getLogger(__name__)


class MarketOffer(NamedTuple):
    offer_id: str
    asset_id: str
    market: str
    trading_date: datetime
    energy_bids: list[EnergyBid]
    ancillary_bids: list[AncillaryBid]
    total_offered_mwh: float
    total_as_mw: float
    expected_revenue: float


@dataclass
class CAISOOfferBuilder:
    """
    Builds CAISO (California ISO) market offers from dispatch plan output.

    CAISO markets:
    - Day-Ahead Market (DAM): submits energy offers by 10 AM
    - Real-Time Market (RTM): 5-minute dispatch
    - Regulation: hourly capacity offers
    - Spinning/Non-Spinning Reserve: hourly capacity offers

    Offer format: price-quantity pairs (supply curve) per interval
    """
    asset_id: str
    resource_id: str    # CAISO resource ID (e.g., "VELA_BTMS_01")
    min_offer_mw: float = 0.1
    price_increment: float = 0.01  # $/MWh price granularity
    market_close_buffer_h: int = 2  # Hours before market close to submit

    def build_dam_offers(
        self,
        trading_date: datetime,
        dispatch_charge: list[float],
        dispatch_discharge: list[float],
        lmp_forecast: list[float],
        reg_up_mw: list[float] | None = None,
        reg_down_mw: list[float] | None = None,
        spin_mw: list[float] | None = None,
        dt_hours: float = 1.0,
    ) -> MarketOffer:
        """
        Build Day-Ahead Market (DAM) offers.

        Energy bids: discharge schedule (supply offer), charge schedule (demand bid)
        AS bids: regulation capacity offers
        """
        T = len(dispatch_discharge)
        energy_bids = []
        ancillary_bids = []
        total_mwh = 0.0
        total_as = 0.0
        expected_rev = 0.0

        for t in range(T):
            interval_start = trading_date + timedelta(hours=t)
            interval_end = interval_start + timedelta(hours=dt_hours)
            lmp = lmp_forecast[t]

            # Energy discharge offer (supply)
            if dispatch_discharge[t] >= self.min_offer_mw:
                mwh = dispatch_discharge[t] * dt_hours
                # Strategic bidding: offer just below LMP forecast (ensure dispatch)
                offer_price = max(0.0, lmp * 0.98)
                energy_bids.append(EnergyBid(
                    asset_id=self.asset_id,
                    market="CAISO_DAM",
                    interval_start=interval_start,
                    interval_end=interval_end,
                    mw=dispatch_discharge[t],
                    price=round(offer_price, 2),
                    bid_type=BidType.ENERGY,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                total_mwh += mwh
                expected_rev += mwh * lmp

            # Energy charge bid (demand)
            if dispatch_charge[t] >= self.min_offer_mw:
                mwh = dispatch_charge[t] * dt_hours
                # Bid slightly above LMP to ensure we buy
                bid_price = min(lmp * 1.02, lmp + 2.0)
                energy_bids.append(EnergyBid(
                    asset_id=self.asset_id,
                    market="CAISO_DAM",
                    interval_start=interval_start,
                    interval_end=interval_end,
                    mw=-dispatch_charge[t],  # Negative = load
                    price=round(bid_price, 2),
                    bid_type=BidType.ENERGY,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                expected_rev -= mwh * lmp

            # Regulation Up offer
            if reg_up_mw and reg_up_mw[t] >= self.min_offer_mw:
                ancillary_bids.append(AncillaryBid(
                    asset_id=self.asset_id,
                    market="CAISO_DAM",
                    interval_start=interval_start,
                    service="REG_UP",
                    mw=reg_up_mw[t],
                    price=0.0,  # CAISO reg uses capability payment; price = 0 for price-taker
                    bid_id=str(uuid.uuid4())[:8],
                ))
                total_as += reg_up_mw[t]

            # Regulation Down offer
            if reg_down_mw and reg_down_mw[t] >= self.min_offer_mw:
                ancillary_bids.append(AncillaryBid(
                    asset_id=self.asset_id,
                    market="CAISO_DAM",
                    interval_start=interval_start,
                    service="REG_DOWN",
                    mw=reg_down_mw[t],
                    price=0.0,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                total_as += reg_down_mw[t]

            # Spinning reserve
            if spin_mw and spin_mw[t] >= self.min_offer_mw:
                ancillary_bids.append(AncillaryBid(
                    asset_id=self.asset_id,
                    market="CAISO_DAM",
                    interval_start=interval_start,
                    service="SPIN",
                    mw=spin_mw[t],
                    price=0.0,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                total_as += spin_mw[t]

        offer = MarketOffer(
            offer_id=str(uuid.uuid4()),
            asset_id=self.asset_id,
            market="CAISO_DAM",
            trading_date=trading_date,
            energy_bids=energy_bids,
            ancillary_bids=ancillary_bids,
            total_offered_mwh=total_mwh,
            total_as_mw=total_as / max(T, 1),
            expected_revenue=expected_rev,
        )
        logger.info(
            "Built CAISO DAM offer %s: %d energy bids, %d AS bids, exp rev=$%.2f",
            offer.offer_id, len(energy_bids), len(ancillary_bids), expected_rev
        )
        return offer


@dataclass
class ERCOTOfferBuilder:
    """
    Builds ERCOT market offers.

    ERCOT markets:
    - Day-Ahead Market (DAM)
    - Real-Time Market (RTM): SCED (Security Constrained Economic Dispatch)
    - Ancillary Services: ECRS, Reg-Up, Reg-Down, RRS (Responsive Reserve), Non-Spin
    """
    asset_id: str
    qse_id: str  # Qualified Scheduling Entity ID
    min_offer_mw: float = 0.1

    def build_dam_offers(
        self,
        trading_date: datetime,
        dispatch_charge: list[float],
        dispatch_discharge: list[float],
        lmp_forecast: list[float],
        reg_up_mw: list[float] | None = None,
        reg_down_mw: list[float] | None = None,
        spin_mw: list[float] | None = None,
        dt_hours: float = 1.0,
    ) -> MarketOffer:
        """Build ERCOT DAM energy + AS offers."""
        T = len(dispatch_discharge)
        energy_bids = []
        ancillary_bids = []
        total_mwh = 0.0
        total_as = 0.0
        expected_rev = 0.0

        for t in range(T):
            interval_start = trading_date + timedelta(hours=t)
            interval_end = interval_start + timedelta(hours=dt_hours)
            lmp = lmp_forecast[t]

            if dispatch_discharge[t] >= self.min_offer_mw:
                # ERCOT uses multi-segment supply curves; we submit at forecast LMP
                offer_price = max(0.0, round(lmp * 0.97, 2))
                energy_bids.append(EnergyBid(
                    asset_id=self.asset_id,
                    market="ERCOT_DAM",
                    interval_start=interval_start,
                    interval_end=interval_end,
                    mw=dispatch_discharge[t],
                    price=offer_price,
                    bid_type=BidType.ENERGY,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                total_mwh += dispatch_discharge[t] * dt_hours
                expected_rev += dispatch_discharge[t] * dt_hours * lmp

            if dispatch_charge[t] >= self.min_offer_mw:
                bid_price = round(lmp * 1.03, 2)
                energy_bids.append(EnergyBid(
                    asset_id=self.asset_id,
                    market="ERCOT_DAM",
                    interval_start=interval_start,
                    interval_end=interval_end,
                    mw=-dispatch_charge[t],
                    price=bid_price,
                    bid_type=BidType.ENERGY,
                    bid_id=str(uuid.uuid4())[:8],
                ))
                expected_rev -= dispatch_charge[t] * dt_hours * lmp

            for service, mw_list, svc_name in [
                (reg_up_mw, reg_up_mw, "REG_UP"),
                (reg_down_mw, reg_down_mw, "REG_DOWN"),
                (spin_mw, spin_mw, "RRS"),
            ]:
                if mw_list and mw_list[t] >= self.min_offer_mw:
                    ancillary_bids.append(AncillaryBid(
                        asset_id=self.asset_id,
                        market="ERCOT_DAM",
                        interval_start=interval_start,
                        service=svc_name,
                        mw=mw_list[t],
                        price=0.0,  # ERCOT AS: price-taker (cleared at system marginal AS price)
                        bid_id=str(uuid.uuid4())[:8],
                    ))
                    total_as += mw_list[t]

        return MarketOffer(
            offer_id=str(uuid.uuid4()),
            asset_id=self.asset_id,
            market="ERCOT_DAM",
            trading_date=trading_date,
            energy_bids=energy_bids,
            ancillary_bids=ancillary_bids,
            total_offered_mwh=total_mwh,
            total_as_mw=total_as / max(T, 1),
            expected_revenue=expected_rev,
        )
