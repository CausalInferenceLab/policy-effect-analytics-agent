from core.discovery.ontology import check_links, load_datasets, load_issues


def test_catalog_links_are_consistent():
    assert check_links() == []


def test_every_issue_has_outcome_data_and_source():
    by_id = {d.id: d for d in load_datasets()}
    for i in load_issues():
        assert i.source.startswith("https://")
        assert any("outcome" in by_id[x].roles for x in i.datasets), i.id
