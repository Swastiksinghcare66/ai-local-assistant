from __future__ import annotations

import re


class HinglishNormalizer:
    """
    Speech-only Hinglish front-end for Piper hi_IN.

    The displayed/stored assistant text is left untouched.  This class creates
    a pronunciation-oriented copy for the Hindi Piper voice by:
      * converting common Roman Hindi to Devanagari,
      * converting common English/technical loan words to Hindi phonetics,
      * expanding acronyms, numbers and engineering units,
      * normalising punctuation for more natural pauses.

    It is deliberately conservative around unknown names, code and paths.
    """

    _TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+:#/'\-]*(?:\.[A-Za-z0-9_+:#/'\-]+)*")
    _DEV_RE = re.compile(r"[\u0900-\u097F]")

    _LETTER_NAMES = {
        "a": "ए", "b": "बी", "c": "सी", "d": "डी", "e": "ई", "f": "एफ",
        "g": "जी", "h": "एच", "i": "आई", "j": "जे", "k": "के", "l": "एल",
        "m": "एम", "n": "एन", "o": "ओ", "p": "पी", "q": "क्यू", "r": "आर",
        "s": "एस", "t": "टी", "u": "यू", "v": "वी", "w": "डब्ल्यू", "x": "एक्स",
        "y": "वाय", "z": "ज़ेड",
    }

    _ROMAN_HINDI = {
        "haan": "हाँ", "han": "हाँ", "nahi": "नहीं", "nahin": "नहीं",
        "kya": "क्या", "kyu": "क्यों", "kyun": "क्यों", "kaise": "कैसे",
        "mujhe": "मुझे", "tum": "तुम", "aap": "आप", "hum": "हम", "main": "मैं",
        "mai": "मैं", "mera": "मेरा", "meri": "मेरी", "mere": "मेरे",
        "aapka": "आपका", "aapki": "आपकी", "aapko": "आपको", "tumhara": "तुम्हारा",
        "tumhe": "तुम्हें", "hai": "है", "hain": "हैं", "ho": "हो", "tha": "था",
        "thi": "थी", "raha": "रहा", "rahi": "रही", "rahe": "रहे",
        "kar": "कर", "karo": "करो", "karna": "करना", "karen": "करें", "karte": "करते",
        "karti": "करती", "karta": "करता", "batao": "बताओ", "bataiye": "बताइए",
        "samjhao": "समझाओ", "samjhaiye": "समझाइए", "samajh": "समझ", "suno": "सुनो",
        "dekho": "देखो", "dekh": "देख", "dekhte": "देखते", "ab": "अब", "abhi": "अभी",
        "phir": "फिर", "agar": "अगर", "lekin": "लेकिन", "aur": "और", "bas": "बस",
        "sirf": "सिर्फ", "thoda": "थोड़ा", "thodi": "थोड़ी", "zyada": "ज़्यादा",
        "kam": "कम", "sahi": "सही", "galat": "गलत", "ye": "ये", "yeh": "ये",
        "wo": "वो", "woh": "वो", "iska": "इसका", "iski": "इसकी", "isko": "इसको",
        "isme": "इसमें", "uska": "उसका", "usko": "उसको", "usme": "उसमें", "ka": "का",
        "ki": "की", "ke": "के", "se": "से", "pe": "पे", "par": "पर", "mein": "में",
        "me": "में", "to": "तो", "na": "ना", "wala": "वाला", "wali": "वाली",
        "wale": "वाले", "chahiye": "चाहिए", "yaar": "यार", "bhai": "भाई",
        "accha": "अच्छा", "acha": "अच्छा", "theek": "ठीक", "thik": "ठीक",
        "matlab": "मतलब", "hota": "होता", "hoti": "होती", "hote": "होते",
        "lagta": "लगता", "lagti": "लगती", "pata": "पता", "ek": "एक", "baar": "बार",
        "saath": "साथ", "andar": "अंदर", "bahar": "बाहर", "upar": "ऊपर", "niche": "नीचे",
        "pehle": "पहले", "baad": "बाद", "fir": "फिर", "chalo": "चलो", "chal": "चल",
        "bolo": "बोलो", "bol": "बोल", "boliye": "बोलिए", "milega": "मिलेगा",
        "milegi": "मिलेगी", "milta": "मिलता", "milti": "मिलती", "rakh": "रख",
        "rakho": "रखो", "rakhna": "रखना", "bhi": "भी", "hi": "ही", "kuch": "कुछ",
        "sab": "सब", "bahut": "बहुत", "bilkul": "बिल्कुल", "shayad": "शायद",
        "waise": "वैसे", "waisa": "वैसा", "aisi": "ऐसी", "aisa": "ऐसा", "ise": "इसे",
        "usse": "उससे", "mujhse": "मुझसे", "tumse": "तुमसे", "aapse": "आपसे",
        "ko": "को", "karenge": "करेंगे", "karoge": "करोगे", "karenge": "करेंगे",
        "hui": "हुई", "hua": "हुआ", "hue": "हुए", "ya": "या", "le": "ले", "lo": "लो",
        "lenge": "लेंगे", "legi": "लेगी", "lena": "लेना", "liye": "लिए", "liye": "लिए",
    }

    # Phrase replacements run before token replacements so multiword technical
    # expressions keep their natural spoken form.
    _PHRASES = {
        "machine learning": "मशीन लर्निंग",
        "deep learning": "डीप लर्निंग",
        "neural network": "न्यूरल नेटवर्क",
        "neural networks": "न्यूरल नेटवर्क्स",
        "large language model": "लार्ज लैंग्वेज मॉडल",
        "large language models": "लार्ज लैंग्वेज मॉडल्स",
        "fine tuning": "फाइन ट्यूनिंग",
        "fine-tuning": "फाइन ट्यूनिंग",
        "computer vision": "कंप्यूटर विज़न",
        "natural language processing": "नैचुरल लैंग्वेज प्रोसेसिंग",
        "operating system": "ऑपरेटिंग सिस्टम",
        "data structure": "डेटा स्ट्रक्चर",
        "data structures": "डेटा स्ट्रक्चर्स",
        "real time": "रियल टाइम",
        "real-time": "रियल टाइम",
        "response time": "रिस्पॉन्स टाइम",
        "vector database": "वेक्टर डेटाबेस",
        "context window": "कॉन्टेक्स्ट विंडो",
        "system prompt": "सिस्टम प्रॉम्प्ट",
        "prompt engineering": "प्रॉम्प्ट इंजीनियरिंग",
        "speech to text": "स्पीच टू टेक्स्ट",
        "text to speech": "टेक्स्ट टू स्पीच",
        "wake word": "वेक वर्ड",
        "noise suppression": "नॉइज़ सप्रेशन",
        "echo cancellation": "एको कैंसलेशन",
        "model loading": "मॉडल लोडिंग",
        "memory usage": "मेमोरी यूसेज",
        "gpu memory": "जी पी यू मेमोरी",
        "cpu usage": "सी पी यू यूसेज",
        "ram usage": "रैम यूसेज",
        "power consumption": "पावर कंजम्प्शन",
    }

    _TECH = {
        "ai": "ए आई", "ml": "एम एल", "llm": "एल एल एम", "rag": "रैग",
        "gpu": "जी पी यू", "cpu": "सी पी यू", "ram": "रैम", "vram": "वी रैम",
        "am": "ए एम", "pm": "पी एम",
        "cuda": "कूडा", "nvidia": "एनविडिया", "rtx": "आर टी एक्स",
        "python": "पाइथन", "pytorch": "पाई टॉर्च", "tensorflow": "टेंसरफ्लो",
        "java": "जावा", "javascript": "जावास्क्रिप्ट", "cpp": "सी प्लस प्लस",
        "c++": "सी प्लस प्लस", "windows": "विंडोज़", "linux": "लिनक्स", "wsl": "डब्ल्यू एस एल",
        "ollama": "ओलामा", "qwen": "क्वेन", "qwen3": "क्वेन थ्री", "piper": "पाइपर",
        "parakeet": "पैराकीट", "chatterbox": "चैटरबॉक्स", "cosyvoice": "कोज़ी वॉइस",
        "onnx": "ऑनिक्स", "api": "ए पी आई", "http": "एच टी टी पी", "https": "एच टी टी पी एस",
        "json": "जेसन", "sql": "एस क्यू एल", "dbms": "डी बी एम एस", "os": "ओ एस",
        "stt": "एस टी टी", "tts": "टी टी एस", "vad": "वी ए डी", "aec": "ए ई सी",
        "esp32": "ई एस पी थर्टी टू", "esp32-s3": "ई एस पी थर्टी टू एस थ्री",
        "i2s": "आई टू एस", "i2c": "आई टू सी", "spi": "एस पी आई", "uart": "यू आर्ट",
        "gpio": "जी पी आई ओ", "wifi": "वाई फाई", "wi-fi": "वाई फाई", "bluetooth": "ब्लूटूथ",
        "model": "मॉडल", "models": "मॉडल्स", "server": "सर्वर", "client": "क्लाइंट",
        "database": "डेटाबेस", "data": "डेटा", "vector": "वेक्टर", "vectors": "वेक्टर्स",
        "embedding": "एम्बेडिंग", "embeddings": "एम्बेडिंग्स", "pipeline": "पाइपलाइन",
        "latency": "लेटेंसी", "memory": "मेमोरी", "context": "कॉन्टेक्स्ट", "token": "टोकन",
        "tokens": "टोकन्स", "prompt": "प्रॉम्प्ट", "inference": "इन्फरेंस",
        "quantization": "क्वांटाइज़ेशन", "finetuning": "फाइन ट्यूनिंग", "training": "ट्रेनिंग",
        "dataset": "डेटासेट", "framework": "फ्रेमवर्क", "backend": "बैकएंड", "frontend": "फ्रंटएंड",
        "code": "कोड", "error": "एरर", "debug": "डीबग", "file": "फाइल", "folder": "फोल्डर",
        "search": "सर्च", "web": "वेब", "local": "लोकल", "online": "ऑनलाइन", "offline": "ऑफलाइन",
        "temperature": "टेम्परेचर", "high": "हाई", "low": "लो", "load": "लोड", "loading": "लोडिंग",
        "system": "सिस्टम", "process": "प्रोसेस", "network": "नेटवर्क", "audio": "ऑडियो",
        "speaker": "स्पीकर", "microphone": "माइक्रोफोन", "mic": "माइक", "voice": "वॉइस",
        "stream": "स्ट्रीम", "streaming": "स्ट्रीमिंग", "cache": "कैश", "thread": "थ्रेड",
        "threads": "थ्रेड्स", "core": "कोर", "cores": "कोर्स", "benchmark": "बेंचमार्क",
        "performance": "परफॉर्मेंस", "fast": "फास्ट", "slow": "स्लो", "update": "अपडेट",
        "download": "डाउनलोड", "install": "इंस्टॉल", "version": "वर्ज़न", "config": "कॉन्फिग",
        "configuration": "कॉन्फिगरेशन", "router": "राउटर", "agent": "एजेंट", "tool": "टूल",
        "tools": "टूल्स", "response": "रिस्पॉन्स", "request": "रिक्वेस्ट", "result": "रिज़ल्ट",
        "check": "चेक", "restart": "रीस्टार्ट", "start": "स्टार्ट", "stop": "स्टॉप",
        "open": "ओपन", "close": "क्लोज़", "run": "रन", "running": "रनिंग",
        "ready": "रेडी", "working": "वर्किंग", "issue": "इशू", "problem": "प्रॉब्लम",
        "fix": "फिक्स", "fixed": "फिक्स्ड", "good": "गुड", "bad": "बैड", "better": "बेटर",
        "best": "बेस्ट", "normal": "नॉर्मल", "safe": "सेफ", "dangerous": "डेंजरस",
        "cooling": "कूलिंग", "status": "स्टेटस", "usage": "यूसेज", "storage": "स्टोरेज",
        "drive": "ड्राइव", "disk": "डिस्क", "internet": "इंटरनेट", "connection": "कनेक्शन",
        "connected": "कनेक्टेड", "disconnected": "डिस्कनेक्टेड", "mode": "मोड",
        "active": "एक्टिव", "standby": "स्टैंडबाय", "automatic": "ऑटोमैटिक",
        "auto": "ऑटो", "manual": "मैनुअल", "default": "डिफॉल्ट", "input": "इनपुट",
        "output": "आउटपुट", "quality": "क्वालिटी", "speed": "स्पीड", "frequency": "फ्रीक्वेंसी",
        "voltage": "वोल्टेज", "current": "करंट", "power": "पावर", "signal": "सिग्नल",
        "frequency": "फ्रीक्वेंसी", "bandwidth": "बैंडविड्थ", "packet": "पैकेट",
        "packets": "पैकेट्स", "buffer": "बफर", "queue": "क्यू", "hardware": "हार्डवेयर",
        "software": "सॉफ्टवेयर", "firmware": "फर्मवेयर", "device": "डिवाइस", "driver": "ड्राइवर",
        "let's": "लेट्स", "lets": "लेट्स", "the": "द", "a": "अ", "an": "एन",
        "and": "एंड", "or": "ऑर", "for": "फॉर", "with": "विद", "from": "फ्रॉम",
        "this": "दिस", "that": "दैट", "is": "इज़", "are": "आर", "was": "वॉज़", "were": "वर",
        "but": "बट", "okay": "ओके", "ok": "ओके",
        "actually": "एक्चुअली", "basically": "बेसिकली", "simple": "सिंपल", "way": "वे",
        "technical": "टेक्निकल", "words": "वर्ड्स", "word": "वर्ड", "degrees": "डिग्रीज़",
        "difference": "डिफरेंस", "around": "अराउंड", "about": "अबाउट", "because": "बिकॉज़",
        "then": "देन", "now": "नाउ", "first": "फर्स्ट", "next": "नेक्स्ट", "time": "टाइम",
    }

    _ONES = {
        0: "ज़ीरो", 1: "वन", 2: "टू", 3: "थ्री", 4: "फोर", 5: "फाइव",
        6: "सिक्स", 7: "सेवन", 8: "एट", 9: "नाइन", 10: "टेन",
        11: "इलेवन", 12: "ट्वेल्व", 13: "थर्टीन", 14: "फोर्टीन",
        15: "फिफ्टीन", 16: "सिक्सटीन", 17: "सेवेंटीन", 18: "एटीन", 19: "नाइन्टीन",
    }

    _TENS = {
        20: "ट्वेंटी", 30: "थर्टी", 40: "फोर्टी", 50: "फिफ्टी",
        60: "सिक्स्टी", 70: "सेवेंटी", 80: "एटी", 90: "नाइंटी",
    }

    _UNITS = {
        "gb": "जी बी", "mb": "एम बी", "kb": "के बी", "tb": "टी बी",
        "gb/s": "जी बी पर सेकंड", "mb/s": "एम बी पर सेकंड",
        "ghz": "गीगा हर्ट्ज़", "mhz": "मेगा हर्ट्ज़", "khz": "किलो हर्ट्ज़", "hz": "हर्ट्ज़",
        "ms": "मिलीसेकंड", "s": "सेकंड", "sec": "सेकंड", "secs": "सेकंड",
        "%": "परसेंट", "w": "वॉट", "v": "वोल्ट", "a": "एम्पियर",
        "c": "डिग्री सेल्सियस", "°c": "डिग्री सेल्सियस",
        "f": "डिग्री फ़ारेनहाइट", "°f": "डिग्री फ़ारेनहाइट",
    }

    @classmethod
    def _number_words(cls, value: int) -> str:
        if value < 0:
            return "माइनस " + cls._number_words(abs(value))
        if value < 20:
            return cls._ONES[value]
        if value < 100:
            tens = (value // 10) * 10
            rest = value % 10
            return cls._TENS[tens] + (" " + cls._ONES[rest] if rest else "")
        if value < 1000:
            head = cls._ONES[value // 100] + " हंड्रेड"
            rest = value % 100
            return head + (" " + cls._number_words(rest) if rest else "")
        if value < 10000:
            head = cls._ONES[value // 1000] + " थाउज़ंड"
            rest = value % 1000
            return head + (" " + cls._number_words(rest) if rest else "")
        # Large technical IDs are safer digit-by-digit than guessed grouping.
        return " ".join(cls._ONES[int(ch)] for ch in str(value) if ch.isdigit())

    @classmethod
    def _decimal_words(cls, raw: str, force_digits: bool = False) -> str:
        raw = str(raw).strip()
        sign = ""
        if raw.startswith("-"):
            sign = "माइनस "
            raw = raw[1:]

        if "." in raw:
            left, right = raw.split(".", 1)
            left_value = int(left or "0")
            right_words = " ".join(cls._ONES[int(ch)] for ch in right if ch.isdigit())
            return f"{sign}{cls._number_words(left_value)} पॉइंट {right_words}".strip()

        if not raw.isdigit():
            return raw

        if force_digits:
            return sign + " ".join(cls._ONES[int(ch)] for ch in raw)

        return sign + cls._number_words(int(raw))

    @classmethod
    def _replace_units_and_numbers(cls, text: str) -> str:
        # Clock times need special handling before generic numbers.  Speaking
        # "12:40 PM" as "twelve colon forty" sounds synthetic; for voice we
        # want "twelve forty P M" (and "twelve oh five" for 12:05).
        def clock_repl(match: re.Match) -> str:
            hour_raw = match.group(1)
            minute_raw = match.group(2)
            suffix = match.group(3).lower()

            hour = cls._decimal_words(hour_raw)
            minute_value = int(minute_raw)
            if minute_value == 0:
                minute = ""
            elif minute_value < 10:
                minute = "ओ " + cls._decimal_words(str(minute_value))
            else:
                minute = cls._decimal_words(str(minute_value))

            am_pm = "ए एम" if suffix == "am" else "पी एम"
            return " ".join(part for part in (hour, minute, am_pm) if part)

        text = re.sub(
            r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b",
            clock_repl,
            text,
            flags=re.IGNORECASE,
        )

        # Common GPU/product identifiers are normally spoken digit-by-digit.
        def product_id(match: re.Match) -> str:
            prefix = match.group(1)
            number = match.group(2)
            spoken_prefix = cls._TECH.get(prefix.lower(), prefix)
            return spoken_prefix + " " + cls._decimal_words(number, force_digits=True)

        text = re.sub(
            r"\b(RTX|GTX|ESP)\s*[- ]?([0-9]{2,6})\b",
            product_id,
            text,
            flags=re.IGNORECASE,
        )

        # Number + engineering/computing unit.
        unit_keys = sorted(cls._UNITS, key=len, reverse=True)
        unit_pattern = "|".join(re.escape(key) for key in unit_keys)

        def unit_repl(match: re.Match) -> str:
            number = cls._decimal_words(match.group(1))
            unit = cls._UNITS.get(match.group(2).lower(), match.group(2))
            return f"{number} {unit}"

        text = re.sub(
            rf"(?<![\w.])(-?\d+(?:\.\d+)?)\s*({unit_pattern})(?![A-Za-z])",
            unit_repl,
            text,
            flags=re.IGNORECASE,
        )

        # Temperatures often arrive as "72 degrees" without C/F.
        text = re.sub(
            r"\b(-?\d+(?:\.\d+)?)\s+degrees?\b",
            lambda m: cls._decimal_words(m.group(1)) + " डिग्रीज़",
            text,
            flags=re.IGNORECASE,
        )

        # Remaining standalone numbers/versions.
        text = re.sub(
            r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])",
            lambda m: cls._decimal_words(m.group(0)),
            text,
        )

        return text

    @classmethod
    def _replace_phrases(cls, text: str) -> str:
        for source in sorted(cls._PHRASES, key=len, reverse=True):
            target = cls._PHRASES[source]
            text = re.sub(
                rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])",
                target,
                text,
                flags=re.IGNORECASE,
            )
        return text

    @classmethod
    def _spell_acronym(cls, token: str) -> str | None:
        clean = re.sub(r"[^A-Za-z]", "", token)
        if not clean:
            return None
        if token.isupper() and len(clean) <= 8:
            return " ".join(cls._LETTER_NAMES.get(ch.lower(), ch) for ch in clean)
        return None

    @classmethod
    def _replace_token(cls, match: re.Match) -> str:
        token = match.group(0)
        lower = token.lower()

        if lower in cls._TECH:
            return cls._TECH[lower]
        if lower in cls._ROMAN_HINDI:
            return cls._ROMAN_HINDI[lower]

        spelled = cls._spell_acronym(token)
        if spelled:
            return spelled

        # Unknown names/code are intentionally preserved rather than guessed.
        return token

    @staticmethod
    def _punctuation(text: str) -> str:
        text = text.replace("...", "…")
        text = re.sub(r"\s*,\s*", ", ", text)
        text = re.sub(r"\s*;\s*", "; ", text)
        text = re.sub(r"\s*:\s*", ": ", text)
        text = re.sub(r"\s*\?\s*", "? ", text)
        text = re.sub(r"\s*!\s*", "! ", text)
        # Hindi Piper usually pauses more naturally on danda than on a dense
        # run of Latin full stops. Decimals were already expanded above.
        text = re.sub(r"\s*\.\s*", "। ", text)
        text = re.sub(r"\s*।\s*", "। ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def to_piper_text(self, text: str) -> str:
        text = str(text or "").strip()
        if not text:
            return ""

        # Strip formatting that sounds awkward when read literally.
        text = text.replace("`", "")
        text = re.sub(r"[*_]{1,3}", "", text)

        text = self._replace_phrases(text)
        text = self._replace_units_and_numbers(text)
        text = self._TOKEN_RE.sub(self._replace_token, text)
        text = self._punctuation(text)
        return text
