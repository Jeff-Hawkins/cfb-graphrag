"""Run the three target demo queries through the full GraphRAG pipeline.

Usage:
    python demo_queries.py

Requires a valid .env with NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD,
and GEMINI_API_KEY set.

Demo queries:
  1. Show me every head coach who came from Nick Saban's staff
  2. Which coaches have worked in both the SEC and Big Ten?
  3. What is the shortest path between Kirby Smart and Lincoln Riley?
"""

import os
import textwrap
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from neo4j import GraphDatabase

from graphrag.retriever import answer_question

load_dotenv()

DEMO_QUERIES = [
    "Show me every head coach who came from Nick Saban's staff",
    "Which coaches have worked in both the SEC and Big Ten?",
    "What is the shortest path between Kirby Smart and Lincoln Riley?",
]


def _separator(title: str) -> None:
    width = 72
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def run_demos() -> None:
    """Connect to Neo4j and run all three demo queries, printing full results."""
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for i, query in enumerate(DEMO_QUERIES, start=1):
        _separator(f"Demo Query {i}")
        print(f"  Q: {query}\n")

        answer = answer_question(query, driver=driver, client=client)

        print("  Answer:")
        for line in textwrap.wrap(answer, width=68):
            print(f"    {line}")

    driver.close()


if __name__ == "__main__":
    run_demos()
