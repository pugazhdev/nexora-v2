import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from envload import load_env
from openai import OpenAI
from pydantic import BaseModel

env = load_env()
model = env.get("OPENAI_MODEL") or env["OPENAI_VISION_MODEL"]
client = OpenAI(api_key=env["OPENAI_API_KEY"])
TOOLS = [{"type": "web_search", "user_location": {"type": "approximate", "country": "IN"}}]
Q = "2 mL disposable syringe with needle manufacturer India price"


class Hit(BaseModel):
    url: str
    title: str
    seller: str


class Hits(BaseModel):
    hits: list[Hit]


def show(resp):
    for item in resp.output:
        if item.type == "message":
            for c in item.content:
                for a in getattr(c, "annotations", []) or []:
                    if a.type == "url_citation":
                        print("CITATION", a.url, "|", a.title)


print("model:", model)
print("--- A: parse + web_search")
try:
    r = client.responses.parse(model=model, tools=TOOLS, input=Q, text_format=Hits)
    print("PARSED:", r.output_parsed)
    show(r)
except Exception as e:
    print("A FAILED:", type(e).__name__, str(e)[:500])
    print("--- B: web_search without text_format, then parse on text")
    try:
        r = client.responses.create(model=model, tools=TOOLS, input=Q)
        print("TEXT:", r.output_text[:800])
        show(r)
        p = client.responses.parse(model=model, input="Extract the listing URLs:\n" + r.output_text, text_format=Hits)
        print("PARSED2:", p.output_parsed)
    except Exception as e2:
        print("B FAILED:", type(e2).__name__, str(e2)[:500])
