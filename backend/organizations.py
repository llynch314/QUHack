"""Verified healthcare organisations, matched by the email domain providers sign in with.

The list lives in data/verified_organizations.csv (columns: name, domain). Add a row per
hospital or clinic. A provider whose Google-verified email is at a listed domain (or a
subdomain of it, e.g. psych.cityhospital.example) gets that organisation automatically and
a "Verified" badge patients can see. Everyone else can still be a provider, shown as unverified.

The demo list uses .example domains, which are reserved and can't belong to a real organisation.
"""
import csv
import os
from functools import lru_cache

ORGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'verified_organizations.csv')


@lru_cache(maxsize=1)
def _domains():
    """{domain: organisation name}, loaded once."""
    try:
        with open(ORGS_FILE, newline='', encoding='utf-8') as f:
            return {row['domain'].strip().lower().lstrip('@'): row['name'].strip()
                    for row in csv.DictReader(f) if row.get('domain') and row.get('name')}
    except FileNotFoundError:
        return {}


def organization_for_email(email):
    """Name of the verified organisation for this email address, or None."""
    if not email or '@' not in email:
        return None
    domain = email.rsplit('@', 1)[1].strip().lower()
    orgs = _domains()
    # Exact domain or any subdomain of it, but never a lookalike such as evilcityhospital.example.
    parts = domain.split('.')
    for i in range(len(parts) - 1):
        name = orgs.get('.'.join(parts[i:]))
        if name:
            return name
    return None
