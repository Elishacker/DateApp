"""Every paid plan can see who liked them.

Policy change: "see who likes you" was a Gold-and-above feature, which left
Plus subscribers paying and still looking at a blurred list. Seeing your
admirers is now what subscribing buys — the higher tiers are differentiated by
their other entitlements. Free accounts are unchanged.
"""
from django.db import migrations

ENTITLEMENT = "see_who_likes_you"


def grant(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.exclude(code="free"):
        entitlements = list(plan.entitlements or [])
        if ENTITLEMENT not in entitlements:
            entitlements.append(ENTITLEMENT)
            plan.entitlements = entitlements
            plan.save(update_fields=["entitlements"])


def revoke(apps, schema_editor):
    """Back out to the previous Gold-and-above arrangement."""
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.filter(code="plus"):
        entitlements = [e for e in (plan.entitlements or []) if e != ENTITLEMENT]
        plan.entitlements = entitlements
        plan.save(update_fields=["entitlements"])


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(grant, revoke),
    ]
