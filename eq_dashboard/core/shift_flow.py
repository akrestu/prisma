"""Approval of Hourly Production shifts: states, closing time and what the data officer may do. No Streamlit or
database here.

DRAFT (saved, not sent) → SUBMITTED (waiting for the Site Manager) → APPROVED, or REJECTED back to the data officer.
A shift closes at 09:00 WIB the day after its production date. It is locked once APPROVED or once closed
(except REJECTED, which is sent back to be fixed); a locked shift changes only through a change request that the
Site Manager approves. A shift not yet approved at closing keeps waiting: it can still be submitted and approved.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from core.config import WIB, now_wib

DRAFT, SUBMITTED, APPROVED, REJECTED = "DRAFT", "SUBMITTED", "APPROVED", "REJECTED"
PENDING = "PENDING"                                         # change request waiting for a decision
CLOSING_HOUR = 9                                            # H+1 09:00 WIB
LABEL = {DRAFT: "Draft · not submitted", SUBMITTED: "Submitted · waiting for the Site Manager",
         APPROVED: "Approved", REJECTED: "Rejected · fix and submit again"}


def now() -> dt.datetime:
    """The clock the server-side checks use (tests set it)."""
    return now_wib()


def closes_at(date: dt.date) -> dt.datetime:
    """Closing time of every shift of a production date: 09:00 WIB the next day."""
    return dt.datetime.combine(date + dt.timedelta(days=1), dt.time(CLOSING_HOUR), tzinfo=WIB)


@dataclass(frozen=True)
class State:
    status: str
    closed: bool
    locked: bool          # direct saving is refused: changes go through a change request
    can_submit: bool
    pending_change: bool

    @property
    def label(self) -> str:
        return LABEL.get(self.status, self.status) + (" · closed" if self.closed else "")


def state(status: str | None, date: dt.date, now: dt.datetime, pending_change: bool = False) -> State:
    """What can be done with a shift (`status` None = nothing saved yet) at `now` (aware)."""
    st_ = status or DRAFT
    closed = now >= closes_at(date)
    locked = st_ == APPROVED or (closed and st_ != REJECTED)
    can_submit = status is not None and st_ in (DRAFT, REJECTED)
    return State(st_, closed, locked, can_submit, pending_change)


def after_save(status: str | None) -> str:
    """Status after a direct save: any edit of a submitted or rejected sheet must be submitted (again)."""
    return status if status == APPROVED else DRAFT
