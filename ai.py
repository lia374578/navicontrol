import os
from google import genai
from dotenv import load_dotenv
load_dotenv()

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

generation_config = {
    "temperature": 1,
    "max_output_tokens": 65536,
    "top_p": 0.95,
    "thinking_level": "high",
}

interaction = client.interactions.create(
    model="models/gemini-3-flash-preview",
    input="",
    generation_config=generation_config,
)

print(interaction.steps[-1])



