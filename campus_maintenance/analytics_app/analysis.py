"""
Complaint analysis with Pandas, NumPy and Matplotlib.

This file does not use Django models at all. It works on plain Pandas
DataFrames, so the same code analyses:
  * live complaints from the database (see views.py), and
  * historical CSV files uploaded by the administrator.

Expected DataFrame columns:
  reference_id, category, building, floor, room, priority, status,
  submitted_at, resolved_at, deadline (deadline may be missing)
"""
import base64
import io
import re

import matplotlib

matplotlib.use("Agg")  # draw charts into memory; no window is opened on the server
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

VALID_PRIORITIES = ["low", "medium", "high", "urgent"]
VALID_STATUSES = ["submitted", "assigned", "in_progress", "resolved", "reopened", "closed"]
COMPLETED_STATUSES = ["resolved", "closed"]

# Example target hours used when a CSV has no deadline column.
DEFAULT_TARGET_HOURS = {"urgent": 4, "high": 24, "medium": 72, "low": 168}

REQUIRED_CSV_COLUMNS = ["complaint_id", "category", "building", "priority", "status", "submitted_at"]
OPTIONAL_CSV_COLUMNS = ["floor", "room", "resolved_at"]

# Chart colours (blue and orange are easy to tell apart, including for
# most colour-blind readers). Text uses neutral greys.
COLOR_MAIN = "#2a78d6"
COLOR_SECOND = "#eb6834"
COLOR_TEXT = "#0b0b0b"
COLOR_MUTED = "#52514e"
COLOR_GRID = "#e4e3df"
COLOR_SURFACE = "#fcfcfb"


class CSVValidationError(Exception):
    """Raised with a friendly message when an uploaded CSV cannot be used."""


# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------
def normalize_text(value):
    """'  Main-Block ' -> 'main block'. Used to compare locations fairly."""
    if pd.isna(value):
        return ""
    text = str(value).lower().strip()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def prepare_dataframe(df):
    """
    Make sure all expected columns exist with the right types and add
    helper columns: location, location_key, resolution_hours.
    """
    df = df.copy()
    for column in ["reference_id", "category", "building", "floor", "room", "priority", "status"]:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str).str.strip()

    for column in ["submitted_at", "resolved_at", "deadline"]:
        if column not in df.columns:
            df[column] = pd.NaT
        df[column] = pd.to_datetime(df[column], errors="coerce")

    # Fill missing deadlines using the example target hours for the priority.
    target_hours = df["priority"].map(DEFAULT_TARGET_HOURS)
    calculated_deadline = df["submitted_at"] + pd.to_timedelta(target_hours, unit="h")
    df["deadline"] = df["deadline"].fillna(calculated_deadline)

    df["location"] = df["building"] + ", Floor " + df["floor"] + ", " + df["room"]
    df["location_key"] = (
        df["building"].map(normalize_text) + "|" + df["floor"].map(normalize_text) + "|" + df["room"].map(normalize_text)
    )

    duration = df["resolved_at"] - df["submitted_at"]
    df["resolution_hours"] = duration.dt.total_seconds() / 3600
    return df


def records_to_dataframe(records):
    """Turn a list of dictionaries (from the database) into a prepared DataFrame."""
    df = pd.DataFrame(list(records))
    return prepare_dataframe(df)


# ---------------------------------------------------------------------------
# Historical CSV loading and validation
# ---------------------------------------------------------------------------
def load_historical_csv(uploaded_file, max_bytes, max_rows):
    """
    Read and clean an uploaded CSV. Returns (clean_dataframe, warnings).
    Raises CSVValidationError with a helpful message if the file is unusable.
    Nothing is saved to the database.
    """
    if not uploaded_file.name.lower().endswith(".csv"):
        raise CSVValidationError("Only files ending in .csv can be uploaded.")
    if uploaded_file.size == 0:
        raise CSVValidationError("The uploaded file is empty.")
    if uploaded_file.size > max_bytes:
        raise CSVValidationError(f"The file is too large. The limit is {max_bytes // (1024 * 1024)} MB.")

    raw_bytes = uploaded_file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVValidationError("The file must be a UTF-8 text CSV. Save it as 'CSV UTF-8' from Excel.")

    try:
        # dtype=str: read every value as plain text; nothing is ever executed.
        df = pd.read_csv(io.StringIO(text), dtype=str)
    except pd.errors.EmptyDataError:
        raise CSVValidationError("The file has no header row or data.")
    except pd.errors.ParserError:
        raise CSVValidationError("The file could not be read as CSV. Check that every row has the same number of commas.")

    return clean_historical_dataframe(df, max_rows)


def clean_historical_dataframe(df, max_rows):
    """Check required columns and handle missing / invalid values."""
    warnings = []
    df.columns = [str(column).strip().lower().replace(" ", "_") for column in df.columns]

    missing_columns = [column for column in REQUIRED_CSV_COLUMNS if column not in df.columns]
    if missing_columns:
        raise CSVValidationError(
            "Missing required column(s): " + ", ".join(missing_columns)
            + ". Required columns are: " + ", ".join(REQUIRED_CSV_COLUMNS) + "."
        )
    if len(df) == 0:
        raise CSVValidationError("The file has a header row but no data rows.")
    if len(df) > max_rows:
        raise CSVValidationError(f"The file has {len(df)} rows. The limit is {max_rows} rows.")

    for column in OPTIONAL_CSV_COLUMNS:
        if column not in df.columns:
            df[column] = None
            warnings.append(f"Optional column '{column}' was not found, so it was left empty.")

    df = df.rename(columns={"complaint_id": "reference_id"})
    for column in ["reference_id", "category", "building", "floor", "room", "priority", "status"]:
        df[column] = df[column].fillna("").astype(str).str.strip()
    df["category"] = df["category"].str.lower()
    df["priority"] = df["priority"].str.lower()
    df["status"] = df["status"].str.lower().str.replace(" ", "_")

    # Dates: invalid text becomes NaT ("not a time") instead of crashing.
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce", format="mixed")
    resolved_text = df["resolved_at"].fillna("").astype(str).str.strip()
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", format="mixed")

    # Rows without the essential information cannot be analysed.
    bad_rows = (df["category"] == "") | (df["building"] == "") | df["submitted_at"].isna()
    if bad_rows.sum() > 0:
        warnings.append(
            f"{int(bad_rows.sum())} row(s) were skipped because the category, building "
            "or submitted date was missing or invalid."
        )
    df = df[~bad_rows].copy()
    resolved_text = resolved_text[~bad_rows]

    invalid_resolved = (resolved_text != "") & df["resolved_at"].isna()
    if invalid_resolved.sum() > 0:
        warnings.append(f"{int(invalid_resolved.sum())} resolved date(s) could not be read and were ignored.")

    resolved_too_early = df["resolved_at"].notna() & (df["resolved_at"] < df["submitted_at"])
    if resolved_too_early.sum() > 0:
        warnings.append(f"{int(resolved_too_early.sum())} resolved date(s) were before the submitted date and were ignored.")
        df.loc[resolved_too_early, "resolved_at"] = pd.NaT

    invalid_priority = ~df["priority"].isin(VALID_PRIORITIES)
    if invalid_priority.sum() > 0:
        warnings.append(f"{int(invalid_priority.sum())} row(s) had an unknown priority, shown as 'unknown'.")
        df.loc[invalid_priority, "priority"] = "unknown"

    invalid_status = ~df["status"].isin(VALID_STATUSES)
    if invalid_status.sum() > 0:
        warnings.append(f"{int(invalid_status.sum())} row(s) had an unknown status, shown as 'unknown'.")
        df.loc[invalid_status, "status"] = "unknown"

    if len(df) == 0:
        raise CSVValidationError("No valid rows remained after cleaning. Check the date format (YYYY-MM-DD HH:MM).")

    return prepare_dataframe(df), warnings


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def count_with_percent(series, top=None):
    """Value counts as a list of dicts: [{'name', 'count', 'percent'}]."""
    counts = series.value_counts()
    if top:
        counts = counts.head(top)
    total = len(series)
    rows = []
    for name, count in counts.items():
        rows.append({"name": name, "count": int(count), "percent": round(count * 100 / total, 1)})
    return rows


def monthly_trend(df):
    """Number of complaints submitted and resolved in each month."""
    submitted = df["submitted_at"].dt.to_period("M").value_counts()
    resolved = df["resolved_at"].dropna().dt.to_period("M").value_counts()
    trend = pd.DataFrame({"submitted": submitted, "resolved": resolved}).fillna(0).astype(int)
    trend = trend.sort_index()
    rows = []
    for period, row in trend.iterrows():
        rows.append({"month": period.strftime("%b %Y"), "submitted": int(row["submitted"]), "resolved": int(row["resolved"])})
    return rows


def resolution_time_stats(df):
    """Average, median and 90th percentile resolution time in hours (NumPy)."""
    hours = df["resolution_hours"].dropna().to_numpy()
    hours = hours[hours >= 0]
    if len(hours) == 0:
        return None
    return {
        "count": int(len(hours)),
        "average_hours": round(float(np.mean(hours)), 1),
        "median_hours": round(float(np.median(hours)), 1),
        "p90_hours": round(float(np.percentile(hours, 90)), 1),
    }


def overdue_stats(df, now):
    """Currently overdue = not finished and deadline passed. Also counts late resolutions."""
    is_completed = df["status"].isin(COMPLETED_STATUSES)
    currently_overdue = ~is_completed & (df["deadline"] < now)
    resolved_late = df["resolved_at"].notna() & (df["resolved_at"] > df["deadline"])
    total = len(df)
    overdue_count = int(currently_overdue.sum())
    return {
        "overdue_count": overdue_count,
        "overdue_percent": round(overdue_count * 100 / total, 1) if total else 0.0,
        "resolved_late_count": int(resolved_late.sum()),
        "open_count": int((~is_completed).sum()),
        "completed_count": int(is_completed.sum()),
    }


def find_recurring_patterns(df, window_days=30, min_complaints=2):
    """
    POTENTIAL recurring issues: at least `min_complaints` complaints with the
    same category and the same normalised location inside any period of
    `window_days` days. This does not prove the same fault caused them.
    """
    results = []
    window = np.timedelta64(window_days, "D")
    for (category, location_key), group in df.groupby(["category", "location_key"]):
        if len(group) < min_complaints:
            continue
        dates = np.sort(group["submitted_at"].to_numpy())
        # For each complaint, find how many complaints fall within the window that starts at it.
        window_end_positions = np.searchsorted(dates, dates + window, side="right")
        counts_in_window = window_end_positions - np.arange(len(dates))
        most_in_window = int(counts_in_window.max())
        if most_in_window >= min_complaints:
            results.append({
                "category": category,
                "location": group["location"].iloc[0],
                "total_complaints": int(len(group)),
                "most_in_window": most_in_window,
                "first_date": pd.Timestamp(dates[0]).strftime("%d %b %Y"),
                "last_date": pd.Timestamp(dates[-1]).strftime("%d %b %Y"),
            })
    results.sort(key=lambda row: (row["most_in_window"], row["total_complaints"]), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Charts (Matplotlib -> PNG -> base64 text that an <img> tag can show)
# ---------------------------------------------------------------------------
def figure_to_data_uri(figure):
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110, bbox_inches="tight", facecolor=COLOR_SURFACE)
    plt.close(figure)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded


def style_axes(axes, title, x_label, y_label):
    axes.set_title(title, color=COLOR_TEXT, fontsize=12, loc="left", pad=12)
    axes.set_xlabel(x_label, color=COLOR_MUTED)
    axes.set_ylabel(y_label, color=COLOR_MUTED)
    axes.set_facecolor(COLOR_SURFACE)
    axes.tick_params(colors=COLOR_MUTED)
    for side in ["top", "right"]:
        axes.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        axes.spines[side].set_color(COLOR_GRID)
    axes.set_axisbelow(True)


def bar_chart(rows, title, x_label):
    """Horizontal bar chart of counts (one colour, the title names the series)."""
    names = [str(row["name"]).replace("_", " ").title() for row in rows][::-1]
    counts = [row["count"] for row in rows][::-1]
    figure, axes = plt.subplots(figsize=(6.4, 0.45 * len(names) + 1.4))
    bars = axes.barh(names, counts, color=COLOR_MAIN, height=0.6)
    axes.bar_label(bars, padding=3, color=COLOR_MUTED, fontsize=9)
    style_axes(axes, title, x_label, "")
    axes.grid(axis="x", color=COLOR_GRID, linewidth=0.8)
    axes.xaxis.get_major_locator().set_params(integer=True)
    return figure_to_data_uri(figure)


def monthly_chart(trend_rows):
    months = [row["month"] for row in trend_rows]
    submitted = [row["submitted"] for row in trend_rows]
    resolved = [row["resolved"] for row in trend_rows]
    figure, axes = plt.subplots(figsize=(6.4, 3.4))
    axes.plot(months, submitted, color=COLOR_MAIN, linewidth=2, marker="o", markersize=5, label="Submitted")
    axes.plot(months, resolved, color=COLOR_SECOND, linewidth=2, marker="s", markersize=5, label="Resolved")
    style_axes(axes, "Monthly complaint trend", "Month", "Number of complaints")
    axes.set_ylim(bottom=0)
    axes.grid(axis="y", color=COLOR_GRID, linewidth=0.8)
    axes.yaxis.get_major_locator().set_params(integer=True)
    axes.legend(frameon=False, labelcolor=COLOR_TEXT)
    plt.setp(axes.get_xticklabels(), rotation=30, ha="right")
    return figure_to_data_uri(figure)


def priority_overdue_chart(df, now):
    """Stacked bars: for each priority, how many open complaints are on time vs overdue."""
    open_complaints = df[~df["status"].isin(COMPLETED_STATUSES)]
    priorities = [p for p in VALID_PRIORITIES if p in set(open_complaints["priority"])]
    if not priorities:
        return None
    overdue_counts = []
    on_time_counts = []
    for priority in priorities:
        rows = open_complaints[open_complaints["priority"] == priority]
        overdue = int((rows["deadline"] < now).sum())
        overdue_counts.append(overdue)
        on_time_counts.append(len(rows) - overdue)
    labels = [p.title() for p in priorities]
    figure, axes = plt.subplots(figsize=(6.4, 3.4))
    axes.bar(labels, on_time_counts, color=COLOR_MAIN, width=0.55, label="Within deadline", edgecolor=COLOR_SURFACE, linewidth=2)
    axes.bar(labels, overdue_counts, bottom=on_time_counts, color=COLOR_SECOND, width=0.55, label="Overdue", edgecolor=COLOR_SURFACE, linewidth=2)
    style_axes(axes, "Open complaints by priority", "Priority", "Open complaints")
    axes.grid(axis="y", color=COLOR_GRID, linewidth=0.8)
    axes.yaxis.get_major_locator().set_params(integer=True)
    axes.legend(frameon=False, labelcolor=COLOR_TEXT)
    return figure_to_data_uri(figure)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------
def build_report(df, now, window_days=30, min_complaints=2, include_charts=True):
    """Return a dictionary with every statistic (and chart) shown on the analytics page."""
    report = {
        "total": len(df),
        "by_category": [],
        "by_building": [],
        "top_locations": [],
        "monthly": [],
        "resolution": None,
        "overdue": None,
        "recurring": [],
        "charts": {},
        "window_days": window_days,
        "min_complaints": min_complaints,
    }
    if len(df) == 0:
        return report

    report["by_category"] = count_with_percent(df["category"])
    report["by_building"] = count_with_percent(df["building"], top=10)
    report["top_locations"] = count_with_percent(df["location"], top=5)
    report["monthly"] = monthly_trend(df)
    report["resolution"] = resolution_time_stats(df)
    report["overdue"] = overdue_stats(df, now)
    report["recurring"] = find_recurring_patterns(df, window_days, min_complaints)

    if include_charts:
        report["charts"]["category"] = bar_chart(report["by_category"], "Complaints by category", "Number of complaints")
        report["charts"]["building"] = bar_chart(report["by_building"], "Complaints by building (top 10)", "Number of complaints")
        report["charts"]["monthly"] = monthly_chart(report["monthly"])
        priority_chart = priority_overdue_chart(df, now)
        if priority_chart:
            report["charts"]["priority"] = priority_chart
    return report
