"""Subscriptions REST endpoints."""
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.registry import services

from .serializers import CouponQuoteSerializer, StartSubscriptionSerializer
from .services import CouponService, PlanService, SubscriptionService


class PlanListAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return self.ok({"plans": PlanService.public_plans()})


class MySubscriptionAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self.ok(SubscriptionService.summary(str(request.user.id)))

    def delete(self, request):
        SubscriptionService.cancel(str(request.user.id), request.data.get("reason", ""))
        return self.ok(message="Subscription cancelled.")


class StartSubscriptionAPIView(ServiceResponseMixin, APIView):
    """Creates a payment intent; access is granted only on PAYMENT_SUCCEEDED."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = StartSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = PlanService.get(data["plan_code"])
        amount = float(plan.price)
        if data.get("coupon_code"):
            quote = CouponService.quote(
                data["coupon_code"], str(request.user.id), plan.code
            )
            amount = quote["new_amount"]

        if amount <= 0:
            result = services.subscriptions.start_subscription(
                str(request.user.id), plan.code,
                coupon_code=data.get("coupon_code", ""), amount_paid=0,
            )
            return self.ok(result, message="Plan activated.")

        intent = services.payments.create_payment(
            user_id=str(request.user.id), amount=amount, currency=plan.currency,
            provider=data["provider"], purpose="subscription",
            metadata={"plan_code": plan.code, "coupon_code": data.get("coupon_code", "")},
            phone=data.get("phone", ""),
        )
        return self.ok(intent, message="Complete the payment to activate your plan.")


class EntitlementAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "entitlements": services.subscriptions.get_entitlements(user_id),
            "limits": services.subscriptions.get_quota_limits(user_id),
            "is_premium": services.subscriptions.is_premium(user_id),
        })


class CouponQuoteAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CouponQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = CouponService.quote(
            serializer.validated_data["code"], str(request.user.id),
            serializer.validated_data["plan_code"],
        )
        return self.ok(quote)


class BoostAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone

        remaining = SubscriptionService.consume_boost(str(request.user.id))
        services.profiles.apply_boost(
            str(request.user.id), timezone.now() + timezone.timedelta(minutes=30)
        )
        return self.ok({"remaining": remaining}, message="Boost active for 30 minutes.")
