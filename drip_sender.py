import csv
import os
import random
import smtplib
import ssl
import time
from email.message import EmailMessage

from google import genai

# --- CONFIG ---
SENDER_EMAIL = "charanwatches@gmail.com"
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

CSV_FILE = "brands_enriched.csv"
SENT_LOG = "sent_log.txt"

DRY_RUN = False        # Review the first batch in terminal before flipping to False
DAILY_LIMIT = 5      # Safe cap for cold outreach from a personal Gmail
MIN_DELAY_SEC = 60
MAX_DELAY_SEC = 120

client = genai.Client(api_key=GEMINI_API_KEY)


def load_sent(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip().lower() for line in f if line.strip()}


def log_sent(path: str, email: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(email.lower() + "\n")

def draft_unique_email(brand_name: str, country: str, blurb: str, founder_name: str = "") -> tuple[str, str]:
    greeting_target = founder_name.strip() if founder_name.strip() else f"{brand_name} team"

    prompt = f"""
Write a short, casual, genuinely human email (80–100 words max) from Charan, a 20-year-old college student in India who is obsessed with mechanical watches.

Recipient: {greeting_target} at {brand_name} ({country})
Brand context: {blurb or "independent watchmaking"}

Tone & Style Rules (CRITICAL):
- Write like a real 20-year-old student typing on his laptop, NOT like a PR agency or a Victorian orphan.
- Start with "Hi {greeting_target},"
- Mention ONE specific thing about {brand_name} from the brand context casually and naturally.
- Make the ask light, honest, and zero-pressure: ask if they have any beaten-up prototype, scratched display piece, or spare watch sitting in a drawer that they'd ever consider gifting for Christmas.
- Add one relaxed, confident line offering to take a watch/movement trivia quiz from them to prove he's a real enthusiast and not just spamming for free stuff.
- BANNED WORDS/PHRASES: "humble", "long shot", "shot in the dark", "cherish", "endlessly", "distant dream", "quiet Christmas wish", "brutal", "gathering dust", "Warmly", "I hope this email finds you well".
- Sign off simply with "Cheers," or "Best," followed by "Charan".

Output format:
SUBJECT: <short, lowercase-friendly, natural subject line>
BODY:
<email body>
"""
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
            text = resp.text.strip()
            subject = f"quick christmas question from a student in india"
            body = text
            if "SUBJECT:" in text and "BODY:" in text:
                parts = text.split("BODY:", 1)
                subject = parts[0].replace("SUBJECT:", "").strip()
                body = parts[1].strip()
            return subject, body
        except Exception as e:
            if "429" in str(e):
                print("  [Daily API quota reached, using fallback template.]")
                break
            print(f"  [API busy, retrying {attempt + 1}/3...] ({e})")
            time.sleep(5 * (attempt + 1))

    # Humanized fallback if API quota is hit
    subject = f"quick question from a college watch nerd"
    body = (
        f"Hi {greeting_target},\n\n"
        f"I'm Charan, a 20-year-old college student in India who spends way too much time reading about mechanical watches. "
        f"I've been following {brand_name} for a while and really like what you're doing.\n\n"
        f"Since Christmas is coming up, I figured I'd just ask directly—if you happen to have an old prototype, "
        f"scratched display piece, or any spare watch sitting in a drawer, would you ever consider gifting it to a student? "
        f"Totally understand if not. Happy to take a watch trivia quiz from you first to prove I'm not just spamming!\n\n"
        f"Cheers,\nCharan"
    )
    return subject, body
def main() -> None:
    sent_set = load_sent(SENT_LOG)
    sent_count = 0

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    server = None
    if not DRY_RUN:
        ctx = ssl.create_default_context()
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx)
        server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)

    try:
        for row in rows:
            if sent_count >= DAILY_LIMIT:
                print(f"\nReached daily limit ({DAILY_LIMIT}). Run again tomorrow.")
                break

            email = row["email"].strip()
            brand = row["brand_name"].strip()
            if not email or email.lower() in sent_set:
                continue

            subject, body = draft_unique_email(brand, row["country"], row["brand_blurb"], row.get("founder_name", ""))

            msg = EmailMessage()
            msg["From"] = f"Charan Poddaturi <{SENDER_EMAIL}>"
            msg["To"] = email
            msg["Subject"] = subject
            msg.set_content(body)

            if DRY_RUN:
                print("=" * 60)
                print(f"TO: {email} ({brand})")
                print(f"SUBJECT: {subject}\n\n{body}\n")
                sent_count += 1
            else:
                server.send_message(msg)
                log_sent(SENT_LOG, email)
                sent_count += 1
                print(f"[SENT {sent_count}/{DAILY_LIMIT}] {brand} -> {email}")
                delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
                time.sleep(delay)
    finally:
        if server:
            server.quit()


if __name__ == "__main__":
    main()