from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.conf import settings
from exams.models import Notification, ChatMessage, Exam
from itertools import chain
from operator import attrgetter
import json

@login_required()
@require_http_methods(["GET"])
def notifications_list(request):
    """List all notifications and messages for the user"""
    
    # Get the active tab (default to 'notifications')
    active_tab = request.GET.get('tab', 'notifications')
    
    # Fetch unread counts for badges
    unread_notifications_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    unread_chats_count = ChatMessage.objects.filter(recipient=request.user, is_read=False).count()
    
    # Initialize variables
    page_obj = None
    
    if active_tab == 'chats':
        # Fetch chat messages
        chats = ChatMessage.objects.filter(recipient=request.user).order_by('-created_at')
        
        # Paginate chats
        paginator = Paginator(chats, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # Add attributes for template
        for c in page_obj:
            c.type = 'chat'
            c.title = f"Message from {c.sender.get_full_name() or c.sender.username}"
            c.category = 'primary'
            
    else:
        # Default to notifications
        active_tab = 'notifications' # Normalize
        
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
        
        # Paginate notifications
        paginator = Paginator(notifications, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # Add attributes for template
        for n in page_obj:
            n.type = 'notification'
            n.category = 'info'
    
    context = {
        'active_tab': active_tab,
        'notifications': page_obj, # This variable name is used in template loop, keeping it generic
        'unread_notifications_count': unread_notifications_count,
        'unread_chats_count': unread_chats_count,
        'unread_count': unread_notifications_count + unread_chats_count, # Total unread
    }
    
    return render(request, 'notifications/list.html', context)

@login_required()
@require_http_methods(["GET"])
def get_unread_notifications(request):
    """API endpoint to get unread notifications (AJAX)"""
    # Fetch unread notifications and chats
    notifications = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).order_by('-created_at')[:5]
    
    chats = ChatMessage.objects.filter(
        recipient=request.user,
        is_read=False
    ).order_by('-created_at')[:5]
    
    # Calculate total count
    count = (Notification.objects.filter(recipient=request.user, is_read=False).count() + 
             ChatMessage.objects.filter(recipient=request.user, is_read=False).count())
    
    notification_data = [
        {
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'is_read': n.is_read,
            'type': 'notification'
        }
        for n in notifications
    ]
    
    chat_data = [
        {
            'id': c.id,
            'title': f"Message from {c.sender.username}",
            'message': c.message,
            'is_read': c.is_read,
            'type': 'chat'
        }
        for c in chats
    ]
    
    # Combine and return
    combined = notification_data + chat_data
    # Simple sort by ID (proxy for recent) or just return mixed
    # We won't implement complex sorting for the popup preview for now
    
    data = {
        'count': count,
        'notifications': combined
    }
    
    return JsonResponse(data)

@login_required()
@require_http_methods(["POST"])
def mark_as_read(request):
    """Mark a notification as read"""
    try:
        data = json.loads(request.body)
        notification_id = data.get('notification_id')
        item_type = data.get('type', 'notification') # Default to notification
        
        if item_type == 'chat':
             # Note: ChatMessage model might not have a simple ID lookup if we want to be safe, but let's assume ID is sufficient
             chat = ChatMessage.objects.get(id=notification_id, recipient=request.user)
             chat.is_read = True
             chat.save()
        else:
            notification = Notification.objects.get(
                id=notification_id,
                recipient=request.user
            )
            notification.is_read = True
            notification.save()
        
        # Recalculate total count
        count = (Notification.objects.filter(recipient=request.user, is_read=False).count() + 
                 ChatMessage.objects.filter(recipient=request.user, is_read=False).count())
        
        return JsonResponse({
            'success': True,
            'message': 'Marked as read',
            'unread_count': count
        })
    except (Notification.DoesNotExist, ChatMessage.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Item not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required()
@require_http_methods(["POST"])
def mark_all_as_read(request):
    """Mark all notifications and chats as read"""
    # Optional: check if type is specified in query params or body to only mark specific type
    # For now, let's check request GET or POST
    target_type = request.GET.get('type') or request.POST.get('type')
    
    if target_type == 'notifications':
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    elif target_type == 'chats':
        ChatMessage.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    else:
        # Mark ALL
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        ChatMessage.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    
    return JsonResponse({
        'success': True,
        'message': 'Marked as read',
        'unread_count': 0 if not target_type else (
             Notification.objects.filter(recipient=request.user, is_read=False).count() + 
             ChatMessage.objects.filter(recipient=request.user, is_read=False).count()
        )
    })

# ── Web Push endpoints ──────────────────────────────────────────────────────

@login_required
@require_http_methods(['POST'])
def push_subscribe(request):
    """Save a browser push subscription for the logged-in user."""
    from dashboards.models import PushSubscription
    try:
        data = json.loads(request.body)
        PushSubscription.objects.update_or_create(
            endpoint=data['endpoint'],
            defaults={
                'user': request.user,
                'p256dh': data['keys']['p256dh'],
                'auth': data['keys']['auth'],
            }
        )
        return JsonResponse({'status': 'subscribed'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)


@login_required
@require_http_methods(['POST'])
def push_unsubscribe(request):
    """Remove a push subscription."""
    from dashboards.models import PushSubscription
    try:
        data = json.loads(request.body)
        PushSubscription.objects.filter(endpoint=data['endpoint']).delete()
        return JsonResponse({'status': 'unsubscribed'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)


@login_required
def push_vapid_public_key(request):
    """Return the VAPID public key so the frontend can subscribe."""
    return JsonResponse({'publicKey': settings.VAPID_PUBLIC_KEY})


# ── Existing views ───────────────────────────────────────────────────────────

@login_required()
@require_http_methods(["DELETE"])
def delete_notification(request, notification_id):
    """Delete a notification or chat message"""
    target_type = request.GET.get('type', 'notification')
    
    try:
        if target_type == 'chat':
            item = ChatMessage.objects.get(
                id=notification_id,
                recipient=request.user
            )
        else:
            item = Notification.objects.get(
                id=notification_id,
                recipient=request.user
            )
            
        item.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'{target_type.title()} deleted'
        })
    except (Notification.DoesNotExist, ChatMessage.DoesNotExist):
        return JsonResponse({
            'success': False,
            'error': 'Item not found'
        }, status=404)

@login_required()
@require_http_methods(["GET"])
def notification_detail(request, notification_id):
    """Get detail of a specific notification"""
    try:
        notification = Notification.objects.get(
            id=notification_id,
            recipient=request.user
        )
        
        # Mark as read
        if not notification.is_read:
            notification.is_read = True
            notification.save()
            
        # Inject defaults for template compatibility
        notification.category = 'info'
        if notification.related_exam:
            try:
                notification.related_exam_obj = Exam.objects.get(id=notification.related_exam)
            except Exam.DoesNotExist:
                notification.related_exam_obj = None
        
        context = {
            'notification': notification,
        }
        
        return render(request, 'notifications/detail.html', context)
    except Notification.DoesNotExist:
        return render(request, 'notifications/not_found.html', status=404)
