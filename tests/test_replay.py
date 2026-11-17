"""Replay-Schritte als End-to-End-Test (Konzept §10)."""

from __future__ import annotations

from pathlib import Path

from conftest import NORDWIND, REPO

from lotse.demo.replay import load_steps, replay, workspace_files

STEPS = REPO / "demo" / "replay" / "steps"


def test_every_step_matches_expected_findings(tmp_path: Path) -> None:
    results = replay(STEPS, NORDWIND, tmp_path / "ws")
    assert len(results) == len(load_steps(STEPS))
    for r in results:
        assert r.ok, f"{r.name}: fehlend {r.missing}, unerwartet {r.unexpected}"
        assert not r.build.has_errors, r.name


def test_replay_ends_in_nordwind_end_state(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    replay(STEPS, NORDWIND, ws)
    assert workspace_files(ws) == workspace_files(NORDWIND)


def test_story_conflict_appears_and_disappears(tmp_path: Path) -> None:
    results = replay(STEPS, NORDWIND, tmp_path / "ws")
    conflict = [
        any(f.rule == "measure_definition_conflict" for f in r.build.findings) for r in results
    ]
    first, last = conflict.index(True), len(conflict) - 1 - conflict[::-1].index(True)
    assert results[first].step.act == 3
    assert results[last + 1].step.act == 5
    assert not any(conflict[last + 1 :])


def test_acts_are_monotonic_and_cover_one_to_six() -> None:
    acts = [s.act for _, s in load_steps(STEPS)]
    assert acts == sorted(acts)
    assert set(range(1, 7)) <= set(acts)
