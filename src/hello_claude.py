import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()            # finder selv ANTHROPIC_API_KEY i miljøet
MODEL = "claude-haiku-5-5"

resp = client.messages.create(
    model=MODEL,
    max_tokens=200,
    messages=[{"role": "user", "content": "Forklar log loss i én sætning."}],
)
print(resp.content[0].text)

u = resp.usage
cost = u.input_tokens / 1e6 * 0.10 + u.output_tokens / 1e6 * 0.50
print(f"\nTokens: {u.input_tokens} ind, {u.output_tokens} ud – pris ca. ${cost:.6f}")