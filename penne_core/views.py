from functools import wraps
from django.shortcuts import (
        render,
        get_object_or_404,
)
from django.utils.decorators import available_attrs

import frontdesk


def with_deposit(func):

    @wraps(func, assigned=available_attrs(func))
    def wrapper(request, deposit_id, *args, **kwargs):

        deposits = frontdesk.models.Deposit.objects.order_by('-created')[:10]
        if deposit_id:
            detailed_deposit = get_object_or_404(
                frontdesk.models.Deposit, pk=deposit_id)
        else:
            detailed_deposit = frontdesk.models.Deposit.objects.order_by(
                    '-created').first()

        context = {'deposits': deposits, 'detailed_deposit': detailed_deposit}

        kwargs['context'] = context

        return func(request, deposit_id, *args, **kwargs)

    return wrapper


def index(request, context=None):

    deposits = frontdesk.models.Deposit.objects.order_by('-created')[:10]

    context = {'deposits': deposits}

    return render(request, 'penne_core/index.html', context)


@with_deposit
def package_report(request, deposit_id, context=None):

    return render(request, 'penne_core/package_report.html', context)

@with_deposit
def package_report_virus(request, deposit_id, context=None):

    return render(request, 'penne_core/package_report_virus.html', context)

@with_deposit
def package_report_integrity(request, deposit_id, context=None):

    return render(request, 'penne_core/package_report_integrity.html', context)

@with_deposit
def package_report_scielops(request, deposit_id, context=None):

    return render(request, 'penne_core/package_report_scielops.html', context)
