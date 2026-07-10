from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.template.loader import render_to_string


from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from io import BytesIO

from decimal import Decimal
import stripe
import uuid
import requests

from .models import Product, ProductSize, Order, OrderItem
from .forms import CheckoutForm



def get_payment_method_label(session):
    try:
        payment_intent_id = session.get("payment_intent")

        if not payment_intent_id:
            return "CARD"

        payment_intent = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=["latest_charge"]
        )

        latest_charge = payment_intent.get("latest_charge")

        if not latest_charge:
            return "CARD"

        payment_method_details = latest_charge.get("payment_method_details", {})
        pm_type = payment_method_details.get("type")

        if pm_type == "card":
            card = payment_method_details.get("card", {})
            wallet = card.get("wallet")

            if wallet:
                wallet_type = wallet.get("type")

                if wallet_type == "apple_pay":
                    return "APPLE PAY"

                if wallet_type == "google_pay":
                    return "GOOGLE PAY"

                if wallet_type == "samsung_pay":
                    return "SAMSUNG PAY"

            brand = card.get("brand")

            if brand:
                return brand.replace("_", " ").upper()

            return "CARD"

        if pm_type:
            return pm_type.replace("_", " ").upper()

        return "CARD"

    except Exception as e:
        print("Could not determine payment method:", str(e))
        return "CARD"


def send_order_confirmation_email(order, session):
    import resend

    print("=== send_order_confirmation_email started ===")

    resend.api_key = settings.RESEND_API_KEY

    order_items = order.items.all()
    payment_method_label = get_payment_method_label(session)

    recipient_email = (
        session.get("customer_email")
        or session.get("customer_details", {}).get("email")
        or order.email
    )

    print("Order:", order.id)
    print("Recipient:", recipient_email)
    print("From:", settings.DEFAULT_FROM_EMAIL)

    if not recipient_email:
        raise Exception("No customer email found for order confirmation")

    subject = f"ONV Order Confirmation #{order.order_number}"

    context = {
        "order": order,
        "order_items": order_items,
        "tracking_url": "https://www.onvel.store/track-order/",
        "payment_method": payment_method_label,
        "subtotal": order.total_price,
        "delivery_cost": 0,
        "delivery_discount": 0,
        "discount": 0,
        "total": order.total_price,
    }

    print("About to render templates...")

    text_content = render_to_string(
        "store/emails/order_confirmation.txt",
        context
    )

    html_content = render_to_string(
        "store/emails/order_confirmation.html",
        context
    )

    print("Templates rendered successfully")
    print("Calling Resend API...")

    response = resend.Emails.send({
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": [recipient_email],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    })

    print("Resend response:", response)

    return response


def home(request):
    products = Product.objects.all().order_by("-created_at")
    return render(request, "store/index.html", {"products": products})


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    return render(request, "store/product_detail.html", {"product": product})


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method != "POST":
        return redirect("product_detail", slug=product.slug)

    selected_size = request.POST.get("size", "").strip()

    if product.sizes.exists():
        if not selected_size:
            return redirect("product_detail", slug=product.slug)

        size_obj = get_object_or_404(ProductSize, product=product, size=selected_size)

        if size_obj.stock < 1:
            return redirect("product_detail", slug=product.slug)
    else:
        selected_size = None

    cart = request.session.get("cart", {})
    cart_key = f"{product_id}_{selected_size}" if selected_size else str(product_id)

    if cart_key in cart:
        cart[cart_key]["quantity"] += 1
    else:
        cart[cart_key] = {
            "product_id": product_id,
            "size": selected_size,
            "quantity": 1,
        }

    request.session["cart"] = cart
    request.session.modified = True

    return redirect("cart")


def cart_view(request):
    cart = request.session.get("cart", {})
    cart_items = []
    total = Decimal("0.00")

    for cart_key, item_data in cart.items():
        product = get_object_or_404(Product, id=item_data["product_id"])
        quantity = int(item_data["quantity"])
        size = item_data.get("size")

        item_total = product.price * quantity
        total += item_total

        cart_items.append({
            "cart_key": cart_key,
            "product": product,
            "size": size,
            "quantity": quantity,
            "item_total": item_total,
        })

    return render(request, "store/cart.html", {
        "cart_items": cart_items,
        "total": total,
    })


def remove_from_cart(request, cart_key):
    cart = request.session.get("cart", {})

    if cart_key in cart:
        del cart[cart_key]

    request.session["cart"] = cart
    request.session.modified = True

    return redirect("cart")


def update_cart_quantity(request, cart_key, action):
    cart = request.session.get("cart", {})

    if cart_key in cart:
        if action == "increase":
            cart[cart_key]["quantity"] += 1

        elif action == "decrease":
            cart[cart_key]["quantity"] -= 1

            if cart[cart_key]["quantity"] <= 0:
                del cart[cart_key]

    request.session["cart"] = cart
    request.session.modified = True

    return redirect("cart")


def terms(request):
    return render(request, "store/terms.html")


def refund(request):
    return render(request, "store/refund.html")


def contact(request):
    return render(request, "store/contact.html")


def privacy(request):
    return render(request, "store/privacy.html")


def checkout_view(request):
    cart = request.session.get("cart", {})
    cart_items = []
    total = Decimal("0.00")

    if not cart:
        return redirect("cart")

    for cart_key, item_data in cart.items():
        product = get_object_or_404(Product, id=item_data["product_id"])
        quantity = int(item_data["quantity"])
        size = item_data.get("size")

        item_total = product.price * quantity
        total += item_total

        cart_items.append({
            "cart_key": cart_key,
            "product": product,
            "size": size,
            "quantity": quantity,
            "item_total": item_total,
        })

    if request.method == "POST":
        form = CheckoutForm(request.POST)

        if form.is_valid():
            payment_method = request.POST.get("payment_method")
            stripe_account = request.POST.get("stripe_account", "a")

            if stripe_account == "b":
                selected_stripe_key = settings.STRIPE_SECRET_KEY_B
            else:
                selected_stripe_key = settings.STRIPE_SECRET_KEY_A

            order = Order.objects.create(
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                address=form.cleaned_data["address"],
                city=form.cleaned_data["city"],
                postcode=form.cleaned_data["postcode"],
                country=form.cleaned_data["country"],
                total_price=total,
            )

            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item["product"],
                    size=item["size"],
                    quantity=item["quantity"],
                    price=item["product"].price,
                )

            if payment_method == "square":
                try:
                    square_url = create_square_payment_link(request, order)
                    return redirect(square_url)

                except Exception as e:
                    order.delete()

                    return render(request, "store/checkout.html", {
                        "form": form,
                        "cart_items": cart_items,
                        "total": total,
                        "error": f"Square checkout error: {str(e)}",
                    })

            line_items = []

            for item in cart_items:
                product_name = item["product"].name

                if item["size"]:
                    product_name = f"{product_name} - Size {item['size']}"

                line_items.append({
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {
                            "name": product_name,
                        },
                        "unit_amount": int(item["product"].price * 100),
                    },
                    "quantity": item["quantity"],
                })

            try:
                checkout_session = stripe.checkout.Session.create(
                    api_key=selected_stripe_key,
                    mode="payment",
                    line_items=line_items,
                    success_url=request.build_absolute_uri("/checkout/success/") + "?session_id={CHECKOUT_SESSION_ID}",
                    cancel_url=request.build_absolute_uri("/checkout/"),
                    customer_email=form.cleaned_data["email"],
                    metadata={
                        "order_id": str(order.id),
                        "customer_name": form.cleaned_data["full_name"],
                    },
                )

                order.stripe_session_id = checkout_session.id
                order.save()

                return redirect(checkout_session.url, code=303)

            except stripe.error.StripeError as e:
                order.delete()

                return render(request, "store/checkout.html", {
                    "form": form,
                    "cart_items": cart_items,
                    "total": total,
                    "error": str(e),
                })

    else:
        form = CheckoutForm()

    return render(request, "store/checkout.html", {
        "form": form,
        "cart_items": cart_items,
        "total": total,
    })


def checkout_success(request):
    request.session["cart"] = {}
    request.session.modified = True

    return render(request, "store/checkout_success.html")


@csrf_exempt
def stripe_webhook(request):
    print("Webhook endpoint hit", flush=True)

    try:
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        event = None
        stripe_account = None

        for account_name, secret in [
            ("A", settings.STRIPE_WEBHOOK_SECRET_A),
            ("B", settings.STRIPE_WEBHOOK_SECRET_B),
        ]:
            if not secret:
                print(f"Missing webhook secret for account {account_name}", flush=True)
                continue

            try:
                event = stripe.Webhook.construct_event(payload, sig_header, secret)
                stripe_account = account_name
                break
            except stripe.error.SignatureVerificationError:
                continue

        if event is None:
            print("Invalid signature for both Stripe accounts", flush=True)
            return HttpResponse(status=400)

        print("Webhook received from Stripe account:", stripe_account, flush=True)
        print("Event verified:", event["type"], flush=True)

        if event["type"] == "checkout.session.completed":
            print("Checkout session completed", flush=True)

    session = event["data"]["object"].to_dict()

    order_id = session.get("metadata", {}).get("order_id")

    print("Order ID from metadata:", order_id, flush=True)

    if not order_id:
        print("No order_id found in metadata", flush=True)
        return HttpResponse(status=200)

    try:
        order = Order.objects.get(id=order_id)
        print("Order found:", order.order_number, flush=True)

        if not order.is_paid:
            order.is_paid = True
            order.save()
            print("Order marked as paid", flush=True)
        else:
            print("Order already paid", flush=True)

        try:
            send_order_confirmation_email(order, session)
            print("Email function completed", flush=True)
        except Exception:
            import traceback
            print("Email sending failed:", flush=True)
            traceback.print_exc()

    except Order.DoesNotExist:
        print("Order not found:", order_id, flush=True)

        return HttpResponse(status=200)

    except ValueError as e:
        print("Invalid payload:", str(e), flush=True)
        return HttpResponse(status=400)

    except Exception:
        import traceback
        print("Webhook crashed:", flush=True)
        traceback.print_exc()
        return HttpResponse(status=200)


def create_square_payment_link(request, order):
    base_url = "https://connect.squareup.com"
    url = f"{base_url}/v2/online-checkout/payment-links"

    headers = {
        "Authorization": f"Bearer {settings.SQUARE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Square-Version": "2026-05-21",
    }

    line_items = []

    for item in order.items.all():
        name = item.product.name

        if item.size:
            name = f"{name} - Size {item.size}"

        line_items.append({
            "name": name,
            "quantity": str(item.quantity),
            "base_price_money": {
                "amount": int(item.price * 100),
                "currency": "GBP",
            },
        })

    data = {
        "idempotency_key": str(uuid.uuid4()),
        "order": {
            "location_id": settings.SQUARE_LOCATION_ID,
            "reference_id": str(order.id),
            "line_items": line_items,
        },
        "checkout_options": {
            "redirect_url": request.build_absolute_uri(
                f"/square/success/?order_id={order.id}"
            )
        },
        "pre_populated_data": {
            "buyer_email": order.email,
        },
        "payment_note": f"Order ID: {order.id}",
    }

    response = requests.post(url, headers=headers, json=data)
    response_data = response.json()

    if response.status_code not in [200, 201]:
        raise Exception(response_data)

    return response_data["payment_link"]["url"]


def square_success(request):
    order_id = request.GET.get("order_id")

    if order_id:
        try:
            order = Order.objects.get(id=order_id)
            order.is_paid = True
            order.save()

            try:
                send_order_confirmation_email(order, {})
            except Exception as e:
                print("Square email failed:", str(e))

        except Order.DoesNotExist:
            pass

    request.session["cart"] = {}
    request.session.modified = True

    return render(request, "store/checkout_success.html")


def tracking(request):
    return render(request, "store/tracking.html")


def tracking_result(request):
    order_number = request.GET.get("order", "").strip().upper()

    order_id = (
        order_number
        .replace("ONV", "")
        .replace("ONVEL", "")
        .replace("#", "")
        .strip()
    )

    try:
        order = Order.objects.get(id=int(order_id))
    except:
        return redirect("tracking")

    return render(request, "store/tracking_result.html", {
        "order": order
    })


def tracking_result_with_id(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    return render(request, "store/tracking_result.html", {
        "order": order
    })


def download_invoice(request, order_id):
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    order = get_object_or_404(Order, id=order_id)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 35 * mm

    # Title
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(25 * mm, y, "ONVEL INVOICE")

    y -= 18 * mm

    # Invoice details
    pdf.setFont("Helvetica", 11)
    pdf.drawString(25 * mm, y, f"Invoice Number: {order.order_number.lower()}")
    y -= 8 * mm
    pdf.drawString(25 * mm, y, f"Order Date: {order.created_at.strftime('%d %B %Y')}")
    y -= 8 * mm
    pdf.drawString(25 * mm, y, f"Order Status: {'Paid' if order.is_paid else 'Awaiting Payment'}")

    y -= 18 * mm

    # Customer details
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(25 * mm, y, "Customer Details")

    y -= 9 * mm

    pdf.setFont("Helvetica", 11)
    pdf.drawString(25 * mm, y, order.full_name)
    y -= 7 * mm
    pdf.drawString(25 * mm, y, order.email)
    y -= 7 * mm
    pdf.drawString(25 * mm, y, order.address)
    y -= 7 * mm
    pdf.drawString(25 * mm, y, f"{order.city}, {order.postcode}")
    y -= 7 * mm
    pdf.drawString(25 * mm, y, order.country)

    y -= 18 * mm

    # Order items
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(25 * mm, y, "Order Items")

    y -= 10 * mm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(25 * mm, y, "Product")
    pdf.drawString(105 * mm, y, "Size")
    pdf.drawString(130 * mm, y, "Qty")
    pdf.drawString(155 * mm, y, "Price")

    y -= 5 * mm
    pdf.line(25 * mm, y, 185 * mm, y)
    y -= 8 * mm

    pdf.setFont("Helvetica", 10)

    for item in order.items.all():
        product_name = item.product.name[:42]
        size = item.size if item.size else "-"
        qty = str(item.quantity)
        price = f"£{item.price}"

        pdf.drawString(25 * mm, y, product_name)
        pdf.drawString(105 * mm, y, size)
        pdf.drawString(130 * mm, y, qty)
        pdf.drawString(155 * mm, y, price)

        y -= 8 * mm

    y -= 6 * mm

    # Total
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(25 * mm, y, f"Total: £{order.total_price}")

    y -= 22 * mm

    # Footer
    pdf.setFont("Helvetica", 11)
    pdf.drawString(25 * mm, y, "Thank you for shopping with ONVEL.")

    pdf.showPage()
    pdf.save()

    buffer.seek(0)

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number.lower()}.pdf"'

    return response


def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if request.method == "POST":

        if order.status in ["Shipped", "Delivered", "Cancelled"]:
            messages.error(request, "This order cannot be cancelled.")
            return redirect("tracking_result_with_id", order_id=order.id)

        order.status = "Cancelled"
        order.save()

        try:
            import resend

            resend.api_key = settings.RESEND_API_KEY

            context = {
                "order": order,
                "order_items": order.items.all(),
                "tracking_url": "https://onvel.shop/track-order/",
            }

            html_content = render_to_string(
                "store/emails/order_cancelled.html",
                context
            )

            text_content = render_to_string(
                "store/emails/order_cancelled.txt",
                context
            )

            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [order.email],
                "subject": f"Your ONVEL order {order.order_number} has been cancelled",
                "html": html_content,
                "text": text_content,
            })

            messages.success(
                request,
                "Your order has been cancelled. A confirmation email has been sent."
            )

        except Exception as e:
            print("Cancellation email failed:", str(e))
            messages.warning(
                request,
                "Your order has been cancelled, but the confirmation email could not be sent."
            )

        return redirect("tracking_result_with_id", order_id=order.id)

    return redirect("tracking")