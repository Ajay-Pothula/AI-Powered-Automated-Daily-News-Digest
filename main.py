# --- All imports at the top ---
import feedparser
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import smtplib
from email.message import EmailMessage
import datetime

# --- IMPORTANT: PASTE YOUR NEW SECRETS HERE ---
# 1. Create a NEW API Key and paste it here
GOOGLE_API_KEY = "AIzaSyBriKnuIloYXW7ByzYPm0BZmQndhlj5C9Q"
# 2. Create a NEW App Password and paste it here
SENDER_EMAIL = "pothulaajay3@gmail.com"  # Your Gmail address
RECEIVER_EMAIL = "ajaypothula125@gmail.com" # The email you want to send to
APP_PASSWORD = "rohq vmyu xdqx msxq"

# --- Helper function to get article text ---
def get_article_text(url):
    try:
        response = requests.get(url, timeout=10) # Added a timeout
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        article_text = ' '.join([p.get_text() for p in paragraphs])
        # A quick check to see if we got meaningful text
        if len(article_text) < 200:
            return None
        return article_text
    except Exception as e:
        print(f"Error fetching article content: {e}")
        return None
    

# --- Helper function to send email ---

def send_email(subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, APP_PASSWORD)
            smtp.send_message(msg)
            print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

###############-------------#######################
# def send_email(subject, articles):
#     """
#     articles: list of dicts with keys 'title', 'url', 'summary'
#     """
#     msg = EmailMessage()
#     msg['Subject'] = subject
#     msg['From'] = SENDER_EMAIL
#     msg['To'] = RECEIVER_EMAIL

#     # Build plain-text and HTML versions
#     plain_text = ""
#     html_content = "<html><body>"

#     for article in articles:
#         plain_text += f"{article['title']}\nLink: {article['url']}\nSummary:\n{article['summary']}\n\n"
#         html_content += f"""
#         <h2>{article['title']}</h2>
#         <p><a href="{article['url']}">Read full article</a></p>
#         <ul>
#             {''.join(f'<li>{line.strip(" *")}</li>' for line in article['summary'].splitlines() if line.startswith('*'))}
#         </ul>
#         """

#     html_content += "</body></html>"

#     msg.set_content(plain_text)
#     msg.add_alternative(html_content, subtype='html')

#     try:
#         with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
#             smtp.login(SENDER_EMAIL, APP_PASSWORD)
#             smtp.send_message(msg)
#             print("Email sent successfully!")
#     except Exception as e:
#         print(f"Error sending email: {e}")
####################-------------------##########################


# --- Main Script Logic ---

# 1. Fetch the latest news article
news_feed_url = 'https://timesofindia.indiatimes.com/rssfeedstopstories.cms'
feed = feedparser.parse(news_feed_url)

if not feed.entries:
    print("Could not fetch any articles from the RSS feed.")
else:
    first_article = feed.entries[0]
    article_url = first_article.link
    article_title = first_article.title

    print(f"Title: {article_title}")
    print(f"Link: {article_url}")

    # 2. Get the full text of the article
    full_text = get_article_text(article_url)

    if full_text:
        # 3. Summarize using Gemini
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            # FIX 1: Using the recommended model name
            model = genai.GenerativeModel('gemini-2.5-flash')

            prompt = f"Please summarize the following news article in 3 short, clear bullet points:\n\nArticle Title: {article_title}\n\nArticle Text:\n{full_text}"
            
            print("\nGenerating summary...")
            response = model.generate_content(prompt)
            summary = response.text

            print("\n--- Summary ---")
            print(summary)

            # 4. Send the email with the actual summary
            today_date = datetime.date.today().strftime('%B %d, %Y')
            email_subject = f"Your Daily News Digest - {today_date}"
            
            # FIX 2: Using the real 'summary' variable in the email body
            email_body = f"Today's Top Story:\n{article_title}\n\nLink: {article_url}\n\nSummary:\n{summary}"
            
            send_email(subject=email_subject, body=email_body)

        except Exception as e:
            print(f"An error occurred with the Gemini API: {e}")
    else:
        print("Could not retrieve enough text from the article to summarize.")