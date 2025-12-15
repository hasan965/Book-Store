from django.utils import translation
from .translations import TRANSLATIONS


def translations(request):
    """Return a translations mapping `t` for templates.

    Uses the bundled `TRANSLATIONS` dict in `UserApp/translations.py`.
    Falls back to English when a language or key is missing.
    """
    lang = translation.get_language() or 'en'
    lang = lang.split('-')[0]
    data = TRANSLATIONS.get(lang, TRANSLATIONS.get('en', {}))
    return {'t': data}
