from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from accounts.models import User
from pathlib import Path
import os
import boto3
from datetime import datetime

# ========================= BACKUP & RESTORE =========================

from django.core.paginator import Paginator

@login_required()
def admin_backup_restore(request):
    if request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:dashboard_redirect')
        
    # List Local Backups
    local_backups_list = []
    backup_dir = Path(settings.BASE_DIR) / "backups"
    if backup_dir.exists():
        for f in backup_dir.iterdir():
            if f.is_file() and f.suffix == '.json':
                local_backups_list.append({
                    'name': f.name,
                    'size': f"{f.stat().st_size / (1024*1024):.2f} MB",
                    'date': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    local_backups_list.sort(key=lambda x: x['name'], reverse=True)
    
    # Paginate Local Backups
    paginator_local = Paginator(local_backups_list, 5) # Show 5 per page
    page_number_local = request.GET.get('page_local')
    local_backups = paginator_local.get_page(page_number_local)

    # List AWS Backups
    aws_backups_list = []
    aws_error = None
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        folder = getattr(settings, 'AWS_BACKUP_FOLDER', 'backups')
        
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder)
        if 'Contents' in response:
            for obj in response['Contents']:
                if obj['Key'].endswith('.json'):
                    aws_backups_list.append({
                        'name': os.path.basename(obj['Key']),
                        'key': obj['Key'],
                        'size': f"{obj['Size'] / (1024*1024):.2f} MB",
                        'date': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S')
                    })
        aws_backups_list.sort(key=lambda x: x['date'], reverse=True)
    except Exception as e:
        aws_error = str(e)

    # Paginate AWS Backups
    paginator_aws = Paginator(aws_backups_list, 5) # Show 5 per page
    page_number_aws = request.GET.get('page_aws')
    aws_backups = paginator_aws.get_page(page_number_aws)

    return render(request, 'dashboards/admin/backup_restore.html', {
        'local_backups': local_backups,
        'aws_backups': aws_backups,
        'aws_error': aws_error
    })

@login_required()
@require_POST
def delete_backup(request):
    if request.user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    source_type = request.POST.get('source_type')
    filename = request.POST.get('filename')
    
    try:
        if source_type == 'local':
            backup_dir = Path(settings.BASE_DIR) / "backups"
            file_path = backup_dir / filename
            if file_path.exists() and file_path.suffix == '.json':
                os.remove(file_path)
                messages.success(request, f'Local backup "{filename}" deleted successfully.')
            else:
                messages.error(request, 'File not found or invalid.')
                
        elif source_type == 'aws':
            import boto3
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME,
            )
            bucket = settings.AWS_STORAGE_BUCKET_NAME
            # filename passed here should be the full Key (e.g. backups/file.json) or name
            # In the template loop for AWS, we store 'key' in the dict. We should use that.
            # Let's assume the POST data sends the 'key' as 'filename' for simplicity or verify.
            # In list loop: 'key': obj['Key']. 
            # I will ensure the form sends this key.
            
            s3.delete_object(Bucket=bucket, Key=filename)
            messages.success(request, f'AWS backup "{os.path.basename(filename)}" deleted successfully.')
            
        else:
            messages.error(request, 'Invalid source type.')
            
    except Exception as e:
        messages.error(request, f'Delete failed: {str(e)}')
        
    return redirect('dashboards:admin_backup_restore')


@login_required()
@require_POST
def trigger_backup(request):
    if request.user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    backup_type = request.POST.get('backup_type', 'local')
    
    # Import here to avoid circular imports if any
    from school_sms.task import backup_project_data
    
    # Trigger task (using delay for async if Celery is running, otherwise sync if configured eagerly)
    # Using delay() assumes Celery worker is running. If not, it might not run.
    # For safety in this environment (local/dev?), we might want to run it synchronously if desired, 
    # but the user asked for "trigger", implying async.
    # However, to ensure it works for the user immediately without worker, I'll check if I should run sync.
    # But best practice is async. I'll use .delay() and tell user it started.
    # UPDATE: User environment might not have celery worker running. 
    # To be safe and ensure the user sees the result, I will run it synchronously for now 
    # OR catch the error if delay fails (which it won't, it just queues).
    # Given "trigger... restore or backup", I'll run it synchronously for immediate feedback 
    # unless it takes too long. A full dumpdata might take a few seconds.
    # I'll run it synchronously for this interaction to ensure "verification".
    
    try:
        # Run synchronously for reliability in this demo/session
        result = backup_project_data(backup_type=backup_type)
        messages.success(request, f'Backup completed successfully: {result}')
    except Exception as e:
        messages.error(request, f'Backup failed: {str(e)}')
        
    return redirect('dashboards:admin_backup_restore')

@login_required()
@require_POST
def trigger_restore(request):
    if request.user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    source_type = request.POST.get('source_type')
    source_path = request.POST.get('source_path')
    
    from school_sms.task import restore_project_data
    
    try:
        # Run synchronously
        restore_project_data(source_type=source_type, source_path=source_path)
        messages.success(request, 'System restored successfully.')
    except Exception as e:
        messages.error(request, f'Restore failed: {str(e)}')
        
    return redirect('dashboards:admin_backup_restore')
