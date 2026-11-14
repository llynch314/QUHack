"""Phone push notifications to family members, sent with ntfy (https://ntfy.sh).

No account or keys: each family member gets a random topic name, subscribes to it
in the free ntfy app (Android / iPhone), and alerts arrive as phone notifications.
The topic name works like a password - anyone who knows it can read the notifications
- so it is long and random, and the family member can replace it at any time.

Set NTFY_SERVER in backend/.env to use your own ntfy server instead of ntfy.sh.
Notifications never include chat text or the patient's note.
"""
import logging
import os
import secrets
import threading

import requests

log = logging.getLogger(__name__)


def server():
    return (os.getenv('NTFY_SERVER') or 'https://ntfy.sh').strip().rstrip('/')


# Short, friendly words so the topic name is easy to read and type on a phone.
_WORDS = """
acorn amber apple apricot aspen autumn bamboo basil beach berry birch bloom blossom breeze brook
butter cabin candle canyon cedar cherry cider clover cloud cocoa comet coral cotton cozy creek
crystal daisy dawn delta dewdrop dove dream dune ember fable feather fern field firefly flint
forest fox garden gentle ginger glade glow golden grove harbor harvest hazel heron hill honey
horizon indigo island ivy jade jasmine juniper kettle kite lagoon lantern lark laurel lavender
lemon lily linen lotus lucky lunar maple marble meadow mellow melody mint misty moon moss
nectar nest nova oak oasis ocean olive orchard otter owl palm panda pebble peach pearl pepper
petal pine plum pond poppy prairie quail quiet rain raven reef ripple river robin rose ruby
saffron sage sail sandy sapphire shell silver sky snow sparrow spring spruce star stone summer
sunny swan teal thistle thunder tide tulip twilight valley velvet violet walnut wave willow
willow wind winter wren yarrow zephyr
""".split()
_WORDS = sorted(set(_WORDS))


def new_topic():
    """e.g. 'attune-maple-otter-river-4821': ~44 bits of randomness, but easy to read and type."""
    words = '-'.join(secrets.choice(_WORDS) for _ in range(4))
    return f'attune-{words}-{secrets.randbelow(10000):04d}'


def topic_url(topic):
    return f'{server()}/{topic}'


def send_push(topic, title, message, click=None, urgent=False):
    """Send one notification now. Raises on an error so callers can report it."""
    payload = {'topic': topic, 'title': title, 'message': message,
               'priority': 5 if urgent else 3, 'tags': ['rotating_light'] if urgent else ['bell']}
    if click:
        payload['click'] = click
    res = requests.post(server(), json=payload, timeout=10)
    res.raise_for_status()
    log.info('Push notification sent to topic %s...', topic[:16])


def _send_all(notifications):
    for kwargs in notifications:
        try:
            send_push(**kwargs)
        except Exception:
            log.exception('Could not send push notification')


def dispatch(notifications):
    """Send in the background so the chat reply isn't held up."""
    if notifications:
        threading.Thread(target=_send_all, args=(notifications,), daemon=True).start()
