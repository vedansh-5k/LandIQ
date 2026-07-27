import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

try:
    print("Testing gemini-1.5-flash...")
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
    print(llm.invoke("Hello").content)
except Exception as e:
    print("Error with flash:", e)

try:
    print("Testing gemini-1.5-flash-latest...")
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest")
    print(llm.invoke("Hello").content)
except Exception as e:
    print("Error with latest:", e)

try:
    print("Testing gemini-1.5-flash-001...")
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-001")
    print(llm.invoke("Hello").content)
except Exception as e:
    print("Error with 001:", e)
