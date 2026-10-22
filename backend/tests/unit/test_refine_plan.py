"""``refine_groups.plan_merges``: what grouping refinement changes (ADR-028).

Pure: proposals from the content walk, and the gallery as it is, in; merges and subgroup
labels out. The rules (design/variant-grouping.md §3): merge-only, only eligible groups,
the largest group survives, nothing is split, and stale membership is simply what the plan
is made against.
"""

from __future__ import annotations

import pytest

from backend.pipeline.refine_groups import GroupMerge, Membership, MergePlan, Proposal, plan_merges


def membership(
    groups: dict[int, int | None],
    eligible: set[int] | None = None,
    sizes: dict[int, int] | None = None,
    subgroups: dict[int, str | None] | None = None,
) -> Membership:
    """``groups``: image → group. Every group is eligible and as large as its images here,
    unless given."""
    present = {g for g in groups.values() if g is not None}
    eligible = present if eligible is None else eligible
    counted = {g: sum(1 for x in groups.values() if x == g) for g in eligible}
    return Membership(
        group_of=groups,
        subgroup_of=subgroups or dict.fromkeys(groups),
        eligible=eligible,
        sizes={**counted, **(sizes or {})},
    )


def merges(plan: MergePlan) -> list[tuple[int, tuple[int, ...]]]:
    return [(m.survivor, m.merged) for m in plan.merges]


def test_a_proposal_over_two_groups_merges_them():
    plan = plan_merges(
        [Proposal((1, 2, 3), name="Forest Road", reasons={"x1 rendition": 1})],
        membership({1: 10, 2: 10, 3: 20}),
    )
    assert plan.merges == (GroupMerge(10, (20,), "Forest Road", ("x1 rendition",)),)
    assert plan.merged_groups == 1
    assert plan.subgroups == {} and plan.conflicted == frozenset()


def test_proposals_within_one_group_change_nothing():
    plan = plan_merges([Proposal((1, 2)), Proposal((3,))], membership({1: 10, 2: 10, 3: 20}))
    assert plan == MergePlan()


def test_the_largest_group_survives_counting_images_from_other_imports():
    # Group 30 holds one of this job's images but four images in all
    plan = plan_merges(
        [Proposal((1, 2, 3, 4))],
        membership({1: 10, 2: 10, 3: 20, 4: 30}, sizes={30: 4}),
    )
    assert merges(plan) == [(30, (10, 20))]


def test_a_tie_goes_to_the_lowest_id():
    plan = plan_merges([Proposal((1, 2, 3))], membership({1: 12, 2: 11, 3: 13}))
    assert merges(plan) == [(11, (12, 13))]


def test_several_proposals_merge_independently():
    plan = plan_merges(
        [Proposal((1, 2)), Proposal((3, 4)), Proposal((5,))],
        membership({1: 10, 2: 11, 3: 20, 4: 21, 5: 30}),
    )
    assert merges(plan) == [(10, (11,)), (20, (21,))]


def test_ineligible_groups_never_move_nor_take_others_in():
    # 20 was edited by the user (or existed before the import): images in it stay, and it
    # isn't a survivor either, though it is the largest
    plan = plan_merges(
        [Proposal((1, 2, 3, 4))],
        membership({1: 10, 2: 11, 3: 20, 4: 20}, eligible={10, 11}),
    )
    assert merges(plan) == [(10, (11,))]


def test_one_eligible_group_beside_ineligible_ones_is_left_alone():
    plan = plan_merges([Proposal((1, 2))], membership({1: 10, 2: 20}, eligible={10}))
    assert plan.merges == ()


def test_images_in_no_group_or_deleted_meanwhile_are_ignored():
    plan = plan_merges(
        [Proposal((1, 2, 3, 4))],
        # 3 is in no group; 4 was deleted (absent from the gallery)
        membership({1: 10, 2: 11, 3: None}),
    )
    assert merges(plan) == [(10, (11,))]


def test_a_group_the_walk_splits_is_left_exactly_as_it_is():
    """Group 10 holds images of two proposals: merging both into it would chain them."""
    plan = plan_merges(
        [Proposal((1, 3), subgroups={1: "Night"}), Proposal((2, 4), subgroups={2: "Day"})],
        membership({1: 10, 2: 10, 3: 20, 4: 30}),
    )
    assert plan.conflicted == frozenset({10})
    assert plan.merges == ()  # each proposal touches one unconflicted group only
    assert plan.subgroups == {}  # nor relabelled


def test_a_conflict_blocks_only_the_split_group():
    plan = plan_merges(
        [Proposal((1, 3, 5)), Proposal((2, 4, 6))],
        membership({1: 10, 2: 10, 3: 20, 4: 30, 5: 21, 6: 31}),
    )
    assert plan.conflicted == frozenset({10})
    assert merges(plan) == [(20, (21,)), (30, (31,))]


def test_an_ineligible_group_spanning_proposals_is_no_conflict():
    plan = plan_merges(
        [Proposal((1, 3, 5)), Proposal((2, 4))],
        membership({1: 99, 2: 99, 3: 10, 4: 20, 5: 11}, eligible={10, 11, 20}),
    )
    assert plan.conflicted == frozenset()
    assert merges(plan) == [(10, (11,))]


def test_never_a_split():
    """Every image of a merged group ends up in the survivor: groups move whole."""
    groups = {1: 10, 2: 10, 3: 11, 4: 12, 5: 12, 6: 13}
    plan = plan_merges([Proposal((1, 2, 3)), Proposal((4, 5, 6))], membership(groups))
    final = dict(groups)
    for merge in plan.merges:
        for image, group in groups.items():
            if group in merge.merged:
                final[image] = merge.survivor
    # Images together before are together after
    for a in groups:
        for b in groups:
            if groups[a] == groups[b]:
                assert final[a] == final[b]
    assert merges(plan) == [(10, (11,)), (12, (13,))]


def test_subgroups_follow_the_proposal():
    plan = plan_merges(
        [Proposal((1, 2, 3), subgroups={1: "Gridded", 2: "Gridless"})],
        membership(
            {1: 10, 2: 11, 3: 10},
            subgroups={1: None, 2: "Gridless", 3: "Old label"},
        ),
    )
    # 2 already has its label; 3 joins the main body
    assert plan.subgroups == {1: "Gridded", 3: None}


def test_subgroups_are_updated_without_a_merge():
    plan = plan_merges(
        [Proposal((1, 2), subgroups={2: "Floor 2"})],
        membership({1: 10, 2: 10}),
    )
    assert plan.merges == () and plan.subgroups == {2: "Floor 2"}


def test_subgroups_in_ineligible_groups_are_never_touched():
    plan = plan_merges(
        [Proposal((1, 2), subgroups={1: "Night", 2: "Day"})],
        membership({1: 10, 2: 20}, eligible={20}, subgroups={1: "Mine", 2: None}),
    )
    assert plan.subgroups == {2: "Day"}


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_the_plan_does_not_depend_on_proposal_order(order):
    proposals = [Proposal((1, 2)), Proposal((3, 4))]
    plan = plan_merges([proposals[i] for i in order], membership({1: 10, 2: 11, 3: 12, 4: 13}))
    assert sorted(merges(plan)) == [(10, (11,)), (12, (13,))]


def test_planning_again_after_the_merge_is_a_no_op():
    """Refinement is idempotent: the merged gallery yields an empty plan."""
    proposals = [Proposal((1, 2, 3), subgroups={3: "Night"})]
    first = plan_merges(proposals, membership({1: 10, 2: 11, 3: 11}))
    assert merges(first) == [(11, (10,))]
    again = plan_merges(
        proposals, membership({1: 11, 2: 11, 3: 11}, subgroups={1: None, 2: None, 3: "Night"})
    )
    assert again == MergePlan()
