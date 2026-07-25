"""
Web Push notification utility using pywebpush + VAPID.
Usage:
    from dashboards.push_utils import send_push_to_user, send_push_to_all

    send_push_to_user(user, title="Exam Alert", body="Your exam starts in 15 mins")
    send_push_to_all(title="School Notice", body="School closes early today")
"""

import json
import logging
from django.conf import settings
from pywebpush import webpush, WebPushException

logger = logging.getLogger('project')


def _send(subscription, title, body, url='/', icon='/static/images/school_logo.png'):
    """Send a single push notification to one subscription."""
    payload = json.dumps({'title': title, 'body': body, 'url': url, 'icon': icon})
    try:
        webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f'mailto:{settings.VAPID_ADMIN_EMAIL}'},
        )
        return True
    except WebPushException as e:
        # 410 Gone = subscription expired/revoked — delete it
        if e.response and e.response.status_code in (404, 410):
            subscription.delete()
            logger.info(f'Deleted stale push subscription: {subscription.endpoint[:60]}')
        else:
            logger.error(f'WebPush failed: {e}')
        return False


def send_push_to_user(user, title, body, url='/', icon='/static/images/school_logo.png'):
    """Send push notification to all devices of a single user."""
    from dashboards.models import PushSubscription
    subs = PushSubscription.objects.filter(user=user)
    for sub in subs:
        _send(sub, title, body, url, icon)


def send_push_to_users(users, title, body, url='/', icon='/static/images/school_logo.png'):
    """Send push notification to a queryset/list of users."""
    from dashboards.models import PushSubscription
    subs = PushSubscription.objects.filter(user__in=users)
    for sub in subs:
        _send(sub, title, body, url, icon)


def send_push_to_all(title, body, url='/', icon='/static/images/school_logo.png'):
    """Broadcast push notification to every subscribed user."""
    from dashboards.models import PushSubscription
    for sub in PushSubscription.objects.all():
        _send(sub, title, body, url, icon)


def send_push_to_role(role, title, body, url='/', icon='/static/images/school_logo.png'):
    """Send push to all users with a specific role e.g. 'STUDENT', 'TEACHER'."""
    from dashboards.models import PushSubscription
    subs = PushSubscription.objects.filter(user__role=role)
    for sub in subs:
        _send(sub, title, body, url, icon)
