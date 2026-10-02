from app.services.search_service import compact_text, normalize_text, rank_matching_ids

ROWS = [
    (1, "M012345678", "DSF-001", "SOCIÉTÉ ALPHA CONGO SARL", "ALPHA", ""),
    (2, "M0123-4567 9", "DSF-002", "Beta Distribution", "BETA", "Pointe-Noire"),
    (3, "P99887766", "12", "Gamma Alpha Services", "", ""),
]


def test_normalisation_ignores_case_accents_and_separators():
    assert normalize_text("  SOCIÉTÉ   Alpha ") == "societe alpha"
    assert compact_text("M01-23 456") == "m0123456"


def test_search_by_company_name_ignores_accents_and_word_order():
    assert rank_matching_ids(ROWS, "societe alpha") == [1]
    assert rank_matching_ids(ROWS, "CONGO alpha") == [1]
    assert rank_matching_ids(ROWS, "alpha") == [1, 3]


def test_search_by_niu_ignores_separators_and_ranks_prefix_first():
    assert rank_matching_ids(ROWS, "m0123 4567 9") == [2]
    assert rank_matching_ids(ROWS, "m01234") == [1, 2]
    assert rank_matching_ids(ROWS, "99887766") == [3]


def test_exact_dsf_number_comes_first_and_wildcards_are_literal():
    assert rank_matching_ids(ROWS, "12")[0] == 3
    assert rank_matching_ids(ROWS, "dsf 002") == [2]
    assert rank_matching_ids(ROWS, "%") == []
    assert rank_matching_ids(ROWS, "_") == []


def test_extra_fields_and_empty_term():
    assert rank_matching_ids(ROWS, "pointe noire") == [2]
    assert rank_matching_ids(ROWS, "") == [1, 2, 3]
