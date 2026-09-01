import logging

from schemas import Order

from rag.text_utils import format_value

logger = logging.getLogger("eternate-ai-api")

_REFUND_FIELDS = [
    ("id", "Refund ID"),
    ("created_at", "Created at"),
    ("amount", "Amount"),
    ("currency", "Currency"),
    ("status", "Status"),
    ("note", "Note"),
    ("reason", "Reason"),
]

_REFUND_TRANSACTION_FIELDS = [
    ("id", "Transaction ID"),
    ("kind", "Kind"),
    ("status", "Status"),
    ("amount", "Amount"),
    ("currency", "Currency"),
    ("created_at", "Created at"),
]


def _format_supplied_fields(source: dict, fields: list[tuple[str, str]], indent: str) -> list[str]:
    lines = []
    for key, label in fields:
        if key in source:
            value = source[key]
            if value is None or value == "":
                continue
            lines.append(f"{indent}{label}: {value}")
    return lines


def _format_refund_entry(refund, index: int) -> str:
    if not isinstance(refund, dict):
        return f"Refund {index}:\n  Supplied value: {refund}"

    lines = [f"Refund {index}:"]
    lines += _format_supplied_fields(refund, _REFUND_FIELDS, "  ")

    transactions = refund.get("transactions")
    if isinstance(transactions, list):
        for t_index, transaction in enumerate(transactions, start=1):
            if not isinstance(transaction, dict):
                continue
            transaction_lines = _format_supplied_fields(
                transaction, _REFUND_TRANSACTION_FIELDS, "    "
            )
            if transaction_lines:
                lines.append(f"  Transaction {t_index}:")
                lines += transaction_lines

    if len(lines) == 1:
        lines.append("  No recognizable refund fields were supplied.")

    return "\n".join(lines)


def _format_refunds(refunds) -> str:
    if not refunds:
        return (
            "Refund records: NONE PROVIDED\n"
            "IMPORTANT:\n"
            "No refund records are present in the supplied data.\n"
            "This does not confirm whether a refund, reversal, void, authorization "
            "release, or other payment adjustment occurred.\n"
            "Do not infer the customer's actual payment outcome from the absence "
            "of refund records."
        )

    if not isinstance(refunds, list):
        return f"Refund records:\n{_format_refund_entry(refunds, 1)}"

    entries = [_format_refund_entry(refund, i + 1) for i, refund in enumerate(refunds)]
    return "Refund records:\n" + "\n".join(entries)


def _is_unfulfilled(fulfillment_status) -> bool:
    """Shopify returns null fulfillment_status when the order has not shipped."""
    return fulfillment_status is None or fulfillment_status == ""


def _format_fulfillment_status(fulfillment_status) -> str:
    if _is_unfulfilled(fulfillment_status):
        return (
            "Fulfillment status: UNFULFILLED\n"
            "The supplied Shopify data confirms this order has not shipped yet.\n"
            "You may state that the order has not shipped yet.\n"
            "Do not state which production stage the order is in, how far along it "
            "is, or when it will ship, unless another supplied field establishes it."
        )
    return f"Fulfillment status: {fulfillment_status}"


def _format_tracking_number(tracking_number, fulfillment_status) -> str:
    if tracking_number is not None and tracking_number != "":
        return f"Tracking number: {tracking_number}"

    if _is_unfulfilled(fulfillment_status):
        return (
            "Tracking number: NONE YET\n"
            "No tracking number exists because the order has not shipped yet.\n"
            "You may explain that tracking becomes available once the order ships.\n"
            "Do not state a shipping date or estimate when tracking will be issued."
        )

    return (
        "Tracking number: UNKNOWN\n"
        "IMPORTANT:\n"
        "The order is not marked unfulfilled, yet no tracking number is present in "
        "the supplied data.\n"
        "Do not invent a reason for the missing tracking information.\n"
        "Do not explain how or when tracking information is normally generated.\n"
        "State only that the tracking details need to be confirmed."
    )


def _format_cancelled_at(cancelled_at) -> str:
    if cancelled_at is None or cancelled_at == "":
        return (
            "Cancelled at: UNKNOWN\n"
            "IMPORTANT:\n"
            "This does not establish that the order is active, open, processing, "
            "or valid.\n"
            'Do not describe the order as "active" unless supplied data explicitly '
            "confirms that status."
        )
    return (
        f"Cancelled at: {cancelled_at}\n"
        "IMPORTANT:\n"
        "The order data shows this order was canceled.\n"
        "This does NOT automatically confirm a refund was issued, a charge was "
        "reversed, a refund amount, refund timing, or that payment has been "
        "resolved."
    )


def _format_financial_status(financial_status) -> str:
    if financial_status is None or financial_status == "":
        return "Financial status: UNKNOWN"
    return (
        f"Financial status: {financial_status}\n"
        "Financial status must not be used to infer a complete payment history "
        "unless supported by other supplied payment data."
    )


def _format_order(order: Order, index: int) -> str:
    lines = [
        f"Order {index}:",
        f"Order number: {format_value(order.order_number)}",
        _format_financial_status(order.financial_status),
        _format_fulfillment_status(order.fulfillment_status),
        f"Created at: {format_value(order.created_at)}",
        _format_cancelled_at(order.cancelled_at),
        f"Cancel reason: {format_value(order.cancel_reason)}",
        _format_refunds(order.refunds),
        _format_tracking_number(order.tracking_number, order.fulfillment_status),
    ]
    return "\n".join(lines)


def build_orders_text(request) -> str:
    order_data = request.order_data
    orders = order_data.orders if order_data else None

    if orders and order_data.found is False:
        logger.warning(
            "Inconsistent order_data for ticket_id=%s: found=False but %d order(s) "
            "supplied; using the supplied orders list.",
            request.ticket_id,
            len(orders),
        )

    if not orders:
        return (
            "No matched order data was supplied.\n\n"
            "IMPORTANT:\n"
            "Do not invent order-specific facts."
        )

    order_blocks = [_format_order(order, i + 1) for i, order in enumerate(orders)]
    return "\n\n".join(order_blocks)
