# For testing what all the models there that can be used....Not needed to run in runtime
import google.generativeai as genai

genai.configure(api_key="API_KEY")

print("Listing models:")
for m in genai.list_models():
    print(m.name)

