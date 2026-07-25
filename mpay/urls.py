

from django.urls import path
from . import views 
from . import admin_views
from django.urls import path



app_name = "mpay"

urlpatterns = [
    path("", views.store_view, name="store"),
    path("select-ward/", views.select_ward, name="select_ward"),
    path("products/", views.product_list, name="products"),
    path("cart/add/", views.add_to_cart, name="cart_add"),
    path("cart/update/", views.update_cart_item, name="cart_update"),
    path("cart/sidebar/", views.cart_sidebar, name="cart_sidebar"),
    path("cart/count/", views.cart_count, name="cart_count"),
    path("cart/remove-item/", views.remove_cart_item, name="cart_remove_item"),
    path("cart/clear/", views.clear_cart, name="cart_clear"),

    path("checkout/", views.checkout, name="checkout"),
    path("checkout/<uuid:order_id>/", views.checkout_detail, name="checkout_detail"),
    path("orders/", views.parent_orders, name="parent_orders"),

    path("receipt/<int:tx_id>/pdf/", views.payment_receipt_pdf, name="receipt_pdf"),
    # =======================
    # ADMIN DASHBOARD
    # =======================
    
    path("admin/dashboard/", admin_views.admin_dashboard, name="admin_dashboard"),

    # =======================
    # PRODUCTS & STOCK
    # =======================

    path("admin/orders/<uuid:pk>/", admin_views.admin_order_detail, name="admin_order_detail"),
    
    # Stock control
    path("admin/products/add/", admin_views.admin_add_product, name="admin_add_product"),
    path("admin/products/", admin_views.admin_product_list, name="admin_product_list"),
    path("admin/products/<uuid:pk>/edit/", admin_views.admin_product_edit, name="admin_product_edit"),
    path("admin/products/<uuid:pk>/delete/", admin_views.admin_product_delete, name="admin_product_delete"),
    
    # path("admin/products/<int:pk>/stock/add/", admin_views.admin_add_stock, name="admin_add_stock"),
    # path("admin/products/<int:pk>/stock/remove/", admin_views.admin_remove_stock, name="admin_remove_stock"),

    # =======================
    # ORDERS & PAYMENTS
    # =======================
    path("admin/orders/", admin_views.admin_order_list, name="admin_order_list"),
    path("admin/orders/<uuid:pk>/", admin_views.admin_order_detail, name="admin_order_detail"),

    path("admin/payments/", admin_views.admin_payment_list, name="admin_payment_list"),
    path("admin/payments/<int:pk>/", admin_views.admin_payment_detail, name="admin_payment_detail"),

    # =======================   
    # ACCESS UNLOCKS
    # =======================
    path("admin/access/", admin_views.admin_access_list, name="admin_access_list"),
    path("admin/mercy/", admin_views.admin_mercy_access, name="admin_mercy_access"),
    
    path("admin/access/grant/<int:order_id>/", admin_views.admin_grant_access, name="admin_grant_access"),
    
    path("admin/access/revoke/<int:access_id>/", admin_views.admin_revoke_access, name="admin_revoke_access"),

    # =======================
    # TRANSACTION LOGS
    # =======================
    path("admin/transactions/", admin_views.admin_transaction_logs, name="admin_transaction_logs"),
    path("admin/analytics/", admin_views.admin_analytics_dashboard, name="admin_analytics"),
    path("admin/analytics/export/", admin_views.export_revenue_csv, name="export_revenue_csv"),

    # 👉 Paystack init
    # =======================
    # PAYMENT GATEWAYS
    # =======================
    path('paystack/init/<str:order_id>/', views.paystack_initialize, name='paystack_init'),
    
    # 👉 Paystack callback (redirect)
    path("paystack/callback/", views.paystack_callback, name="paystack_callback"),

    # 👉 Webhook (POST only, no CSRF)
    path("paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("payment_status_check/", views.payment_status_check, name="payment_status_check"),
    path("admin/webhooks/", views.webhook_monitor, name="webhook_monitor"),





]




