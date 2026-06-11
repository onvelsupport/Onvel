from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),

    path('cart/', views.cart_view, name='cart'),

    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),

    path('cart/remove/<str:cart_key>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/update/<str:cart_key>/<str:action>/', views.update_cart_quantity, name='update_cart_quantity'),

    path('terms/', views.terms, name='terms'),
    path('refund/', views.refund, name='refund'),
    path('contact/', views.contact, name='contact'),
    path('privacy/', views.privacy, name='privacy'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('checkout/success/', views.checkout_success, name='checkout_success'),
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),


    path('square/success/', views.square_success, name='square_success'),

    path("track-order/", views.tracking, name="tracking"),
    path("track-order/result/", views.tracking_result, name="tracking_result"),
    path("track-order/result/<int:order_id>/", views.tracking_result_with_id, name="tracking_result_with_id"),
    path("invoice/<int:order_id>/download/", views.download_invoice, name="download_invoice"),
    path("order/<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
]