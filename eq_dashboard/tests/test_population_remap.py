"""Re-upload after a Unit Population change: an upload imported before the population that applies to its month
now is 'stale', so the same file is accepted again (and listed on the Unit Population page)."""
from __future__ import annotations

import datetime as dt

from core import ingest as ing
from db import models as m

T0 = dt.datetime(2026, 11, 1, 8, tzinfo=dt.UTC)


def _upload(s, digest, month, at, status=ing.PUBLISHED):
    up = m.Upload(filename=f"{digest}.xlsx", sha256=digest, month=month, uploaded_at=at, summary={})
    s.add(up)
    s.flush()
    s.add(m.UploadSite(upload_id=up.id, site_code="WBK-MAS", month=month, status=status))
    s.flush()
    return up


def _population(s, effective, at):
    v = m.PopulationVersion(effective_from=effective, filename="pop.xlsx", sha256=f"p{effective}{at}", units=1,
                            uploaded_at=at)
    s.add(v)
    s.flush()
    return v


def test_population_uploaded_later_for_the_month_frees_the_file(db_session):
    s = db_session
    _population(s, dt.date(2025, 1, 1), T0 - dt.timedelta(days=30))      # only 2025-2026 known at import
    y23 = _upload(s, "jan23", dt.date(2023, 1, 1), T0)
    y26 = _upload(s, "jan26", dt.date(2026, 1, 1), T0)
    assert ing.live_uploads(s, ["jan23", "jan26"]) == {"jan23": y23.id, "jan26": y26.id}
    assert ing.stale_published(s) == []

    v23 = _population(s, dt.date(2023, 1, 1), T0 + dt.timedelta(days=1))  # 2023 population arrives afterwards
    # 2023 now maps with a newer population: re-upload allowed; 2026 still uses the population it was imported with
    assert ing.live_uploads(s, ["jan23", "jan26"]) == {"jan26": y26.id}
    assert ing.remapped_uploads(s, ["jan23", "jan26"]) == {"jan23": y23.id}
    stale = ing.stale_published(s)
    assert [(x["upload"], x["population"], x["month"]) for x in stale] == [(y23.id, v23.id, dt.date(2023, 1, 1))]


def test_retired_upload_is_never_reported_as_remapped(db_session):
    s = db_session
    _upload(s, "old", dt.date(2023, 1, 1), T0, status=ing.SUPERSEDED)
    _population(s, dt.date(2023, 1, 1), T0 + dt.timedelta(days=1))
    assert ing.live_uploads(s, ["old"]) == {}
    assert ing.remapped_uploads(s, ["old"]) == {}
    assert ing.stale_published(s) == []
