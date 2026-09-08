#!/usr/bin/env python3
"""Tests for tools/universe_history.py: point-in-time membership from a git history (offline, temp repos)."""

from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import universe_history as uh  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@x"}


def _commit(repo, rows, day):
    os.makedirs(repo / "data", exist_ok=True)
    (repo / "data" / "constituents.csv").write_text("Symbol,Name,Sector\n" + "".join(f"{s},{s} Inc,X\n" for s in rows))
    env = {**ENV, "GIT_AUTHOR_DATE": f"{day}T12:00:00Z", "GIT_COMMITTER_DATE": f"{day}T12:00:00Z"}
    subprocess.run(["git", "-C", str(repo), "add", "data/constituents.csv"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"update {day}"], check=True, env=env)


@pytest.fixture
def dataset_repo(tmp_path):
    """Three snapshots: A, B, BRK.B (2020-01-15); A, C, BRK.B (2020-06-15); A, C, D (2021-01-15)."""
    repo = tmp_path / "dataset"
    subprocess.run(["git", "init", "-q", "-b", uh.DATASET_BRANCH, str(repo)], check=True)
    _commit(repo, ["A", "B", "BRK.B"], "2020-01-15")
    _commit(repo, ["A", "C", "BRK.B"], "2020-06-15")
    (repo / "README.md").write_text("unrelated\n")                       # a commit that does not touch the file
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "docs"], check=True,
                   env={**ENV, "GIT_AUTHOR_DATE": "2020-09-01T12:00:00Z", "GIT_COMMITTER_DATE": "2020-09-01T12:00:00Z"})
    _commit(repo, ["A", "C", "D"], "2021-01-15")
    return repo


def test_history_lists_only_commits_touching_the_file(dataset_repo):
    entries = uh.history(str(dataset_repo))
    assert [d.isoformat() for d, _ in entries] == ["2020-01-15", "2020-06-15", "2021-01-15"]
    assert len({sha for _, sha in entries}) == 3
    assert uh.file_at(str(dataset_repo), entries[0][1]).startswith("Symbol,Name,Sector\nA,")


def test_membership_picks_the_snapshot_in_force(dataset_repo):
    m = uh.Membership(uh.history(str(dataset_repo)), lambda sha: uh.file_at(str(dataset_repo), sha))
    assert m.members("2020-03-01") == {"A", "B", "BRK-B"}                 # Yahoo format, like the scanner
    assert m.members("2020-06-15") == {"A", "C", "BRK-B"}                 # the commit day itself: that snapshot
    assert m.members(pd.Timestamp("2020-12-31")) == {"A", "C", "BRK-B"}   # the docs commit changed nothing
    assert m.members(pd.Timestamp("2022-01-01").date()) == {"A", "C", "D"}
    assert m.before_history == 0
    assert m.members("2019-01-01") == {"A", "B", "BRK-B"} and m.before_history == 1   # earliest snapshot, flagged
    assert m.union(["2020-03-01", "2022-01-01"]) == {"A", "B", "BRK-B", "C", "D"}
    days = pd.bdate_range("2020-05-01", "2021-02-28")
    cov = m.coverage(days, available={"A", "C", "ZZZ"})
    # 2020 spans snapshots 1 and 2 (A, B, C, BRK-B); 2021 still runs on snapshot 2 until 2021-01-15, then
    # snapshot 3, so its union is A, C, BRK-B, D.  ZZZ has data but was never a member.
    assert cov == [{"year": 2020, "members": 4, "with_data": 2, "share": 0.5},
                   {"year": 2021, "members": 4, "with_data": 2, "share": 0.5}]
    assert m.coverage(pd.bdate_range("2021-01-15", "2021-02-28"), available={"A", "C"}) == [
        {"year": 2021, "members": 3, "with_data": 2, "share": 0.667}]
    with pytest.raises(ValueError):
        uh.Membership([], lambda sha: "")


def test_membership_reads_each_snapshot_once():
    calls = []

    def load(sha):
        calls.append(sha)
        return {"s1": "Symbol\nA\nB\n", "s2": "Symbol\nB\n"}[sha]

    m = uh.Membership([(pd.Timestamp("2024-01-01").date(), "s1"), (pd.Timestamp("2024-07-01").date(), "s2")], load)
    assert m.members("2024-03-01") == {"A", "B"} and m.members("2024-04-01") == {"A", "B"}
    assert m.members("2024-08-01") == {"B"} and calls == ["s1", "s2"]


def test_clone_history_creates_a_bare_clone_and_reuses_it(dataset_repo, tmp_path):
    cache = tmp_path / "cache"
    clone = uh.clone_history(str(cache), repo=str(dataset_repo))
    assert os.path.isdir(clone) and os.path.isfile(os.path.join(clone, "HEAD"))
    assert [d.isoformat() for d, _ in uh.history(clone)] == ["2020-01-15", "2020-06-15", "2021-01-15"]
    _commit(dataset_repo, ["A", "E"], "2021-06-15")                       # upstream moves on
    assert uh.clone_history(str(cache), repo=str(dataset_repo)) == clone   # same directory ...
    assert uh.history(clone)[-1][0].isoformat() == "2021-06-15"          # ... refreshed by the fetch
    assert uh.clone_history(str(cache), repo="/nonexistent/repo.git", refresh=True) == clone   # offline: warns, serves
