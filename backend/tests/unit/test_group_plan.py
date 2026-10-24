"""``group_jobs.plan_grouping``: where each file and awaiting image goes in a job's grouping
phase (ADR-028). Pure: proposals from the grouping, and the job as it is, in."""

from __future__ import annotations

from backend.pipeline.group_jobs import (
    GalleryChoice,
    JobState,
    NewImportGroup,
    Proposal,
    joined_subgroups,
    plan_grouping,
)


def test_the_first_run_mints_a_group_per_proposal():
    plan = plan_grouping(
        [
            Proposal((1, 2), "Forest Road", "Czepeku", {2: "Gridded"}),
            Proposal((3,), "Sunken Keep", "Czepeku"),
        ],
        JobState(pending={1: 10, 2: 20, 3: 30}),
        first_sort_order=0,
    )
    assert plan.new_import_groups == [
        NewImportGroup(-1, "Forest Road", "Czepeku", 0),
        NewImportGroup(-2, "Sunken Keep", "Czepeku", 1),
    ]
    assert plan.item_groups == {1: -1, 2: -1, 3: -2}
    assert plan.galleries == {
        -1: GalleryChoice(None, False, "Forest Road", "Czepeku"),
        -2: GalleryChoice(None, False, "Sunken Keep", "Czepeku"),
    }
    assert plan.images == {10: (-1, None), 20: (-1, "Gridded"), 30: (-2, None)}


def test_a_proposal_without_images_gets_an_import_group_and_no_gallery_group():
    plan = plan_grouping([Proposal((1, 2), "Broken Tower", "Czepeku")], JobState())
    assert plan.item_groups == {1: -1, 2: -1}
    assert plan.galleries == {} and plan.images == {}


def test_a_matching_name_adds_to_the_existing_gallery_group():
    state = JobState(pending={1: 10, 2: 20}, existing={("Sunken Keep", "Czepeku"): 99})
    plan = plan_grouping(
        [
            Proposal((1,), "Sunken Keep", "Czepeku"),
            Proposal((2,), "Sunken Keep", "Czepeku", match_existing=False),  # not unique
        ],
        state,
    )
    assert plan.galleries[-1] == GalleryChoice(99, True)
    assert plan.galleries[-2] == GalleryChoice(None, False, "Sunken Keep", "Czepeku")


def test_an_import_group_without_a_gallery_group_takes_the_one_its_proposal_overlaps():
    """A file sorted out at first (its group had no image) is included later; the walk now
    puts it with images already in gallery group 50: it joins that group."""
    state = JobState(
        import_group_of={1: 5, 2: 7},
        pending={2: 20},
        placed={1: 50},
        gallery_of={5: 50, 7: None},
        merged=frozenset({50}),
    )
    plan = plan_grouping([Proposal((1, 2), "Forest Road", "Czepeku")], state)
    assert plan.galleries == {7: GalleryChoice(50, True)}
    assert plan.images == {20: (7, None)}


def test_an_older_import_group_without_a_gallery_group_mints_one_with_its_name():
    state = JobState(
        import_group_of={1: 7},
        pending={1: 10},
        gallery_of={7: None},
        group_names={7: ("Old Seal Name", "Tom")},
    )
    plan = plan_grouping([Proposal((1,), "Walk Name", "Tom")], state)
    assert plan.galleries == {7: GalleryChoice(None, False, "Old Seal Name", "Tom")}


def test_new_files_of_a_proposal_join_its_most_common_import_group():
    state = JobState(import_group_of={1: 8, 2: 5, 3: 5}, pending={4: 40}, gallery_of={5: 50})
    plan = plan_grouping([Proposal((1, 2, 3, 4), "Forest", "Czepeku")], state)
    assert plan.item_groups == {4: 5}
    assert plan.images == {40: (5, None)}


def test_new_import_groups_continue_the_jobs_sort_order():
    plan = plan_grouping([Proposal((1,), "A", "B")], JobState(), first_sort_order=7)
    assert plan.new_import_groups[0].sort_order == 7


# The subgroup a scene joining a map group takes (joined_subgroups)

FOLDERS = {
    1: "czepeku/keep",  # map, group 0
    2: "czepeku/keep",  # map, group 0, labelled "Gridded"
    10: "czepeku/keep",  # a scene beside the keep's maps
}


def test_a_file_takes_the_subgroup_of_its_folder_when_its_maps_share_one():
    folders = {**FOLDERS, 2: "czepeku/keep/gridded", 15: "czepeku/keep/gridded"}
    subgroups = joined_subgroups([(1, 2)], [{2: "Gridded"}], folders, {10: 0, 15: 0})
    assert subgroups == {10: None, 15: "Gridded"}


def test_mixed_labels_in_a_folder_give_no_subgroup():
    assert joined_subgroups([(1, 2)], [{2: "Night"}], FOLDERS, {10: 0}) == {10: None}
