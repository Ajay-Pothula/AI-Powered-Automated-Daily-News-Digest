import google.generativeai as genai

genai.configure(api_key="AIzaSyBriKnuIloYXW7ByzYPm0BZmQndhlj5C9Q")

print("Listing models:")
for m in genai.list_models():
    print(m.name)
