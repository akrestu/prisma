"""Approval per Hourly Production shift: states, closing at 09:00 WIB the next day, locking, change requests."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core import hourly as H
from core import shift_flow as SF
from core.config import WIB
from db import repo
from tests.test_hourly import LF, OPS, TG, UNITS, hauler_rows

D = dt.date(2026, 9, 26)
BEFORE = dt.datetime(2026, 9, 27, 8, 59, tzinfo=WIB)          # one minute before closing
AFTER = dt.datetime(2026, 9, 27, 9, 0, tzinfo=WIB)


def lines(trips: int = 2) -> pd.DataFrame:
    return H.resolve(hauler_rows({"hauler": "WHT026", "r1": trips}), LF, TG, UNITS, OPS).rows


def test_states_and_closing_time():
    assert SF.closes_at(D) == AFTER
    s = SF.state(None, D, BEFORE)
    assert not s.locked and not s.can_submit                                  # nothing saved yet
    assert SF.state(SF.DRAFT, D, BEFORE).can_submit and not SF.state(SF.DRAFT, D, BEFORE).locked
    assert SF.state(SF.DRAFT, D, AFTER).locked and SF.state(SF.DRAFT, D, AFTER).can_submit   # late, still submittable
    assert SF.state(SF.SUBMITTED, D, AFTER).locked and not SF.state(SF.SUBMITTED, D, BEFORE).can_submit
    assert SF.state(SF.APPROVED, D, BEFORE).locked
    assert not SF.state(SF.REJECTED, D, AFTER).locked                         # sent back: can be fixed
    assert SF.after_save(SF.SUBMITTED) == SF.DRAFT and SF.after_save(SF.REJECTED) == SF.DRAFT


def test_submit_approve_then_locked(db_session, shift_clock):
    s = db_session
    shift_clock(BEFORE)
    with pytest.raises(ValueError, match="save it first"):
        repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(), "op1")
    sh = repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    s.commit()
    assert sh.status == SF.SUBMITTED and list(repo.shifts_waiting(s, ["WBK-BAU"])["id"]) == [sh.id]
    assert repo.hourly_waiting_count(s, ["WBK-BAU"]) == 1 and repo.hourly_waiting_count(s, ["WBK-MAS"]) == 0
    with pytest.raises(ValueError, match="reason"):
        repo.review_shift(s, sh.id, False, "sm1", " ")
    repo.review_shift(s, sh.id, True, "sm1")
    s.commit()
    assert (sh.status, sh.reviewed_by) == (SF.APPROVED, "sm1")
    with pytest.raises(ValueError, match="no longer waiting"):
        repo.review_shift(s, sh.id, True, "sm1")
    with pytest.raises(ValueError, match="locked"):
        repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(5), "op1")
    s.rollback()
    with pytest.raises(ValueError, match="locked"):
        repo.add_hourly_remark(s, "WBK-BAU", D, "DS", 1, 1, "WEX019", "302", "", "op1")


def test_editing_a_submitted_shift_needs_a_new_submit(db_session, shift_clock):
    s = db_session
    shift_clock(BEFORE)
    repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(), "op1")
    repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    sh = repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(3), "op1")
    assert sh.status == SF.DRAFT


def test_closing_locks_a_draft_but_a_rejected_shift_can_be_fixed(db_session, shift_clock):
    s = db_session
    shift_clock(BEFORE)
    sh = repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(), "op1")
    repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    s.commit()
    shift_clock(AFTER)
    repo.review_shift(s, sh.id, False, "sm1", "ritase WHT026 tidak sesuai form")
    s.commit()
    repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(4), "op1")              # rejected: fixed after closing
    repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    s.commit()
    repo.save_hourly(s, "WBK-BAU", D, "NS", "", lines(), "op1")               # entered late: allowed once
    s.commit()
    with pytest.raises(ValueError, match="locked"):
        repo.save_hourly(s, "WBK-BAU", D, "NS", "", lines(6), "op1")         # then locked
    s.rollback()
    assert repo.submit_shift(s, "WBK-BAU", D, "NS", "op1").status == SF.SUBMITTED   # still waits for approval


def test_change_request_applies_only_when_approved(db_session, shift_clock):
    s = db_session
    shift_clock(BEFORE)
    sh = repo.save_hourly(s, "WBK-BAU", D, "DS", "Andi", lines(2), "op1")
    repo.submit_shift(s, "WBK-BAU", D, "DS", "op1")
    repo.review_shift(s, sh.id, True, "sm1")
    s.commit()
    with pytest.raises(ValueError, match="reason"):
        repo.request_change(s, "WBK-BAU", D, "DS", "Andi", lines(7), "", "op1")
    cr = repo.request_change(s, "WBK-BAU", D, "DS", "Andi", lines(7), "typo", "op1")
    s.commit()
    again = repo.request_change(s, "WBK-BAU", D, "DS", "Andi", lines(8), "typo, cek form", "op1")
    s.commit()
    assert again.id == cr.id and len(repo.change_requests(s, ["WBK-BAU"])) == 1     # one open request per shift
    assert repo.hourly_shift(s, "WBK-BAU", D, "DS")[1].loc[0, "r1"] == 2              # not applied yet
    assert repo.change_rows(s, cr.id).loc[0, "r1"] == 8
    repo.decide_change(s, cr.id, True, "sm1")
    s.commit()
    sh2, got = repo.hourly_shift(s, "WBK-BAU", D, "DS")
    assert got.loc[0, "r1"] == 8 and sh2.status == SF.APPROVED and repo.change_requests(s, ["WBK-BAU"]).empty
    with pytest.raises(ValueError, match="no longer open"):
        repo.decide_change(s, cr.id, False, "sm1", "x")
    cr2 = repo.request_change(s, "WBK-BAU", D, "DS", "Andi", lines(1), "salah lagi", "op1")
    repo.decide_change(s, cr2.id, False, "sm1", "sudah benar")
    s.commit()
    assert repo.hourly_shift(s, "WBK-BAU", D, "DS")[1].loc[0, "r1"] == 8


def test_change_request_only_for_locked_shifts(db_session, shift_clock):
    s = db_session
    shift_clock(BEFORE)
    repo.save_hourly(s, "WBK-BAU", D, "DS", "", lines(), "op1")
    with pytest.raises(ValueError, match="not locked"):
        repo.request_change(s, "WBK-BAU", D, "DS", "", lines(3), "why", "op1")
