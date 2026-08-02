"""Research session history utilities."""
from __future__ import annotations

import json
from pathlib import Path

from research_db.storage import ResearchStorage


class ResearchHistory:
    """Query and compare historical research sessions."""

    def __init__(self, storage: ResearchStorage) -> None:
        self.storage = storage

    def recent_sessions(self, limit: int = 20):
        return self.storage.get_sessions(limit=limit)

    def best_strategies(self, metric: str = "sharpe_ratio", limit: int = 10):
        return self.storage.get_best_by(metric=metric, limit=limit)

    def compare_sessions(self, sid1: str, sid2: str) -> dict:
        """Return side-by-side comparison of two research sessions."""
        s1 = self.storage.get_session(sid1)
        s2 = self.storage.get_session(sid2)
        r1 = self.storage.get_strategy_results(session_id=sid1)
        r2 = self.storage.get_strategy_results(session_id=sid2)

        def best(results, metric):
            valid = [r for r in results if getattr(r, metric, None) is not None]
            if not valid:
                return None
            return max(valid, key=lambda r: getattr(r, metric))

        return {
            "session_1": {
                "id"          : sid1,
                "started_at"  : s1.started_at if s1 else None,
                "n_passed"    : s1.n_passed   if s1 else 0,
                "n_rejected"  : s1.n_rejected if s1 else 0,
                "best_sharpe" : getattr(best(r1, "sharpe_ratio"), "sharpe_ratio", None),
                "best_cagr"   : getattr(best(r1, "cagr"), "cagr", None),
            },
            "session_2": {
                "id"          : sid2,
                "started_at"  : s2.started_at if s2 else None,
                "n_passed"    : s2.n_passed   if s2 else 0,
                "n_rejected"  : s2.n_rejected if s2 else 0,
                "best_sharpe" : getattr(best(r2, "sharpe_ratio"), "sharpe_ratio", None),
                "best_cagr"   : getattr(best(r2, "cagr"), "cagr", None),
            },
        }

    def performance_decay(
        self,
        strategy_class: str,
        n_sessions: int = 10,
    ) -> list[dict]:
        """Track how a strategy's best Sharpe changed across sessions."""
        sessions = self.storage.get_sessions(limit=n_sessions)
        history  = []
        for s in sessions:
            results = self.storage.get_strategy_results(session_id=s.session_id)
            cls_results = [r for r in results if r.strategy_class == strategy_class]
            if cls_results:
                best = max(cls_results, key=lambda r: r.sharpe_ratio or 0)
                history.append({
                    "session_id"  : s.session_id,
                    "started_at"  : s.started_at,
                    "sharpe_ratio": best.sharpe_ratio,
                    "cagr"        : best.cagr,
                    "max_dd"      : best.max_drawdown_pct,
                })
        return history
