from mitra_app.search import SearchResult, format_search_results


def test_format_search_results_empty():
    assert format_search_results([]) == "No results found"


def test_format_search_results_returns_expected_shape():
    text = format_search_results(
        [
            SearchResult(title="A", url="https://a.example", description="Desc A"),
            SearchResult(title="B", url="https://b.example", description="Desc B"),
        ]
    )

    assert text == "Top 5 results:\n1. A\nhttps://a.example\nDesc A\n\n2. B\nhttps://b.example\nDesc B"
