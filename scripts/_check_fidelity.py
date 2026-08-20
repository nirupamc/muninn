from app.admission.providers.deterministic import DeterministicAdmissionProvider

p = DeterministicAdmissionProvider()
cases = [
    "I'm building RagParser.",
    "RagParser is the document parser I'm working on.",
    "I do not prefer Python.",
    "I do not prefer Python anymore.",
    "I no longer use SQLite.",
    "I still use FastAPI.",
    "I now prefer Rust.",
    "I used to prefer JavaScript.",
    "I switched from OpenAI to local models.",
    "I still prefer OpenAI APIs.",
]
for c in cases:
    a = p.analyze_event(role="user", content=c)
    stores = [x.candidate.content for x in a.candidates if x.provider_recommendation == "STORE"]
    print(repr(c), "->", stores)
