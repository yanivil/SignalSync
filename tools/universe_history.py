#!/usr/bin/env python3
"""Point-in-time S&P 500 membership from the git history of the constituent dataset.

Why: the replays run on today's constituents, so every symbol that left the
index during the replayed years (acquired, delisted, demoted) is missing and
every symbol that joined is present before it joined.  That is survivorship
bias, and it flatters bullish patterns.  The dataset the scanner already
trusts, ``datasets/s-and-p-500-companies``, keeps ``data/constituents.csv``
under version control (195 commits since 2012: about weekly since 2020, a
handful a year before, one a year in 2017-2019), so the membership as of any
date is the file at the last commit on or before that date.  Its 2016
snapshot holds 179 symbols that are not members today.

A bare, blobless clone (commits and trees only, under 1 MB) gives the commit
list; each snapshot's blob is fetched the first time it is read.  The clone is
cached in a directory and refreshed with a fetch on later runs.

Two limits remain and the backtest states them: the dataset records a change
some days after the index does, and a symbol that no longer trades, or was
renamed, has no Yahoo history, so the replay still cannot trade it.  The
coverage table in the backtest report says how many members each year that
affected.
"""

from __future__ import annotations

import bisect
import datetime as dt
import logging
import os
import subprocess
import sys
from typing import Any, Callable, Container, Dict, FrozenSet, Iterable, List, Sequence, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scan  # noqa: E402

log = logging.getLogger("universe")

DATASET_REPO = "https://github.com/datasets/s-and-p-500-companies.git"
DATASET_PATH = "data/constituents.csv"
DATASET_BRANCH = "main"


def clone_history(cache_dir: str, repo: str = DATASET_REPO, refresh: bool = True) -> str:
    """Bare, blobless clone of the dataset under ``cache_dir``, reused (and fetched) when present.

    :param cache_dir: Directory that holds the clone; created if missing.
    :param repo: Repository URL (a local path in tests).
    :param refresh: Fetch the branch when the clone already exists; a failed
        fetch (offline) is logged and the cached history serves.
    :returns: The clone directory.
    :raises subprocess.CalledProcessError: when the first clone fails (no
        network, no git).
    """
    dest = os.path.join(cache_dir, "s-and-p-500-companies.git")
    if not os.path.isdir(dest):
        os.makedirs(cache_dir, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--bare", "--filter=blob:none", repo, dest], check=True)
    elif refresh:
        try:
            subprocess.run(["git", "-C", dest, "fetch", "--quiet", repo,
                            f"+refs/heads/{DATASET_BRANCH}:refs/heads/{DATASET_BRANCH}"],
                           check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            log.warning("could not refresh the constituent history, using the cached one: %s", exc)
    return dest


def history(clone: str, path: str = DATASET_PATH) -> List[Tuple[dt.date, str]]:
    """``(commit date, sha)`` for every commit on the branch that touched ``path``, oldest first."""
    out = subprocess.run(["git", "-C", clone, "log", "--reverse", "--format=%H %cs", DATASET_BRANCH, "--", path],
                         check=True, capture_output=True, text=True).stdout
    entries = []
    for line in out.splitlines():
        sha, day = line.split()
        entries.append((dt.date.fromisoformat(day), sha))
    return entries


def file_at(clone: str, sha: str, path: str = DATASET_PATH) -> str:
    """The file's text at ``sha``; in a blobless clone the blob is fetched on first use."""
    return subprocess.run(["git", "-C", clone, "show", f"{sha}:{path}"],
                          check=True, capture_output=True, text=True).stdout


def _as_date(day: Any) -> dt.date:
    if isinstance(day, str):
        return dt.date.fromisoformat(day[:10])
    if isinstance(day, dt.datetime) or hasattr(day, "date"):    # datetime, pandas Timestamp
        return day.date()
    return day


class Membership:
    """Members as of any date: the snapshot at the last commit on or before it.

    :param entries: :func:`history` output, oldest first.
    :param load: ``sha -> csv text``, e.g. :func:`file_at` bound to a clone; a
        dict lookup in tests.  Snapshots are parsed once and cached per sha.

    A date before the first commit gets the first snapshot, the best there is,
    and is counted in ``before_history``.
    """

    def __init__(self, entries: Sequence[Tuple[dt.date, str]], load: Callable[[str], str]) -> None:
        if not entries:
            raise ValueError("no constituent history")
        self.entries = sorted(entries)
        self._dates = [d for d, _ in self.entries]
        self._load = load
        self._cache: Dict[str, FrozenSet[str]] = {}
        self.before_history = 0

    def sha_asof(self, day: Any) -> str:
        """The commit whose snapshot is in force on ``day``."""
        i = bisect.bisect_right(self._dates, _as_date(day)) - 1
        if i < 0:
            self.before_history += 1
            i = 0
        return self.entries[i][1]

    def members(self, day: Any) -> FrozenSet[str]:
        """Symbols in Yahoo format (``BRK-B``) that were members on ``day``."""
        sha = self.sha_asof(day)
        if sha not in self._cache:
            self._cache[sha] = frozenset(scan.symbols_from_csv(self._load(sha)))
        return self._cache[sha]

    def union(self, days: Iterable[Any]) -> Set[str]:
        """Every symbol that was a member on any of ``days``: what a replay over them has to download."""
        out: Set[str] = set()
        for day in days:
            out |= self.members(day)
        return out

    def coverage(self, days: Iterable[Any], available: Container[str]) -> List[Dict[str, Any]]:
        """Per calendar year of ``days``: members seen (union), how many have price data, and the share."""
        by_year: Dict[int, Set[str]] = {}
        for day in days:
            by_year.setdefault(_as_date(day).year, set()).update(self.members(day))
        out = []
        for year in sorted(by_year):
            members = by_year[year]
            with_data = sum(1 for s in members if s in available)
            out.append({"year": year, "members": len(members), "with_data": with_data,
                        "share": round(with_data / len(members), 3) if members else None})
        return out
