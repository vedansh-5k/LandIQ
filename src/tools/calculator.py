"""
calculator.py
-------------
A mathematical calculator tool for the Finance/CFO agent.

This tool is decorated with @tool from LangChain.
The @tool decorator transforms a regular Python function
into something the AI agent can call during its reasoning.

The docstring below the function name is critical —
the AI reads it to understand WHEN and HOW to use this tool.

The Finance agent uses this via the ReAct pattern:
1. Reason: "I need to calculate ROI"
2. Act: calls calculator("(4500000 * 12) / 50000000 * 100")
3. Observe: gets back "Calculated result: 108.0"
4. Reason: "ROI is 108%, now I can write my assessment"

Why this tool exists separately:
- Any agent can import and use it
- Logic is testable independently
- Clear separation of concerns
- Professional engineering practice
"""

from langchain_core.tools import tool


@tool
def calculator(expression: str) -> str:
    """
    Evaluates a mathematical expression and returns the exact result.

    Use this tool for ANY numeric calculation including:
    - ROI: (annual_profit / investment) * 100
    - Breakeven: investment / monthly_profit
    - Annual profit: monthly_profit * 12
    - Percentages, totals, differences, ratios

    Input must be a valid mathematical expression as a string.

    Examples:
    - "(4500000 * 12) / 50000000 * 100" → ROI percentage
    - "50000000 / 450000" → breakeven in months
    - "800000 - 350000" → monthly profit
    - "(800000 - 350000) * 12" → annual profit

    Always use this tool when numbers are present in the scenario.
    Never estimate or guess mathematical results.
    """
    try:
        # Security: only allow safe mathematical operations
        # __builtins__ is set to empty dict to prevent
        # any dangerous Python code from running
        allowed_functions = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "int": int,
            "float": float,
        }

        result = eval(
            expression,
            {"__builtins__": {}},
            allowed_functions
        )

        # Format the result cleanly
        if isinstance(result, float):
            # Round to 2 decimal places for readability
            formatted = round(result, 2)
        else:
            formatted = result

        return f"Calculated result: {formatted}"

    except ZeroDivisionError:
        return "Error: Cannot divide by zero. Please check your inputs."

    except SyntaxError:
        return f"Error: Invalid mathematical expression: '{expression}'"

    except Exception as e:
        return f"Error evaluating '{expression}': {str(e)}"


@tool
def percentage_calculator(part: float, whole: float) -> str:
    """
    Calculates what percentage 'part' is of 'whole'.

    Use when you need to find percentage share or contribution.

    Examples:
    - What percentage is profit of revenue?
    - What percentage is cost of investment?

    Input: two numbers — part and whole
    Output: percentage as a string
    """
    try:
        if whole == 0:
            return "Error: Cannot calculate percentage with zero as whole"
        percentage = round((part / whole) * 100, 2)
        return f"Calculated result: {percentage}%"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def breakeven_calculator(investment: float, monthly_profit: float) -> str:
    """
    Calculates the breakeven point in months and years.

    Use when you need to know how long until the investment
    is fully recovered from profits.

    Input: investment amount and monthly profit
    Output: breakeven in months and years
    """
    try:
        if monthly_profit <= 0:
            return "Error: Monthly profit must be positive to calculate breakeven"
        months = round(investment / monthly_profit, 1)
        years = round(months / 12, 1)
        return (
            f"Calculated result: "
            f"Breakeven in {months} months ({years} years). "
            f"Investment of {investment:,.0f} recovered at "
            f"{monthly_profit:,.0f} per month."
        )
    except Exception as e:
        return f"Error: {str(e)}"