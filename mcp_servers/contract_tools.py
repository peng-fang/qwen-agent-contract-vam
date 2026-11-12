"""Minimal MCP server exposing contract-cost tools for the local demo.

Run directly for a stdio MCP server:
    .venv\\Scripts\\python.exe mcp_servers\\contract_tools.py

Qwen-Agent starts this process automatically when the MCP config is passed to
Assistant(function_list=[...]).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("contract-tools")


@mcp.tool()
def calculate_refund(
    total_paid: float,
    used_sessions: int,
    list_price_per_session: float,
    refund_fee_rate: float = 0.0,
) -> dict:
    """Calculate a refund when used sessions are settled at the original list price.

    Args:
        total_paid: Amount the consumer actually paid, in CNY.
        used_sessions: Number of sessions already used.
        list_price_per_session: Contract "original price" per session, in CNY.
        refund_fee_rate: Handing fee rate on the remaining balance, e.g. 0.2 for 20%.
    """
    if total_paid < 0 or used_sessions < 0 or list_price_per_session < 0:
        raise ValueError("amounts and session counts must be non-negative")
    if not 0 <= refund_fee_rate <= 1:
        raise ValueError("refund_fee_rate must be between 0 and 1")

    used_value = used_sessions * list_price_per_session
    remaining = max(total_paid - used_value, 0.0)
    fee = remaining * refund_fee_rate
    refund = max(remaining - fee, 0.0)
    return {
        "total_paid": round(total_paid, 2),
        "used_sessions": used_sessions,
        "list_price_per_session": round(list_price_per_session, 2),
        "used_value_at_list_price": round(used_value, 2),
        "remaining_before_fee": round(remaining, 2),
        "refund_fee_rate": refund_fee_rate,
        "refund_fee": round(fee, 2),
        "refund_amount": round(refund, 2),
        "consumer_loss": round(total_paid - refund, 2),
        "formula": "remaining = max(total_paid - used_sessions*list_price, 0); "
                   "refund = remaining * (1 - refund_fee_rate)",
    }


@mcp.tool()
def calculate_total_cost(
    annual_fee: float,
    years: int = 1,
    locker_fee_per_year: float = 0.0,
    assessment_fee: float = 0.0,
    assessment_count: int = 0,
    reschedule_fee: float = 0.0,
    reschedule_count: int = 0,
) -> dict:
    """Calculate the total cost including recurring and per-use extra charges."""
    if annual_fee < 0 or years < 1:
        raise ValueError("annual_fee must be non-negative and years >= 1")
    if min(locker_fee_per_year, assessment_fee, reschedule_fee) < 0:
        raise ValueError("fees must be non-negative")
    if assessment_count < 0 or reschedule_count < 0:
        raise ValueError("counts must be non-negative")

    base = annual_fee * years
    locker = locker_fee_per_year * years
    assessment = assessment_fee * assessment_count
    reschedule = reschedule_fee * reschedule_count
    total = base + locker + assessment + reschedule
    return {
        "base_fee": round(base, 2),
        "locker_fee": round(locker, 2),
        "assessment_fee": round(assessment, 2),
        "reschedule_fee": round(reschedule, 2),
        "total_cost": round(total, 2),
        "formula": "total = annual_fee*years + locker*years + assessment*count + reschedule*count",
    }


@mcp.tool()
def calculate_lease_upfront(
    monthly_rent: float,
    months: int,
    deposit: float,
    payment_fee_rate: float = 0.0,
    electricity_allowance: float = 0.0,
    electricity_rate: float = 0.0,
    estimated_electricity_kwh: float = 0.0,
) -> dict:
    """Calculate lease rent, deposit, payment-channel fees and electricity overage.

    Args:
        monthly_rent: Monthly rent in the contract currency.
        months: Number of rent months charged.
        deposit: Refundable deposit, separate from rent.
        payment_fee_rate: Channel/exchange fee rate, e.g. 0.02 for 2%.
        electricity_allowance: Annual electricity amount included in rent.
        electricity_rate: Price per kWh, e.g. 2.0 HKD/kWh.
        estimated_electricity_kwh: Estimated annual electricity usage.
    """
    if monthly_rent < 0 or months < 1 or deposit < 0:
        raise ValueError("rent/deposit must be non-negative and months >= 1")
    if not 0 <= payment_fee_rate <= 0.2:
        raise ValueError("payment_fee_rate must be between 0 and 0.2")
    if min(electricity_allowance, electricity_rate, estimated_electricity_kwh) < 0:
        raise ValueError("electricity inputs must be non-negative")

    rent_total = monthly_rent * months
    subtotal = rent_total + deposit
    payment_fee = subtotal * payment_fee_rate
    electricity_cost = electricity_rate * estimated_electricity_kwh
    electricity_over_cap = max(electricity_cost - electricity_allowance, 0.0)
    upfront_total = subtotal + payment_fee
    total_with_electricity = upfront_total + electricity_over_cap
    return {
        "monthly_rent": round(monthly_rent, 2),
        "months": months,
        "rent_total": round(rent_total, 2),
        "deposit": round(deposit, 2),
        "rent_plus_deposit": round(subtotal, 2),
        "payment_fee_rate": payment_fee_rate,
        "payment_fee": round(payment_fee, 2),
        "upfront_total": round(upfront_total, 2),
        "electricity_cost": round(electricity_cost, 2),
        "electricity_allowance": round(electricity_allowance, 2),
        "electricity_over_cap": round(electricity_over_cap, 2),
        "total_with_electricity": round(total_with_electricity, 2),
        "formula": "rent_total=monthly_rent*months; "
                   "rent_plus_deposit=rent_total+deposit; "
                   "upfront=rent_plus_deposit*(1+fee_rate); "
                   "electricity_over=max(rate*kwh-allowance,0)",
    }


if __name__ == "__main__":
    mcp.run()
