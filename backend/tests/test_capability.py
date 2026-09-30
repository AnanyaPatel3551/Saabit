from app.core.capability import capability_report

AMAZON_ROLES = {"order_id", "order_date", "amount", "status", "state", "city", "category",
                "sku", "fulfilment", "qty", "channel"}


def topics(items: list) -> dict[str, str]:
    return {item.topic: item.reason for item in items}


def test_no_cost_column_means_profit_unsupported() -> None:
    report = capability_report(AMAZON_ROLES)

    cannot = topics(report.cannot_answer)
    assert "profit and margin" in cannot
    assert "cost" in cannot["profit and margin"]


def test_no_payment_column_means_cod_share_unsupported() -> None:
    cannot = topics(capability_report(AMAZON_ROLES).cannot_answer)

    assert "payment" in cannot["COD and payment mix"]


def test_forecasting_is_never_offered() -> None:
    report = capability_report(AMAZON_ROLES)

    assert "forecasts" in topics(report.cannot_answer)
    assert all("forecast" not in item.topic for item in report.can_answer)


def test_amazon_roles_can_answer_the_core_metrics() -> None:
    can = topics(capability_report(AMAZON_ROLES).can_answer)

    for topic in ["revenue", "orders", "average order value", "units sold", "cancellation rate",
                  "breakdown by state", "breakdown by fulfilment", "trend by month"]:
        assert topic in can


def test_no_status_column_means_cancellation_unsupported() -> None:
    cannot = topics(capability_report(AMAZON_ROLES - {"status"}).cannot_answer)

    assert "status" in cannot["cancellation rate"]


def test_missing_qty_means_units_unsupported() -> None:
    cannot = topics(capability_report(AMAZON_ROLES - {"qty"}).cannot_answer)

    assert "quantity" in cannot["units sold"]


def test_every_item_has_a_reason() -> None:
    report = capability_report({"order_id", "order_date", "amount"})

    assert all(item.reason for item in report.can_answer + report.cannot_answer)
