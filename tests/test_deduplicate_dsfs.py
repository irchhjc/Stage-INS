from types import SimpleNamespace

from app.maintenance.deduplicate_dsfs import analyze_duplicates, build_report, duplicate_key


def _dsf(identifier, niu, year, numero, status, assigned_to_id=None):
    return SimpleNamespace(
        id=identifier,
        niu=niu,
        annee=year,
        numero_dsf=numero,
        status=status,
        assigned_to_id=assigned_to_id,
    )


def test_niu_year_groups_are_normalized_and_separate_years():
    first = _dsf(1, " NIU-01 ", "2025", "A", "completed")
    duplicate = _dsf(2, "niu-01", 2025, "B", "in_progress")
    another_year = _dsf(3, "NIU-01", "2024", "C", "not_started")

    assert duplicate_key(first, "niu-year") == ("niu-01", "2025")
    groups, ignored = analyze_duplicates([first, duplicate, another_year])

    assert ignored == 0
    assert len(groups) == 1
    assert groups[0].completed_ids == (1,)
    assert groups[0].deletion_candidate_ids == (2,)


def test_groups_without_completed_dsf_are_protected():
    rows = [
        _dsf(1, "NIU-02", "2025", "A", "not_started"),
        _dsf(2, "NIU-02", "2025", "B", "in_progress", assigned_to_id=8),
    ]

    report = build_report(rows)

    assert report["groups_without_completed_dsf_protected"] == 1
    assert report["deletion_candidates"] == 0
    assert report["candidate_ids"] == []


def test_only_non_completed_siblings_of_completed_dsf_are_candidates():
    rows = [
        _dsf(1, "NIU-03", "2025", "A", "completed", assigned_to_id=4),
        _dsf(2, "NIU-03", "2025", "B", "completed", assigned_to_id=5),
        _dsf(3, "NIU-03", "2025", "C", "in_progress", assigned_to_id=6),
        _dsf(4, "NIU-03", "2025", "D", "not_started"),
    ]

    report = build_report(rows)

    assert report["deletion_candidates"] == 2
    assert report["candidate_ids"] == [3, 4]
    assert report["assigned_deletion_candidates"] == 1
    assert report["unassigned_deletion_candidates"] == 1
    assert report["candidate_statuses"] == {"in_progress": 1, "not_started": 1}


def test_blank_keys_are_ignored_and_numero_mode_is_supported():
    rows = [
        _dsf(1, "", "2025", " DSF-10 ", "completed"),
        _dsf(2, None, "2025", "dsf-10", "not_started"),
    ]

    niu_groups, ignored = analyze_duplicates(rows, "niu-year")
    numero_groups, numero_ignored = analyze_duplicates(rows, "numero-dsf")

    assert niu_groups == []
    assert ignored == 2
    assert numero_ignored == 0
    assert numero_groups[0].deletion_candidate_ids == (2,)
