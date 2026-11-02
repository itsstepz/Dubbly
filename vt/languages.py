"""Таблица языков: код Whisper/Piper, название, код NLLB."""

# (код whisper/piper, название, код NLLB-200)
LANGUAGES = [
    ("ru", "Русский", "rus_Cyrl"),
    ("en", "Английский", "eng_Latn"),
    ("de", "Немецкий", "deu_Latn"),
    ("fr", "Французский", "fra_Latn"),
    ("es", "Испанский", "spa_Latn"),
    ("it", "Итальянский", "ita_Latn"),
    ("pt", "Португальский", "por_Latn"),
    ("pl", "Польский", "pol_Latn"),
    ("uk", "Украинский", "ukr_Cyrl"),
    ("tr", "Турецкий", "tur_Latn"),
    ("nl", "Нидерландский", "nld_Latn"),
    ("cs", "Чешский", "ces_Latn"),
    ("sv", "Шведский", "swe_Latn"),
    ("fi", "Финский", "fin_Latn"),
    ("da", "Датский", "dan_Latn"),
    ("no", "Норвежский", "nob_Latn"),
    ("el", "Греческий", "ell_Grek"),
    ("hu", "Венгерский", "hun_Latn"),
    ("ro", "Румынский", "ron_Latn"),
    ("bg", "Болгарский", "bul_Cyrl"),
    ("sr", "Сербский", "srp_Cyrl"),
    ("ar", "Арабский", "arb_Arab"),
    ("he", "Иврит", "heb_Hebr"),
    ("fa", "Персидский", "pes_Arab"),
    ("hi", "Хинди", "hin_Deva"),
    ("zh", "Китайский", "zho_Hans"),
    ("ja", "Японский", "jpn_Jpan"),
    ("ko", "Корейский", "kor_Hang"),
    ("vi", "Вьетнамский", "vie_Latn"),
    ("id", "Индонезийский", "ind_Latn"),
    ("th", "Тайский", "tha_Thai"),
    ("kk", "Казахский", "kaz_Cyrl"),
    ("ka", "Грузинский", "kat_Geor"),
    ("ca", "Каталанский", "cat_Latn"),
]

# Названия языков показываются на них самих (как принято в списках выбора языка)
ENDONYMS = {
    "ru": "Русский", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
    "it": "Italiano", "pt": "Português", "pl": "Polski", "uk": "Українська", "tr": "Türkçe",
    "nl": "Nederlands", "cs": "Čeština", "sv": "Svenska", "fi": "Suomi", "da": "Dansk",
    "no": "Norsk", "el": "Ελληνικά", "hu": "Magyar", "ro": "Română", "bg": "Български",
    "sr": "Српски", "ar": "العربية", "he": "עברית", "fa": "فارسی", "hi": "हिन्दी", "zh": "中文",
    "ja": "日本語", "ko": "한국어", "vi": "Tiếng Việt", "id": "Bahasa Indonesia", "th": "ไทย",
    "kk": "Қазақша", "ka": "ქართული", "ca": "Català",
}
LANGUAGES = [(c, ENDONYMS.get(c, n), nl) for c, n, nl in LANGUAGES]

_BY_CODE = {c: (n, nl) for c, n, nl in LANGUAGES}


def name_of(code: str) -> str:
    return _BY_CODE.get(code, (code, ""))[0]


def nllb_of(code: str) -> str:
    try:
        return _BY_CODE[code][1]
    except KeyError:
        raise ValueError(f"Язык «{code}» не поддерживается переводчиком")


# Короткая фраза для прослушивания голоса (ключ — язык голоса, например «ru» из «ru_RU-denis-medium»)
SAMPLES = {
    "ru": "Привет! Так будет звучать озвучка вашего видео.",
    "en": "Hello! This is how your translated video will sound.",
    "de": "Hallo! So wird Ihr übersetztes Video klingen.",
    "fr": "Bonjour ! Voici à quoi ressemblera votre vidéo traduite.",
    "es": "¡Hola! Así sonará tu vídeo traducido.",
    "it": "Ciao! Così suonerà il tuo video tradotto.",
    "pt": "Olá! Assim vai soar o seu vídeo traduzido.",
    "pl": "Cześć! Tak zabrzmi twój przetłumaczony film.",
    "uk": "Привіт! Ось так звучатиме озвучення вашого відео.",
    "tr": "Merhaba! Çevrilmiş videonuz böyle duyulacak.",
    "nl": "Hallo! Zo klinkt je vertaalde video.",
    "cs": "Ahoj! Takhle bude znít vaše přeložené video.",
    "sv": "Hej! Så här kommer din översatta video att låta.",
    "fi": "Hei! Näin käännetty videosi kuulostaa.",
    "da": "Hej! Sådan kommer din oversatte video til at lyde.",
    "no": "Hei! Slik vil den oversatte videoen din høres ut.",
    "el": "Γεια σας! Έτσι θα ακούγεται το μεταφρασμένο σας βίντεο.",
    "hu": "Szia! Így fog hangzani a lefordított videód.",
    "ro": "Salut! Așa va suna videoclipul tău tradus.",
    "sr": "Здраво! Овако ће звучати ваш преведени видео.",
    "ar": "مرحباً! هكذا سيبدو صوت الفيديو المترجم.",
    "fa": "سلام! ویدیوی ترجمه‌شده شما این‌طور شنیده می‌شود.",
    "zh": "你好！翻译后的视频听起来就是这样。",
    "vi": "Xin chào! Video đã dịch của bạn sẽ nghe như thế này.",
    "kk": "Сәлем! Аударылған бейнеңіз осылай естіледі.",
    "ka": "გამარჯობა! ასე ჟღერს თქვენი ნათარგმნი ვიდეო.",
    "ca": "Hola! Així sonarà el teu vídeo traduït.",
}


def sample_for_lang(lang: str) -> str:
    """Фраза для голоса по коду языка. Запасной вариант: английская."""
    return SAMPLES.get(lang.lower(), SAMPLES["en"])


def sample_for(voice_key: str) -> str:
    """Фраза для голоса по его названию (ru_RU-denis-medium → русская)."""
    return sample_for_lang(voice_key.split("_", 1)[0])
