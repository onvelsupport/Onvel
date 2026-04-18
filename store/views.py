from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from decimal import Decimal
import stripe

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail

from .models import Product, Order, OrderItem
from .forms import CheckoutForm

stripe.api_key = settings.STRIPE_SECRET_KEY


def home(request):
    products = Product.objects.all().order_by('-created_at')
    return render(request, 'store/index.html', {'products': products})


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    return render(request, 'store/product_detail.html', {'product': product})


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    cart = request.session.get('cart', {})
    product_id_str = str(product_id)

    if product_id_str in cart:
        cart[product_id_str] += 1
    else:
        cart[product_id_str] = 1

    request.session['cart'] = cart
    return redirect('cart')


def cart_view(request):
    cart = request.session.get('cart', {})
    cart_items = []
    total = Decimal('0.00')

    for product_id, quantity in cart.items():
        product = get_object_or_404(Product, id=product_id)
        item_total = product.price * quantity
        total += item_total

        cart_items.append({
            'product': product,
            'quantity': quantity,
            'item_total': item_total,
        })

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'total': total,
    })


def remove_from_cart(request, product_id):
    cart = request.session.get('cart', {})
    product_id_str = str(product_id)

    if product_id_str in cart:
        del cart[product_id_str]

    request.session['cart'] = cart
    return redirect('cart')


def update_cart_quantity(request, product_id, action):
    cart = request.session.get('cart', {})
    product_id_str = str(product_id)

    if product_id_str in cart:
        if action == 'increase':
            cart[product_id_str] += 1
        elif action == 'decrease':
            cart[product_id_str] -= 1

            if cart[product_id_str] <= 0:
                del cart[product_id_str]

    request.session['cart'] = cart
    return redirect('cart')


def terms(request):
    return render(request, 'store/terms.html')


def refund(request):
    return render(request, 'store/refund.html')


def contact(request):
    return render(request, 'store/contact.html')


def privacy(request):
    return render(request, 'store/privacy.html')


def checkout_view(request):
    cart = request.session.get('cart', {})
    cart_items = []
    total = Decimal('0.00')

    if not cart:
        return redirect('cart')

    for product_id, quantity in cart.items():
        product = get_object_or_404(Product, id=product_id)
        item_total = product.price * quantity
        total += item_total

        cart_items.append({
            'product': product,
            'quantity': quantity,
            'item_total': item_total,
        })

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            order = Order.objects.create(
                full_name=form.cleaned_data['full_name'],
                email=form.cleaned_data['email'],
                address=form.cleaned_data['address'],
                city=form.cleaned_data['city'],
                postcode=form.cleaned_data['postcode'],
                country=form.cleaned_data['country'],
                total_price=total,
            )

            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    price=item['product'].price,
                )

            line_items = []
            for item in cart_items:
                line_items.append({
                    'price_data': {
                        'currency': 'gbp',
                        'product_data': {
                            'name': item['product'].name,
                        },
                        'unit_amount': int(item['product'].price * 100),
                    },
                    'quantity': item['quantity'],
                })

            try:
                checkout_session = stripe.checkout.Session.create(
                    mode='payment',
                    line_items=line_items,
                    success_url=request.build_absolute_uri('/checkout/success/') + '?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url=request.build_absolute_uri('/checkout/'),
                    customer_email=form.cleaned_data['email'],
                    metadata={
                        'order_id': str(order.id),
                        'customer_name': form.cleaned_data['full_name'],
                    },
                )

                order.stripe_session_id = checkout_session.id
                order.save()

                return redirect(checkout_session.url, code=303)

            except stripe.error.StripeError as e:
                order.delete()
                return render(request, 'store/checkout.html', {
                    'form': form,
                    'cart_items': cart_items,
                    'total': total,
                    'error': str(e),
                })
    else:
        form = CheckoutForm()

    return render(request, 'store/checkout.html', {
        'form': form,
        'cart_items': cart_items,
        'total': total,
    })


def checkout_success(request):
    request.session['cart'] = {}
    return render(request, 'store/checkout_success.html')


@csrf_exempt
def stripe_webhook(request):
    print("Webhook endpoint hit")

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        print("Event verified:", event['type'])
    except ValueError:
        print("Invalid payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        print("Invalid signature")
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        print("Checkout session completed")

        session = event['data']['object']
        session_id = session.get('id')
        print("Session ID:", session_id)

        try:
            order = Order.objects.get(stripe_session_id=session_id)
            print("Order found:", order.order_number)
        except Order.DoesNotExist:
            print("Order not found")
            return HttpResponse(status=200)

        if not order.is_paid:
            order.is_paid = True
            order.save()
            print("Order marked as paid")

            order_items = order.items.all()
            item_lines = []
            for item in order_items:
                item_lines.append(f"{item.product.name} x {item.quantity} - £{item.price}")

            items_text = "\n".join(item_lines)

            subject = f"ONVEL Order Confirmation #{order.order_number}"
            message = (
                f"Hello {order.full_name},\n\n"
                f"Thank you for your order from ONVEL.\n\n"
                f"Order Number: {order.order_number}\n"
                f"Total Paid: £{order.total_price}\n\n"
                f"Items:\n{items_text}\n\n"
                f"Shipping Address:\n"
                f"{order.address}\n"
                f"{order.city}\n"
                f"{order.postcode}\n"
                f"{order.country}\n\n"
                f"We’ll send another update when your order is dispatched.\n\n"
                f"ONVEL"
            )

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [order.email],
                fail_silently=False,
            )
            print("Email send function ran")

    return HttpResponse(status=200)