"""Show saved expression readings straight from the SQL database (for demos).

    python show_expressions.py            # latest 20 readings
    python show_expressions.py --follow   # keep printing new readings as they arrive
"""
import argparse
import logging
import time

logging.disable(logging.WARNING)   # keep the demo output clean

from app import app  # noqa: E402
from models import ExpressionReading, User, as_utc, db  # noqa: E402


def fmt(reading, user):
    when = as_utc(reading.created_at).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    return f'{reading.id:>5}  {when}  {(user.name or "?")[:20]:<20}  {reading.emotion:<9} {reading.source}'


def rows(after_id=0, limit=None):
    q = (db.session.query(ExpressionReading, User).join(User)
         .filter(ExpressionReading.id > after_id).order_by(ExpressionReading.id.desc()))
    if limit:
        q = q.limit(limit)
    return list(reversed(q.all()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--follow', action='store_true', help='keep watching for new readings')
    parser.add_argument('-n', type=int, default=20, help='how many recent readings to show first')
    args = parser.parse_args()

    with app.app_context():
        print(f'Database: {db.engine.url}')
        print(f'{"ID":>5}  {"Time":<19}  {"User":<20}  {"Emotion":<9} Source')
        print('-' * 66)
        last_id = 0
        for reading, user in rows(limit=args.n):
            print(fmt(reading, user))
            last_id = reading.id
        if not last_id:
            print('(no readings yet - sign in, opt in to saving, and turn on the camera in Chat)')
        if not args.follow:
            return
        print('Watching for new readings... (Ctrl+C to stop)')
        try:
            while True:
                time.sleep(2)
                db.session.expire_all()   # see rows written by the web app
                for reading, user in rows(after_id=last_id):
                    print(fmt(reading, user), flush=True)
                    last_id = reading.id
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
