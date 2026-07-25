from django.conf import settings
from exams.models import Notification, ChatMessage


def school_context(request):
    context = {
        "SCHOOL_NAME": settings.SCHOOL_NAME,
        "SCHOOL_SLOGAN": settings.SCHOOL_SLOGAN,
        "PORTAL_DOMAIN": settings.PORTAL_DOMAIN,
        "SCHOOL_ECOMMERCE": settings.SCHOOL_ECOMMERCE,
        "SCHOOL_FACEBOOK_URL": settings.SCHOOL_FACEBOOK_URL,
        "SCHOOL_TWITTER_URL": settings.SCHOOL_TWITTER_URL,
        "SCHOOL_INSTAGRAM_URL": settings.SCHOOL_INSTAGRAM_URL,
        "SCHOOL_YOUTUBE_URL": settings.SCHOOL_YOUTUBE_URL,
        "SCHOOL_PHONE": settings.SCHOOL_PHONE,
        "SCHOOL_APP_NAME": settings.SCHOOL_APP_NAME,
        "SCHOOL_EMAIL": settings.SCHOOL_EMAIL,
        "SCHOOL_ADDRESS": settings.SCHOOL_ADDRESS,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "VAPID_PUBLIC_KEY": getattr(settings, 'VAPID_PUBLIC_KEY', ''),
    }

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        unread_notifications = Notification.objects.filter(
            recipient=user,
            is_read=False,
        ).count()

        unread_chats = ChatMessage.objects.filter(
            recipient=user,
            is_read=False,
        ).count()

        recent_notifications = list(
            Notification.objects.filter(recipient=user)
            .order_by('-created_at')[:5]
        )

        recent_chats = list(
            ChatMessage.objects.filter(recipient=user, is_read=False)
            .order_by('-created_at')[:5]
        )

        context.update({
            'unread_notifications_count': unread_notifications,
            'unread_chats_count': unread_chats,
            'total_unread_count': unread_notifications + unread_chats,
            'recent_notifications': recent_notifications,
            'recent_chats': recent_chats,
        })

    return context
