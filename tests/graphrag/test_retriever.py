"""Tests for graphrag/retriever.py."""

from unittest.mock import MagicMock, patch

from graphrag.retriever import answer_question

_ENTITY_FIXTURE = {"coaches": ["Nick Saban"], "teams": [], "players": []}


def _mock_answer_model(answer_text: str = "Test answer.") -> MagicMock:
    """Build a mock GenerativeModel for answer generation."""
    model = MagicMock()
    model.generate_content.return_value.text = answer_text
    return model


def _neo4j_driver() -> MagicMock:
    """Minimal Neo4j driver mock with an empty-result session."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def test_answer_question_returns_string():
    """answer_question must return a non-empty string."""
    model = _mock_answer_model("Nick Saban coached Alabama for 17 seasons.")

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE):
        result = answer_question("Tell me about Nick Saban", driver=_neo4j_driver(), model=model)

    assert isinstance(result, str)
    assert len(result) > 0


def test_answer_question_calls_generate_content():
    """answer_question should call model.generate_content for answer generation."""
    model = _mock_answer_model()

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE):
        answer_question("Who is Nick Saban?", driver=_neo4j_driver(), model=model)

    model.generate_content.assert_called_once()


def test_answer_question_calls_extract_entities():
    """answer_question should call extract_entities with the original question."""
    model = _mock_answer_model()

    with patch("graphrag.retriever.extract_entities", return_value=_ENTITY_FIXTURE) as mock_extract:
        answer_question("Who is Nick Saban?", driver=_neo4j_driver(), model=model)

    mock_extract.assert_called_once_with("Who is Nick Saban?")
