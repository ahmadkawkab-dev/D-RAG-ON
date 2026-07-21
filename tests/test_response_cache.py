from response_cache import ResponseCache, normalize_question, response_cache_key


def test_question_normalization_ignores_case_and_spacing():
    assert normalize_question("  What   Is 5.3? ") == "what is 5.3?"


def test_cache_key_changes_with_answer_settings():
    base = {"collection": "DocumentChunks", "answer_model": "small"}
    changed = {**base, "answer_model": "large"}
    assert response_cache_key("question", base) != response_cache_key("question", changed)


def test_response_cache_persists_and_reuses_normalized_question(tmp_path):
    path = tmp_path / "responses.json"
    configuration = {
        "collection": "DocumentChunks",
        "answer_model": "qwen2.5:1.5b",
        "answer": True,
    }
    result = {"query": "What is 5.3?", "answer": "45 days", "ranked": []}

    ResponseCache(path).put("What is 5.3?", configuration, result)
    cached = ResponseCache(path).get("  WHAT   IS 5.3? ", configuration)

    assert cached == result


def test_expired_response_is_not_returned(tmp_path):
    cache = ResponseCache(tmp_path / "responses.json", ttl_seconds=-1)
    cache.put("question", {}, {"answer": "old"})
    assert cache.get("question", {}) is None



def test_semantic_cache_reuses_a_close_paraphrase(tmp_path):
    cache = ResponseCache(tmp_path / "responses.json")
    configuration = {"collection": "DocumentChunks", "answer": True}
    result = {"answer": "45 days", "rerank_route": {"route": "exact"}}
    cache.put(
        "How long before a dormant account is disabled?",
        configuration,
        result,
        [1.0, 0.0],
    )

    match = cache.semantic_get(
        "After what period should an inactive account be disabled?",
        configuration,
        [0.99, 0.05],
        minimum_similarity=0.94,
    )

    assert match is not None
    assert match[0] == result
    assert match[1] > 0.99


def test_semantic_cache_does_not_cross_clause_numbers(tmp_path):
    cache = ResponseCache(tmp_path / "responses.json")
    configuration = {"collection": "DocumentChunks"}
    cache.put("What does 5.3 require?", configuration, {"answer": "a"}, [1.0, 0.0])

    match = cache.semantic_get(
        "What does 5.4 require?",
        configuration,
        [1.0, 0.0],
        minimum_similarity=0.90,
    )

    assert match is None



def test_related_topic_threshold_is_explicitly_lower_than_answer_reuse(tmp_path):
    cache = ResponseCache(tmp_path / "responses.json")
    configuration = {"collection": "DocumentChunks"}
    result = {"answer": "cached context"}
    cache.put(
        "Why are penetration tests performed?",
        configuration,
        result,
        [1.0, 0.0],
    )

    query_vector = [0.78, 0.63]
    assert cache.semantic_get(
        "Can penetration tests reveal weaknesses?",
        configuration,
        query_vector,
    ) is None

    related = cache.semantic_get(
        "Can penetration tests reveal weaknesses?",
        configuration,
        query_vector,
        minimum_similarity=0.72,
        unanchored_minimum=0.72,
    )

    assert related is not None
    assert related[0] == result

    topic = cache.topic_get(
        "Can penetration tests reveal weaknesses?",
        configuration,
    )
    assert topic is not None
    assert topic[0] == result
    assert topic[1] >= 0.5
