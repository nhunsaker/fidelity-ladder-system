"""A build that reaches stage must say how to check it.

THE BUG THIS FILE EXISTS FOR. Everything in a pull-request body was evidence that the MACHINE was
satisfied — the tests it ran, the score it gave itself, the diff. None of it told a person how to
SEE the change, and the one fact they needed is the least guessable thing in the system: the
feature ships behind a flag that is OFF, so a bare stage link shows the app looking exactly as it
did before, and a reviewer reasonably concludes the deploy did nothing.

Two rules run through every test here. Nothing is invented — the criteria come from the spec's own
ACCEPTANCE section and the flag from what the branch actually added, and each absence gets its own
sentence rather than a checklist this rung made up. And none of it may speak in the ladder's own
vocabulary: a pull request is read by strangers, exactly like the visitor surface.
"""
from __future__ import annotations

from fls.rung4 import PRPackage

CRITERIA = ["the amount is visible without scrolling", "it works one-handed on a phone"]


def _pkg(**kw) -> PRPackage:
    base = dict(diff="+ a line", test_output="12 passed", eval_score="n/a", corner_cuts=[],
                description="a share sheet on the hand screen")
    base.update(kw)
    return PRPackage(**base)


def test_the_body_says_where_to_look_with_the_flag_already_turned_on():
    """THE REGRESSION TEST. A bare stage link shows the app unchanged, so the link that is worth
    giving is the one that carries the switch."""
    md = _pkg(stage_url="https://stage.example", flag="share-sheet").as_markdown()
    assert "### How to verify" in md
    assert "https://stage.example?flags-share-sheet=true" in md
    assert "https://stage.example?flags-reset" in md
    assert "off by default" in md


def test_it_says_the_switch_is_this_browser_only():
    """Otherwise the first reviewer to open it believes they have turned the feature on for
    everybody, which is the one thing the override deliberately does not do."""
    md = _pkg(stage_url="https://stage.example", flag="share-sheet").as_markdown()
    assert "this browser only" in md.lower()


def test_with_no_flag_it_does_not_invent_a_switch_to_turn_on():
    md = _pkg(stage_url="https://stage.example").as_markdown()
    assert "https://stage.example" in md
    assert "flags-" not in md.split("### How to verify")[1].split("---")[0]
    assert "no single flag was added" in md.lower()


def test_with_no_stage_it_says_there_is_nowhere_to_open_it():
    """An instance that stages nowhere is a real mode, and promising a link it does not have
    would be the same lie the 'what happens when' table was fixed for."""
    md = _pkg(flag="share-sheet").as_markdown()
    section = md.split("### How to verify")[1]
    assert "no stage is configured" in section.lower()
    assert "http" not in section.split("**What to check**")[0]


def test_each_acceptance_criterion_becomes_one_box_a_reviewer_can_tick():
    md = _pkg(stage_url="https://stage.example", flag="f", acceptance=CRITERIA).as_markdown()
    for c in CRITERIA:
        assert f"- [ ] {c}" in md


def test_a_spec_whose_criteria_are_prose_gets_a_sentence_not_a_made_up_checklist():
    """A checklist this rung invented would be indistinguishable from one the spec asked for, and
    only one of them is true — so the honest degradation says which situation this is."""
    md = _pkg(stage_url="https://stage.example", flag="f").as_markdown()
    assert "- [ ]" not in md
    assert "prose rather than a numbered list" in md


def test_the_criteria_come_from_the_specs_own_acceptance_section():
    from fls.rung1 import extract_acceptance_criteria
    spec = ("SPEC\n\nsome prose\n\nACCEPTANCE:\n"
            "1. the amount is visible without scrolling\n"
            "2. it works one-handed on a phone\n")
    assert extract_acceptance_criteria(spec) == CRITERIA


def test_how_to_verify_sits_between_what_happens_when_and_the_evidence():
    """Order is the argument: what it does, what your actions will do, how to check it — and only
    then the machine's receipts. It used to end at the receipts."""
    md = _pkg(stage_url="https://s", flag="f", acceptance=CRITERIA).as_markdown()
    assert md.index("### What happens when") < md.index("### How to verify") < md.index("**Tests:**")


def test_the_section_speaks_no_ladder_vocabulary():
    """A pull request is read by strangers. Same rule as the visitor payload, other surface."""
    from fls.demo import looks_like_machinery
    md = _pkg(stage_url="https://stage.example", flag="share-sheet",
              acceptance=CRITERIA).as_markdown()
    section = md.split("### How to verify")[1].split("---")[0]
    low = section.lower()
    for leak in ("rung", "dial", "vessel", "expedition", "anchor", "verifier", "north star"):
        assert leak not in low, f"{leak!r} reached the pull request"
    assert not looks_like_machinery(section)


# ── the flag has to be known BEFORE the body is rendered ───────────────────────────────────

class _FakeApi:
    """Records every call, answers the two the shipper makes."""

    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            return self.existing or []
        return {"html_url": "https://github.com/o/r/pull/7", "number": 7, "node_id": "n"}


def _worktree(tmp_path, flags: dict | None = None):
    """A branch that adds one flag its base does not have."""
    import json
    import subprocess
    r = tmp_path / "wt"
    r.mkdir()
    for args in (("git", "init", "-b", "main"), ("git", "config", "user.email", "t@example.invalid"),
                 ("git", "config", "user.name", "T")):
        subprocess.run(args, cwd=r, capture_output=True, check=True)
    (r / "flags.json").write_text(json.dumps({"_note": "x"}), encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=r, capture_output=True, check=True)
    subprocess.run(("git", "commit", "-m", "base"), cwd=r, capture_output=True, check=True)
    (r / "flags.json").write_text(
        json.dumps(flags if flags is not None else {"share-sheet": {"stage": False, "prod": False}}),
        encoding="utf-8")
    return r


def _shipper(tmp_path, api, wt):
    from fls.builders.ship import PullRequestShipper
    s = PullRequestShipper(str(wt), token="t", slug="o/r", line_budget=10_000, api=api)
    s.push = lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    return s


def test_the_pull_request_body_is_rendered_knowing_which_flag_was_added(tmp_path):
    """THE ORDERING BUG. `flags_added()` was asked one line AFTER `as_markdown()` had already run,
    so the body was always written by something that did not yet know the answer — and the one
    link a reviewer opens is built out of exactly that answer."""
    wt = _worktree(tmp_path)
    api = _FakeApi()
    pkg = _pkg(stage_url="https://stage.example", acceptance=CRITERIA,
               walkthrough_url="https://preview.example/9")
    out = _shipper(tmp_path, api, wt).ship(9, "exp-9", pkg, worktree=wt, title="t")

    assert out.passed, out.detail
    assert pkg.flag == "share-sheet"
    body = next(p["body"] for m, _, p in api.calls if m == "POST" and p)
    assert "https://stage.example?flags-share-sheet=true" in body


def test_two_flags_name_neither_because_naming_the_wrong_one_is_worse(tmp_path):
    wt = _worktree(tmp_path, flags={"a": {"stage": False}, "b": {"stage": False}})
    api = _FakeApi()
    pkg = _pkg(stage_url="https://stage.example", walkthrough_url="https://preview.example/9")
    _shipper(tmp_path, api, wt).ship(9, "exp-9", pkg, worktree=wt, title="t")
    assert pkg.flag == ""
    body = next(p["body"] for m, _, p in api.calls if m == "POST" and p)
    assert "no single flag was added" in body.lower()


def test_a_reused_pull_request_gets_the_new_body(tmp_path):
    """Idempotence is about not failing on GitHub's 422. It was also, by accident, freezing the
    description at whatever the FIRST attempt wrote — so a retried build showed the previous
    attempt's diff, test output and flag to the person reviewing the current one."""
    wt = _worktree(tmp_path)
    api = _FakeApi(existing=[{"number": 7, "html_url": "https://github.com/o/r/pull/7"}])
    pkg = _pkg(stage_url="https://stage.example", walkthrough_url="https://preview.example/9")
    out = _shipper(tmp_path, api, wt).ship(9, "exp-9", pkg, worktree=wt, title="t")

    assert out.passed and out.already_open
    patch = [c for c in api.calls if c[0] == "PATCH"]
    assert patch and patch[0][1] == "/repos/o/r/pulls/7"
    assert "flags-share-sheet=true" in patch[0][2]["body"]


def test_a_body_that_cannot_be_updated_does_not_fail_a_push_that_worked(tmp_path):
    """A stale description is a worse pull request; a failed ship throws away a push."""
    wt = _worktree(tmp_path)

    class Angry(_FakeApi):
        def __call__(self, method, path, payload=None):
            if method == "PATCH":
                raise RuntimeError("422 from GitHub")
            return super().__call__(method, path, payload)

    api = Angry(existing=[{"number": 7, "html_url": "https://github.com/o/r/pull/7"}])
    pkg = _pkg(stage_url="https://s", walkthrough_url="https://preview.example/9")
    out = _shipper(tmp_path, api, wt).ship(9, "exp-9", pkg, worktree=wt, title="t")
    assert out.passed and out.pr_number == 7


# ── and the same checklist on the comment that says it is live ─────────────────────────────

def test_the_staged_comment_repeats_the_checklist():
    """That comment arrives minutes after the body was written and lands at the bottom of the
    thread — which is where a reviewer is reading when the change first becomes openable."""
    from fls.github_surface import _staged_comment
    c = _staged_comment("abc1234567", "2 checks", "https://stage.example", "share-sheet", CRITERIA)
    assert "**To see it:** https://stage.example?flags-share-sheet=true" in c
    for item in CRITERIA:
        assert f"- [ ] {item}" in c


def test_the_staged_comment_with_no_criteria_grows_no_empty_section():
    from fls.github_surface import _staged_comment
    c = _staged_comment("abc1234567", "2 checks", "https://stage.example", "share-sheet", [])
    assert "What to check" not in c
    assert _staged_comment("abc1234567", "2 checks", "", "", None).endswith("no public URL.")


def test_the_criteria_reach_the_webhook_through_the_expeditions_own_facts():
    """The webhook holds a pull request and nothing else — no spec, no run. The criteria travel
    on disk or they do not travel."""
    from fls.store import artifact_facts_from
    facts = artifact_facts_from({"ship": {"pr_url": "u", "pr_number": 7},
                                 "verify": {"criteria": CRITERIA}})
    assert facts["verify"]["criteria"] == CRITERIA


def test_a_run_with_no_criteria_records_none(tmp_path):
    from fls.store import artifact_facts_from
    assert "verify" not in artifact_facts_from({"ship": {"pr_url": "u", "pr_number": 7}})


def test_criteria_for_reads_them_back_off_the_branch_name(tmp_path):
    from fls.github_surface import _criteria_for
    from fls.store import ExpeditionStore
    store = ExpeditionStore(tmp_path)
    store.save_artifact_facts(9, {"verify": {"criteria": CRITERIA}})
    assert _criteria_for(store, {"head": {"ref": "exp-9"}}) == CRITERIA
    assert _criteria_for(store, {"head": {"ref": "not-an-expedition"}}) == []
    assert _criteria_for(None, {"head": {"ref": "exp-9"}}) == []


# ── the flag is compared against what the branch will actually merge into ──────────────────

def _repo_with_stale_main(tmp_path):
    """A worktree whose LOCAL `main` is out of date and whose `origin/main` is current.

    This is not a contrived shape: the build rung works in a worktree of a long-lived vessel
    checkout that nothing ever pulls, so its local `main` is as fresh as the day it was cloned.
    """
    import json
    import subprocess

    def git(where, *args):
        return subprocess.run(("git", "-C", str(where), *args), capture_output=True, text=True,
                              check=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-b", "main")
    git(origin, "config", "user.email", "t@example.invalid")
    git(origin, "config", "user.name", "T")
    (origin / "flags.json").write_text(json.dumps({"_comment": "notes"}), encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "empty")

    work = tmp_path / "work"
    subprocess.run(("git", "clone", str(origin), str(work)), capture_output=True, check=True)
    git(work, "config", "user.email", "t@example.invalid")
    git(work, "config", "user.name", "T")

    # Four flags merge upstream. The clone never pulls — only fetches when something asks it to.
    (origin / "flags.json").write_text(json.dumps(
        {"_comment": "notes", "table-reactions": {"stage": False},
         "hero-stack-depth": {"stage": False}, "live-opponent-reads": {"stage": False},
         "weak-spot": {"stage": False}}), encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "four flags")
    git(work, "fetch", "origin")          # origin/main moves; refs/heads/main does not

    # This branch adds exactly one more.
    (work / "flags.json").write_text(json.dumps(
        {"_comment": "notes", "table-reactions": {"stage": False},
         "hero-stack-depth": {"stage": False}, "live-opponent-reads": {"stage": False},
         "weak-spot": {"stage": False}, "street-jump": {"stage": False}}), encoding="utf-8")
    return work


def test_the_flag_is_compared_against_the_ref_the_branch_will_merge_into(tmp_path):
    """THE REGRESSION TEST. Expedition 39 added `street-jump` and its pull request told the
    reviewer no flag had been added — because the local `main` in the worker's checkout still had
    none, so the branch appeared to add five and "exactly one or none" named none. The stage link
    in the same pull request had the flag right, because the webhook asks GitHub."""
    from fls.builders.ship import flags_added
    assert flags_added(_repo_with_stale_main(tmp_path)) == ["street-jump"]


def test_a_checkout_with_no_remote_still_compares_against_its_local_base(tmp_path):
    """A vessel cloned without a remote, or one whose remote is unreachable, is a real mode —
    and the local branch is then the best answer available rather than no answer."""
    from fls.builders.ship import base_ref, flags_added
    wt = _worktree(tmp_path)
    assert base_ref(wt) == "main"
    assert flags_added(wt) == ["share-sheet"]


def test_with_neither_ref_it_makes_no_claim(tmp_path):
    """Naming the wrong flag is worse than naming none, so an unanswerable question returns
    nothing rather than a guess."""
    from fls.builders.ship import base_ref, flags_added
    wt = _worktree(tmp_path)
    assert base_ref(wt, base="release") == ""
    assert flags_added(wt, base="release") == []


# ── merging lands real code, and a migration is the case the flag does not cover ───────────

def test_the_merged_row_no_longer_says_nothing_happens():
    """"Nothing anyone can see" undersold the one thing a reviewer decides: merging lands real
    code on main. The flag keeps it invisible to a player; it does not make the change not exist."""
    md = _pkg(stage_url="https://s", flag="f").as_markdown()
    row = next(line for line in md.splitlines() if line.startswith("| Merged |"))
    assert "real changes" in row and "nothing anyone can see" not in row


def test_a_migration_gets_its_own_paragraph_in_the_founders_words():
    """FOUND BY THE BATCH (PR #23): a build wrote `supabase/migrations/…daily_drill_attempts.sql`
    and the body said merging released nothing. A flag does not gate a migration."""
    md = _pkg(stage_url="https://s", flag="f",
              migrations=["supabase/migrations/20260916120000_daily_drill_attempts.sql"]).as_markdown()
    assert "Merging and deploying this PR will apply migrations to support this new feature" in md
    assert "20260916120000_daily_drill_attempts.sql" in md
    assert "can be undone if you choose not to go forward" in md
    assert md.index("| Merged |") < md.index("apply migrations") < md.index("### How to verify")


def test_no_migration_means_no_paragraph():
    assert "apply migrations" not in _pkg(stage_url="https://s", flag="f").as_markdown()


def test_the_default_globs_catch_the_shapes_that_merge_into_state():
    from fls.rung4 import migration_files
    files = ["supabase/migrations/20260916_x.sql", "prisma/migrations/1/migration.sql",
             "db/migrate/001_init.rb", "schema.sql", "src/lib/x.ts", "src/app/hands/page.tsx",
             "migrations/0002_add.py"]
    got = migration_files(files)
    assert "src/lib/x.ts" not in got and "src/app/hands/page.tsx" not in got
    for f in ("supabase/migrations/20260916_x.sql", "prisma/migrations/1/migration.sql",
              "db/migrate/001_init.rb", "schema.sql", "migrations/0002_add.py"):
        assert f in got, f


def test_a_vessel_can_name_its_own_migration_paths():
    """ANCHOR wins over the defaults, because which paths are schema is an instance fact."""
    from fls.rung4 import migration_files
    got = migration_files(["infra/ddl/users.hcl", "supabase/migrations/x.sql"],
                          globs=("infra/ddl/**",))
    assert got == ["infra/ddl/users.hcl"]


def test_the_anchor_parses_migration_paths_and_defaults_to_none():
    from fls.anchor import Vessel
    v = Vessel(name="v", kind="app", migration_paths=["supabase/migrations/**"])
    assert v.migration_paths == ["supabase/migrations/**"]
    assert Vessel(name="v", kind="app").migration_paths == []


def test_the_staged_comment_repeats_the_migration_note():
    from fls.github_surface import _staged_comment
    c = _staged_comment("abc1234567", "1 check", "https://s", "f", CRITERIA,
                        ["supabase/migrations/x.sql"])
    assert "apply migrations" in c and "`supabase/migrations/x.sql`" in c
    assert c.index("What to check") < c.index("apply migrations")
    assert "apply migrations" not in _staged_comment("abc1234567", "1 check", "https://s", "f")


def test_migrations_travel_to_the_webhook_through_the_facts(tmp_path):
    from fls.github_surface import _migrations_for
    from fls.store import ExpeditionStore, artifact_facts_from
    facts = artifact_facts_from({"ship": {"pr_url": "u", "pr_number": 7},
                                 "verify": {"criteria": CRITERIA,
                                            "migrations": ["supabase/migrations/x.sql"]}})
    assert facts["verify"]["migrations"] == ["supabase/migrations/x.sql"]
    assert facts["verify"]["criteria"] == CRITERIA
    store = ExpeditionStore(tmp_path)
    store.save_artifact_facts(9, facts)
    assert _migrations_for(store, {"head": {"ref": "exp-9"}}) == ["supabase/migrations/x.sql"]


def test_the_pull_request_lists_the_blocks_the_work_landed_in():
    md = _pkg(stage_url="https://s", flag="f", size="small",
              commits=[{"sha": "a" * 40, "subject": "the schema", "lines": 120},
                       {"sha": "b" * 40, "subject": "the screen", "lines": 240}]).as_markdown()
    assert "### Commits (2, 360 changed lines; estimated **small**)" in md
    assert "| `aaaaaaa` | the schema | 120 |" in md
    assert md.index("### Commits") < md.index("### What happens when")


def test_the_size_notes_ride_with_the_commits_and_refuse_nothing():
    md = _pkg(stage_url="https://s", flag="f", size="small",
              commits=[{"sha": "a" * 40, "subject": "all of it", "lines": 900}],
              size_notes=["estimated **small**, grew from that: 900 changed lines — **large**."]
              ).as_markdown()
    assert "grew from that" in md
    assert "parked" not in md.lower() and "refused" not in md.lower()


def test_a_package_with_no_commits_renders_no_section():
    assert "### Commits" not in _pkg(stage_url="https://s", flag="f").as_markdown()
