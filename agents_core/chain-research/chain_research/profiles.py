"""Versioned, exact-scope profile loading. Draft policy is never a gold standard."""
import json
import re
from importlib.resources import files

from .models import IndustryProfile

PROFILE_IDS = ('notebook', 'liquor')


def normalize_topic(value):
    value = re.sub(r'\s+', '', value).casefold()
    return re.sub(r'(?:产业链图|产业链|行业全景|行业)$', '', value)


def load_profile(profile_id):
    if profile_id not in PROFILE_IDS:
        raise ValueError(f'Unknown profile ID: {profile_id}')
    raw = files('chain_research').joinpath('profile_data', profile_id + '.json').read_text(encoding='utf-8')
    return IndustryProfile.model_validate(json.loads(raw))


def resolve_profile(scope, *, strategy='profile_guided', profile_id=None):
    if strategy == 'explore':
        if profile_id:
            raise ValueError('explore cannot load a dedicated profile')
        return None
    matches = []
    for key in (profile_id,) if profile_id else PROFILE_IDS:
        profile = load_profile(key)
        if (profile.view_kind == scope.view_kind and profile.granularity == scope.granularity
                and normalize_topic(scope.subject) in {
                    normalize_topic(x) for x in [profile.subject, *profile.aliases]}):
            matches.append(profile)
    if profile_id and not matches:
        raise ValueError('Explicit profile does not match requested scope')
    if len(matches) > 1:
        raise ValueError('Ambiguous profile scope')
    return matches[0] if matches else None
