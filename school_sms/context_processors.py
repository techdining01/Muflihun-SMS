from django.conf import settings


def school_context(request):
    try:
        context = {
            "SCHOOL_NAME": getattr(settings, 'SCHOOL_NAME', 'Muflihun High School'),
            "SCHOOL_SLOGAN": getattr(settings, 'SCHOOL_SLOGAN', ''),
            "PORTAL_DOMAIN": getattr(settings, 'PORTAL_DOMAIN', ''),
            "SCHOOL_ECOMMERCE": getattr(settings, 'SCHOOL_ECOMMERCE', 'Store'),
            "SCHOOL_FACEBOOK_URL": getattr(settings, 'SCHOOL_FACEBOOK_URL', '#'),
            "SCHOOL_TWITTER_URL": getattr(settings, 'SCHOOL_TWITTER_URL', '#'),
            "SCHOOL_INSTAGRAM_URL": getattr(settings, 'SCHOOL_INSTAGRAM_URL', '#'),
            "SCHOOL_YOUTUBE_URL": getattr(settings, 'SCHOOL_YOUTUBE_URL', '#'),
            "SCHOOL_PHONE": getattr(settings, 'SCHOOL_PHONE', ''),
            "SCHOOL_APP_NAME": getattr(settings, 'SCHOOL_APP_NAME', ''),
            "SCHOOL_EMAIL": getattr(settings, 'SCHOOL_EMAIL', 'muflihunhighschool@gmail.com'),
            "SCHOOL_ADDRESS": getattr(settings, 'SCHOOL_ADDRESS', ''),
            "CURRENCY_SYMBOL": getattr(settings, 'CURRENCY_SYMBOL', '₦'),
            "VAPID_PUBLIC_KEY": getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        }
    except Exception:
        # Fallback if settings aren't available
        context = {
            "SCHOOL_NAME": "Muflihun High School",
            "SCHOOL_SLOGAN": "",
            "PORTAL_DOMAIN": "",
            "SCHOOL_ECOMMERCE": "Store",
            "SCHOOL_FACEBOOK_URL": "#",
            "SCHOOL_TWITTER_URL": "#",
            "SCHOOL_INSTAGRAM_URL": "#",
            "SCHOOL_YOUTUBE_URL": "#",
            "SCHOOL_PHONE": "",
            "SCHOOL_APP_NAME": "",
            "SCHOOL_EMAIL": "muflihunhighschool@gmail.com",
            "SCHOOL_ADDRESS": "",
            "CURRENCY_SYMBOL": "₦",
            "VAPID_PUBLIC_KEY": "",
        }

    # Only add notification context if user is authenticated and models are available
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        try:
            from exams.models import Notification, ChatMessage
            
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
        except Exception:
            # If models aren't available yet, provide defaults
            context.update({
                'unread_notifications_count': 0,
                'unread_chats_count': 0,
                'total_unread_count': 0,
                'recent_notifications': [],
                'recent_chats': [],
            })
    else:
        # Provide default values for unauthenticated users
        context.update({
            'unread_notifications_count': 0,
            'unread_chats_count': 0,
            'total_unread_count': 0,
            'recent_notifications': [],
            'recent_chats': [],
        })

    return context
