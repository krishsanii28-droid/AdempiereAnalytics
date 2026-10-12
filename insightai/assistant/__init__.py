"""Natural-language questions over approved, parameterised query templates.

params.py   reads periods, top-N and entity names out of a question, and screens unsafe input
matcher.py  matches a question to an approved intent (MiniLM embeddings, keyword fallback)
intents.py  the approved intents: example phrasings and the fixed query each one runs
engine.py   ties them together for the API

No SQL is ever generated from the question. The language model only produces embeddings used to
pick one of the intents below; everything that reaches the database is fixed text with bound parameters.
"""
