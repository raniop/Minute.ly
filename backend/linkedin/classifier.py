"""
Gemini-based LinkedIn prospect classifier.
Extracted from main.py GeminiClassifier class (lines 168-252).
"""
import logging

import google.generativeai as genai


class GeminiClassifier:
    """
    Uses Google Gemini API to classify a LinkedIn prospect into one of:
    Sports, News, Entertainment, or Unknown.

    Uses gemini-2.5-flash-lite for speed and cost efficiency.
    """

    PROMPT_TEMPLATE = """You are a B2B lead classifier for Minute.ly, a video AI company.

Analyze this LinkedIn profile and classify the person into exactly ONE category.

CATEGORIES:
- "Sports": Works in sports broadcasting, sports media, sports leagues, sports streaming, \
or sports content production. Examples: ESPN, NFL, NBA, Sky Sports, DAZN, sports federations.
- "News": Works in news broadcasting, news publishing, digital news media, or general-purpose \
media/publishing. Examples: CNN, BBC, Reuters, The Guardian, local TV news stations.
- "Entertainment": Works in entertainment media, OTT platforms, film/TV production, \
or general media that doesn't fit Sports or News. Examples: Netflix, Disney, Warner Bros.
- "Unknown": Cannot determine industry OR the person does not work in media/broadcasting.

PROFILE DATA:
Name: {name}
About: {about_text}
Experience: {experience_text}

RESPOND WITH EXACTLY ONE WORD: Sports, News, Entertainment, or Unknown.
Do not include any other text, explanation, or punctuation."""

    ALLOWED_CLASSIFICATIONS = {"Sports", "News", "Entertainment", "Unknown"}

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash-lite")
        self.logger = logging.getLogger("minutely")

    def classify(self, about_text: str, experience_text: str, name: str) -> str:
        """
        Classify a prospect's industry based on their LinkedIn profile data.

        Returns one of: "Sports", "News", "Entertainment", "Unknown"
        """
        prompt = self.PROMPT_TEMPLATE.format(
            name=name,
            about_text=about_text or "(not available)",
            experience_text=experience_text or "(not available)",
        )

        try:
            self.logger.debug(f"Sending classification request to Gemini for {name}")
            response = self.model.generate_content(prompt)
            result = response.text.strip().strip('"').strip("'")

            if result in self.ALLOWED_CLASSIFICATIONS:
                self.logger.info(f"Gemini classified {name} as: {result}")
                return result

            # Try case-insensitive match
            for allowed in self.ALLOWED_CLASSIFICATIONS:
                if result.lower() == allowed.lower():
                    self.logger.info(f"Gemini classified {name} as: {allowed}")
                    return allowed

            self.logger.warning(
                f"Gemini returned unexpected classification '{result}' for {name}. "
                f"Defaulting to 'Unknown'."
            )
            return "Unknown"

        except Exception as e:
            self.logger.error(
                f"Gemini API error for {name}: {e}. Defaulting to 'Unknown'."
            )
            return "Unknown"
