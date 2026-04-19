"""
Per-market parameter profiles.

Motivation
----------
The filter-ablation experiment (experiments/filter_ablation.py) made clear
that no single Params configuration is simultaneously best across every
(symbol, timeframe) pair. The ADX min=20 filter that lifts BTC/USDT 4h WF
score to 0.30 actively HURTS the fast-donchian config that works on
ETH/USDT 4h. Baking one market's tuned settings into config.py as
universal defaults would silently degrade every other market.

Design
------
A "profile" is a named JSON document that specifies a partial Params
override set plus metadata describing where it came from. Profiles live
in `profiles/*.json`. Only the fields that differ from the config.py
defaults need to be listed — every other field inherits.

Schema:
    {
        "name": "btc-4h-adx",
        "description": "BTC/USDT 4h EMA crossover with ADX regime filter",
        "source": "experiments/filter_ablation.py B1+V3 (WF 0.30)",
        "created_at": "2026-04-18T12:00:00Z",
        "parent": null,                     # previous version's name (optional)
        "changelog": [                      # user-authored iteration log
            {"at": "...", "message": "initial version"}
        ],
        "performance": {                    # baseline the profile was saved with
            "kind": "backtest",
            "run_id": "abc123",             # optional reference to /runs
            "summary": {"trades": 47, "return_pct": 12.3, ...}
        },
        "params": {
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "strategy": "ema_crossover",
            "ema_short": 12,
            ...
        }
    }

All fields except `name` and `params` are optional; `parent`,
`changelog`, and `performance` were added later and existing files
without them load cleanly.

Precedence
----------
When a CLI invocation passes `--profile <name>`, the profile's `params`
dict is applied AFTER argparse has built the initial Params. This means
profile values override both config.py defaults AND any explicit CLI
flags the user passed on the same command line. Rationale: a profile is
a complete, reproducible preset — mixing a half-applied profile with
manual overrides is a recipe for misleading results. To try a variant,
save a new profile (or invoke without --profile and use flags).

Keep-up workflow
----------------
1. Run a sweep / walk-forward for a (symbol, timeframe) and pick the WF
   winner.
2. Save its Params as a profile via `save_profile(name, params, ...)`
   (CLI: `python -m profiles save <name>` — see __main__ block below).
3. Commit the JSON. That market now has a reproducible, version-
   controlled best config.
4. When a better config emerges, save it under a new name (e.g.
   `btc-4h-adx-v2`) and keep the old one around for A/B comparisons.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import asdict, replace, fields
from typing import Any

from backtest import Params


# --------------------------------------------------------- disk layout -----

PROFILES_DIR = os.environ.get(
    "TDX_PROFILES_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles"),
)


def _ensure_dir() -> None:
    os.makedirs(PROFILES_DIR, exist_ok=True)


_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _validate_name(name: str) -> None:
    """Profile names double as filenames; keep them restrictive.

    No slashes, no leading dots, no whitespace. Length capped at 64 so
    we never run into path-length limits on Windows.
    """
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid profile name {name!r}: must match {_NAME_RE.pattern}"
        )


def _profile_path(name: str) -> str:
    _validate_name(name)
    return os.path.join(PROFILES_DIR, f"{name}.json")


# ------------------------------------------------------------ helpers -----

# Names of Params fields that should NOT be persisted in a profile — these
# are operational knobs (account state, fees, universe), not strategy
# parameters. Keeping them out means profiles stay portable across
# accounts and exchanges.
_RUNTIME_ONLY_FIELDS = frozenset({
    "initial_balance",
    "bars",  # sweep/backtest bar count is a run concern, not a profile concern
})


def _params_field_names() -> set[str]:
    return {f.name for f in fields(Params)}


def _clean_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown keys and runtime-only fields.

    We're strict about unknown keys to catch typos in hand-edited JSON
    before they silently do nothing — raising on first unknown key is
    the friendlier failure mode.
    """
    known = _params_field_names()
    cleaned: dict[str, Any] = {}
    for k, v in overrides.items():
        if k in _RUNTIME_ONLY_FIELDS:
            continue
        if k not in known:
            raise ValueError(
                f"profile contains unknown Params field: {k!r}. "
                f"Valid fields: {sorted(known)}"
            )
        cleaned[k] = v
    return cleaned


# ----------------------------------------------------------- public API -----


def list_profiles() -> list[str]:
    """Return sorted names of all profiles on disk.

    Directory is auto-created on first access so a fresh checkout works
    without a separate setup step.
    """
    _ensure_dir()
    names: list[str] = []
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith(".json"):
            names.append(fname[:-5])
    return sorted(names)


def load_profile(name: str) -> dict[str, Any]:
    """Read the full JSON document (not just params) for a profile.

    Back-compat: profiles saved before `parent` / `changelog` /
    `performance` were added on disk return with those keys filled in
    to their empty defaults, so consumers never need to branch on
    "which schema version am I looking at?".
    """
    path = _profile_path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"profile {name!r} not found at {path}. "
            f"Available: {list_profiles()}"
        )
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if "params" not in doc or not isinstance(doc["params"], dict):
        raise ValueError(f"profile {name!r} missing 'params' object")
    _clean_overrides(doc["params"])  # validation only
    # Upgrade-in-memory so every caller sees a consistent shape.
    doc.setdefault("parent", None)
    doc.setdefault("changelog", [])
    doc.setdefault("performance", None)
    return doc


def apply_profile(params: Params, name: str) -> Params:
    """Return a new Params with the profile's overrides applied.

    Fields not mentioned in the profile are inherited from `params`
    (which is typically built from config.py defaults + any CLI flags).
    """
    doc = load_profile(name)
    overrides = _clean_overrides(doc["params"])
    return replace(params, **overrides)


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_performance(perf: Any) -> dict[str, Any] | None:
    """Clean + lightly validate a performance payload.

    Accepts `None` (nothing attached), or a dict with at minimum a
    `summary` dict. Unknown top-level keys are dropped so the UI can
    pass through a "kind" without us accumulating junk.
    """
    if perf is None:
        return None
    if not isinstance(perf, dict):
        raise ValueError("performance must be an object or null")
    summary = perf.get("summary")
    if summary is not None and not isinstance(summary, dict):
        raise ValueError("performance.summary must be an object")
    out: dict[str, Any] = {}
    # kind is free-form ("backtest" | "walkforward" | "custom"); we just
    # echo it back so the UI can pick the right icon / label.
    if "kind" in perf and perf["kind"]:
        out["kind"] = str(perf["kind"])
    if "run_id" in perf and perf["run_id"]:
        out["run_id"] = str(perf["run_id"])
    if summary is not None:
        out["summary"] = dict(summary)
    if "recorded_at" in perf and perf["recorded_at"]:
        out["recorded_at"] = str(perf["recorded_at"])
    else:
        out["recorded_at"] = _utcnow_iso()
    return out


def _normalise_changelog(entries: Any) -> list[dict[str, Any]]:
    """Each entry must have a `message`; `at` is filled in if missing.

    We're lenient on format because changelog is user-authored text;
    the only hard invariant is the shape, not the content.
    """
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ValueError("changelog must be a list")
    out: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError("changelog entries must be objects")
        msg = e.get("message")
        if not isinstance(msg, str) or not msg.strip():
            raise ValueError("changelog entry missing 'message'")
        out.append({
            "at": str(e.get("at")) if e.get("at") else _utcnow_iso(),
            "message": msg.strip(),
        })
    return out


def save_profile(
    name: str,
    params: Params,
    *,
    description: str = "",
    source: str = "",
    parent: str | None = None,
    changelog_message: str | None = None,
    performance: dict[str, Any] | None = None,
    include_defaults: bool = False,
) -> str:
    """Persist a Params snapshot as a named profile.

    Optional metadata:
        parent:            name of the profile this version iterates on;
                           validated only for shape (not existence), so
                           old profiles deleted mid-lineage don't error.
        changelog_message: seeds the `changelog` list with a single
                           entry. Use `append_changelog` for subsequent
                           edits in-place.
        performance:       baseline stats captured at save time. See
                           `_normalise_performance` for accepted shape.

    By default only fields that differ from a fresh Params() (i.e. from
    config.py defaults) are written — this keeps profiles minimal and
    focused on "what's different about this market". Pass
    include_defaults=True to dump the full param set (useful for
    creating standalone profiles that don't depend on config.py).

    Returns the path the profile was written to.
    """
    _validate_name(name)
    if parent is not None:
        # Same charset rule as the profile name itself.
        _validate_name(parent)
    _ensure_dir()

    payload = asdict(params)
    if not include_defaults:
        baseline = asdict(Params())
        payload = {k: v for k, v in payload.items() if baseline.get(k) != v}
    payload = _clean_overrides(payload)

    changelog: list[dict[str, Any]] = []
    if changelog_message and changelog_message.strip():
        changelog.append({
            "at": _utcnow_iso(),
            "message": changelog_message.strip(),
        })

    doc: dict[str, Any] = {
        "name": name,
        "description": description,
        "source": source,
        "parent": parent,
        "created_at": _utcnow_iso(),
        "changelog": changelog,
        "performance": _normalise_performance(performance),
        "params": payload,
    }
    path = _profile_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=False)
    return path


def update_profile(
    name: str,
    *,
    description: str | None = None,
    source: str | None = None,
    performance: dict[str, Any] | None = None,
    append_message: str | None = None,
    clear_performance: bool = False,
) -> dict[str, Any]:
    """Amend an existing profile in place.

    This is the "keep iterating on the same row" path; for a proper
    new version with a parent link, call `save_profile` with a fresh
    name and `parent=<old>`. We deliberately do NOT let update_profile
    change `params` — editing the config without bumping the name
    throws away reproducibility, which is the whole point of profiles.

    Any field passed as None is left untouched; `clear_performance=True`
    is the explicit way to drop the performance baseline.

    Returns the updated document.
    """
    doc = load_profile(name)

    if description is not None:
        doc["description"] = description
    if source is not None:
        doc["source"] = source

    if clear_performance:
        doc["performance"] = None
    elif performance is not None:
        doc["performance"] = _normalise_performance(performance)

    if append_message and append_message.strip():
        entries = doc.get("changelog") or []
        entries.append({
            "at": _utcnow_iso(),
            "message": append_message.strip(),
        })
        doc["changelog"] = entries

    # Normalise any stored changelog so pre-existing profiles without
    # the field get upgraded on first edit.
    doc["changelog"] = _normalise_changelog(doc.get("changelog"))

    path = _profile_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=False)
    return doc


def delete_profile(name: str) -> None:
    path = _profile_path(name)
    if os.path.exists(path):
        os.remove(path)


# ------------------------------------------------------------- CLI entry ---
# `python -m profiles list|show|save|delete ...`. This is a minimal admin
# tool — the dashboard will grow a richer UI for profile management later.

def _cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Manage per-market profiles.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all profiles")

    s_show = sub.add_parser("show", help="Dump a profile to stdout")
    s_show.add_argument("name")

    s_del = sub.add_parser("delete", help="Remove a profile")
    s_del.add_argument("name")

    s_save = sub.add_parser(
        "save", help="Save the CURRENT config.py defaults under a given name"
    )
    s_save.add_argument("name")
    s_save.add_argument("--description", default="")
    s_save.add_argument("--source", default="config.py snapshot")
    s_save.add_argument("--full", action="store_true",
                         help="Include every field, not just deltas")

    args = p.parse_args()

    if args.cmd == "list":
        for n in list_profiles():
            print(n)
    elif args.cmd == "show":
        doc = load_profile(args.name)
        print(json.dumps(doc, indent=2))
    elif args.cmd == "delete":
        delete_profile(args.name)
        print(f"deleted {args.name}")
    elif args.cmd == "save":
        path = save_profile(
            args.name,
            Params(),
            description=args.description,
            source=args.source,
            include_defaults=args.full,
        )
        print(f"saved -> {path}")


if __name__ == "__main__":
    _cli()
