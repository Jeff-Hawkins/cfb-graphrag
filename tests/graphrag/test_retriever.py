"""Tests for graphrag/retriever.py."""

from unittest.mock import MagicMock, patch

from graphrag.retriever import answer_question

_ENTITY_FIXTURE = {"coaches": ["Nick Saban"], "teams": [], "players": []}
_CLASSIFY_FIXTURE = {"intent": "TREE_QUERY", "confidence": 0.95}


def _mock_client(answer_text: str = "Test answer.") -> MagicMock:
    """Build a mock genai.Client for answer generation."""
    client = MagicMock()
    client.models.generate_content.return_value.text = answer_text
    return client


def _neo4j_driver() -> MagicMock:
    """Minimal Neo4j driver mock with an empty-result session."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    session.run.return_value = MagicMock()
    session.run.return_value.__iter__ = MagicMock(return_value=iter([]))
    session.run.return_value.single = MagicMock(return_value=None)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def test_answer_question_returns_string():
    """answer_question must return a non-empty string."""
    client = _mock_client("Nick Saban coached Alabama for 17 seasons.")

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE), \
         patch("graphrag.retriever.classify_intent", return_value=_CLASSIFY_FIXTURE), \
         patch("graphrag.retriever.resolve_coach_entity", return_value={
             "cfbd_node_id": None, "mc_coach_code": None,
             "display_name": "Nick Saban", "source": "cfbd_only",
         }), \
         patch("graphrag.retriever.get_coach_tree", return_value=[]):
        result = answer_question("Tell me about Nick Saban", driver=_neo4j_driver(), client=client)

    assert isinstance(result, str)
    assert len(result) > 0


def test_answer_question_calls_generate_content():
    """answer_question should call client.models.generate_content for answer generation."""
    client = _mock_client()

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE), \
         patch("graphrag.retriever.classify_intent", return_value=_CLASSIFY_FIXTURE), \
         patch("graphrag.retriever.resolve_coach_entity", return_value={
             "cfbd_node_id": None, "mc_coach_code": None,
             "display_name": "Nick Saban", "source": "cfbd_only",
         }), \
         patch("graphrag.retriever.get_coach_tree", return_value=[]):
        answer_question("Who is Nick Saban?", driver=_neo4j_driver(), client=client)

    client.models.generate_content.assert_called_once()


def test_answer_question_calls_extract_entities():
    """answer_question should call extract_entities with the original question."""
    client = _mock_client()

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE) as mock_extract, \
         patch("graphrag.retriever.classify_intent", return_value=_CLASSIFY_FIXTURE), \
         patch("graphrag.retriever.resolve_coach_entity", return_value={
             "cfbd_node_id": None, "mc_coach_code": None,
             "display_name": "Nick Saban", "source": "cfbd_only",
         }), \
         patch("graphrag.retriever.get_coach_tree", return_value=[]):
        answer_question("Who is Nick Saban?", driver=_neo4j_driver(), client=client)

    mock_extract.assert_called_once_with("Who is Nick Saban?", client=client)


def test_answer_question_uses_coaching_tree_when_mc_code_present():
    """When resolve_coach_entity returns a mc_coach_code, get_coaching_tree is called."""
    client = _mock_client("Kirby Smart came from Saban's staff.")
    driver = _neo4j_driver()

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE), \
         patch("graphrag.retriever.classify_intent", return_value=_CLASSIFY_FIXTURE), \
         patch("graphrag.retriever.resolve_coach_entity", return_value={
             "cfbd_node_id": "elem-1", "mc_coach_code": 1457,
             "display_name": "Nick Saban", "source": "both",
         }), \
         patch("graphrag.retriever.get_coaching_tree", return_value=[]) as mock_tree:
        answer_question(
            "Show me every HC from Saban's staff",
            driver=driver,
            client=client,
        )

    mock_tree.assert_called_once()
    _, call_kwargs = mock_tree.call_args
    assert call_kwargs["coach_code"] == 1457
    assert call_kwargs["role_filter"] == "HC"
    assert call_kwargs["max_depth"] == 4
