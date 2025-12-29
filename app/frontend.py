import solara
import httpx
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import threading
import time
from datetime import datetime, timedelta, timezone

# Define reactive variables for the application state
coins = solara.reactive([])
error_message = solara.reactive("")
selected_exchange = solara.reactive("coinbase")
selected_symbol = solara.reactive("BTC-USD")
history_window = solara.reactive("1h")
chart_type = solara.reactive("Candles")
candles_timeframe = solara.reactive("1m")

API_BASE_URL = "http://localhost:8000"

NEON_NIGHT_CSS = """
:root {
  color-scheme: dark;
  --bg0: #05010d;
  --bg1: #070b18;
  --surface: rgba(10, 12, 28, 0.72);
  --surface2: rgba(6, 8, 18, 0.75);
  --neon-cyan: #00f5ff;
  --neon-magenta: #ff2bd6;
  --neon-green: #39ff14;
  --text: #e6f6ff;
  --muted: rgba(230, 246, 255, 0.75);
  --border: rgba(0, 245, 255, 0.18);
  --border2: rgba(255, 43, 214, 0.18);
  --glow-cyan: rgba(0, 245, 255, 0.55);
  --btn-bg: rgba(0, 0, 0, 0.20);
  --btn-border: rgba(0, 245, 255, 0.28);
  --btn-hover: rgba(0, 245, 255, 0.12);
  --toggle-active-bg: rgba(0, 245, 255, 0.18);
  --shadow: 0 0 0 1px rgba(255, 43, 214, 0.08), 0 0 28px rgba(0, 245, 255, 0.08);
}

body {
  background:
    radial-gradient(circle at 15% 10%, rgba(255, 43, 214, 0.18), transparent 40%),
    radial-gradient(circle at 80% 20%, rgba(0, 245, 255, 0.14), transparent 45%),
    radial-gradient(circle at 30% 90%, rgba(57, 255, 20, 0.10), transparent 40%),
    linear-gradient(180deg, var(--bg0), #000);
  color: var(--text);
}

.v-application {
  background: transparent !important;
  color: var(--text) !important;
}

.v-app-bar {
  background: linear-gradient(90deg, rgba(255, 43, 214, 0.20), rgba(0, 245, 255, 0.14)) !important;
  border-bottom: 1px solid var(--border) !important;
  backdrop-filter: blur(8px);
}

.v-navigation-drawer {
  background: var(--surface2) !important;
  border-right: 1px solid var(--border2) !important;
  backdrop-filter: blur(10px);
}

.v-card {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow) !important;
  backdrop-filter: blur(10px);
}

.v-toolbar__title {
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: var(--neon-cyan) !important;
  text-shadow: 0 0 14px var(--glow-cyan);
}

.v-card__title {
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--neon-cyan) !important;
  text-shadow: 0 0 12px var(--glow-cyan);
}

.v-label {
  color: var(--muted) !important;
}

.v-btn {
  border-radius: 12px !important;
  text-transform: none !important;
  letter-spacing: 0.02em;
  background: var(--btn-bg) !important;
  border: 1px solid var(--btn-border) !important;
}

.v-btn:hover {
  box-shadow: 0 0 18px var(--btn-hover) !important;
}

.v-btn-toggle {
  border-radius: 14px !important;
  overflow: hidden;
  border: 1px solid var(--border) !important;
  background: rgba(0, 0, 0, 0.10) !important;
}

.v-btn-toggle .v-btn {
  border: none !important;
}

.v-btn-toggle .v-btn.v-btn--active {
  background: var(--toggle-active-bg) !important;
  box-shadow: 0 0 18px var(--btn-hover) !important;
}

.v-input__slot {
  border-radius: 12px !important;
  border: 1px solid rgba(0, 245, 255, 0.14) !important;
}

.v-data-table,
table.dataframe {
  background: transparent !important;
  color: var(--text) !important;
}

.v-data-table thead th,
table.dataframe thead th {
  color: var(--muted) !important;
}
"""

NEON_DAY_CSS = """
:root {
  color-scheme: light;
  --bg0: #f7f9ff;
  --bg1: #ffffff;
  --surface: rgba(255, 255, 255, 0.78);
  --surface2: rgba(255, 255, 255, 0.72);
  --neon-cyan: #00bcd4;
  --neon-magenta: #ff2bd6;
  --neon-green: #00c853;
  --text: #081221;
  --muted: rgba(8, 18, 33, 0.68);
  --border: rgba(0, 188, 212, 0.22);
  --border2: rgba(255, 43, 214, 0.12);
  --glow-cyan: rgba(0, 188, 212, 0.30);
  --btn-bg: rgba(255, 255, 255, 0.74);
  --btn-border: rgba(0, 188, 212, 0.30);
  --btn-hover: rgba(255, 43, 214, 0.10);
  --toggle-active-bg: rgba(0, 188, 212, 0.16);
  --shadow: 0 0 0 1px rgba(255, 43, 214, 0.05), 0 0 26px rgba(0, 188, 212, 0.12);
}

body {
  background:
    radial-gradient(circle at 15% 10%, rgba(255, 43, 214, 0.10), transparent 42%),
    radial-gradient(circle at 80% 20%, rgba(0, 188, 212, 0.10), transparent 48%),
    radial-gradient(circle at 30% 90%, rgba(0, 200, 83, 0.08), transparent 44%),
    linear-gradient(180deg, var(--bg0), var(--bg1));
  color: var(--text);
}

.v-application {
  background: transparent !important;
  color: var(--text) !important;
}

.v-app-bar {
  background: linear-gradient(90deg, rgba(255, 43, 214, 0.16), rgba(0, 188, 212, 0.14)) !important;
  border-bottom: 1px solid var(--border) !important;
  backdrop-filter: blur(8px);
}

.v-navigation-drawer {
  background: var(--surface2) !important;
  border-right: 1px solid var(--border2) !important;
  backdrop-filter: blur(10px);
}

.v-card {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow) !important;
  backdrop-filter: blur(10px);
}

.v-toolbar__title {
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: var(--neon-cyan) !important;
  text-shadow: 0 0 14px var(--glow-cyan);
}

.v-card__title {
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--neon-cyan) !important;
  text-shadow: 0 0 12px var(--glow-cyan);
}

.v-label {
  color: var(--muted) !important;
}

.v-btn {
  border-radius: 12px !important;
  text-transform: none !important;
  letter-spacing: 0.02em;
  background: var(--btn-bg) !important;
  border: 1px solid var(--btn-border) !important;
}

.v-btn:hover {
  box-shadow: 0 0 18px var(--btn-hover) !important;
}

.v-btn-toggle {
  border-radius: 14px !important;
  overflow: hidden;
  border: 1px solid var(--border) !important;
  background: rgba(255, 255, 255, 0.55) !important;
}

.v-btn-toggle .v-btn {
  border: none !important;
}

.v-btn-toggle .v-btn.v-btn--active {
  background: var(--toggle-active-bg) !important;
  box-shadow: 0 0 18px var(--btn-hover) !important;
}

.v-input__slot {
  border-radius: 12px !important;
  border: 1px solid rgba(0, 188, 212, 0.18) !important;
}

.v-data-table,
table.dataframe {
  background: transparent !important;
  color: var(--text) !important;
}

.v-data-table thead th,
table.dataframe thead th {
  color: var(--muted) !important;
}
"""


def _parse_duration(value: str) -> timedelta:
    raw = (value or "").strip().lower()
    try:
        if raw.endswith("m"):
            return timedelta(minutes=int(raw[:-1]))
        if raw.endswith("h"):
            return timedelta(hours=int(raw[:-1]))
        if raw.endswith("d"):
            return timedelta(days=int(raw[:-1]))
    except Exception:
        pass
    return timedelta(hours=1)


def _parse_plotly_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Plotly may send ms since epoch; detect by magnitude.
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.fromisoformat(s.replace(" ", "T"))
            except ValueError:
                return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None

def fetch_coins():
    """
    Fetches the list of coins from the backend API.
    """
    try:
        response = httpx.get(f"{API_BASE_URL}/api/coins")
        response.raise_for_status()  # Raise an exception for bad status codes
        coins.value = response.json()
        error_message.value = ""
    except httpx.RequestError as e:
        error_message.value = f"Error fetching data: {e}"
        print(error_message.value)
    except Exception as e:
        error_message.value = f"An unexpected error occurred: {e}"
        print(error_message.value)


@solara.component
def LivePriceChart(exchange: str, symbol: str, is_night: bool, history: str):
    """
    Live chart: loads historical data for the active view range and appends live ticks.

    - Zoom/pan triggers a server-side range fetch (downsampled) so zooming out loads more data.
    - Double-click reset (autorange) returns to live-follow mode.
    """

    override_range, set_override_range = solara.use_state(None)  # (start_dt, end_dt) in UTC, or None to follow live

    last_relayout_at = solara.use_ref(0.0)

    def on_relayout(data):
        # Throttle to avoid spamming requests during drag/zoom.
        now = time.time()
        if now - last_relayout_at.current < 0.35:
            return
        last_relayout_at.current = now

        if not isinstance(data, dict):
            return

        # Plotly double-click reset sets autorange.
        if data.get("xaxis.autorange") is True:
            set_override_range(None)
            return

        start_raw = data.get("xaxis.range[0]")
        end_raw = data.get("xaxis.range[1]")
        if start_raw is None or end_raw is None:
            # Some Plotly versions send a list under "xaxis.range".
            rng = data.get("xaxis.range")
            if isinstance(rng, (list, tuple)) and len(rng) >= 2:
                start_raw, end_raw = rng[0], rng[1]

        start_dt = _parse_plotly_datetime(start_raw)
        end_dt = _parse_plotly_datetime(end_raw)
        if start_dt is None or end_dt is None or start_dt >= end_dt:
            return
        set_override_range((start_dt, end_dt))

    def poll(stop_event: threading.Event):
        series: list[tuple[datetime, float]] = []
        bucket_seconds: int | None = None

        def fetch_series(start_dt: datetime, end_dt: datetime, max_points: int = 2000):
            nonlocal bucket_seconds
            resp = httpx.get(
                f"{API_BASE_URL}/api/market/series/{exchange}/{symbol}",
                params={
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "max_points": max_points,
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            payload = resp.json()
            bucket_seconds = payload.get("bucket_seconds")
            pts = payload.get("points", []) or []
            loaded: list[tuple[datetime, float]] = []
            for p in pts:
                ts_s = p.get("timestamp")
                price_s = p.get("price")
                if ts_s is None or price_s is None:
                    continue
                loaded.append((_parse_plotly_datetime(ts_s), float(price_s)))
            loaded = [(t, v) for (t, v) in loaded if t is not None]
            return loaded

        follow_live = override_range is None
        if follow_live:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - _parse_duration(history)
        else:
            start_dt, end_dt = override_range

        try:
            series = fetch_series(start_dt=start_dt, end_dt=end_dt, max_points=2000)
        except Exception:
            series = []

        # In explore mode we only fetch once (no background polling).
        if not follow_live:
            yield {"series": series, "bucket_seconds": bucket_seconds, "mode": "explore"}
            return

        while not stop_event.is_set():
            try:
                resp = httpx.get(f"{API_BASE_URL}/api/market/latest/{exchange}/{symbol}", timeout=2.0)
                if resp.status_code == 200:
                    tick = resp.json()
                    ts = datetime.fromtimestamp(float(tick["ts"]), tz=timezone.utc)
                    price = float(tick["price"])
                    if not series or ts > series[-1][0]:
                        series.append((ts, price))

                    # Keep a stable time window when following live.
                    cutoff = datetime.now(timezone.utc) - _parse_duration(history)
                    series = [(t, p) for (t, p) in series if t >= cutoff][-5000:]
            except Exception:
                pass
            yield {"series": list(series), "bucket_seconds": bucket_seconds, "mode": "live"}
            time.sleep(0.5)

    result = solara.use_thread(poll, dependencies=[exchange, symbol, history, override_range])

    def fetch_coverage():
        try:
            resp = httpx.get(f"{API_BASE_URL}/api/market/coverage/{exchange}/{symbol}", timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            return None
        return None

    coverage = solara.use_thread(fetch_coverage, dependencies=[exchange, symbol])

    payload = result.value or {}
    series = payload.get("series") or []
    bucket_seconds = payload.get("bucket_seconds")
    mode = payload.get("mode", "live")

    if not series:
        solara.Info(f"Waiting for live ticks: {exchange}:{symbol}")
        return

    with solara.Row(justify="space-between"):
        if mode == "live":
            solara.Text(f"{exchange}:{symbol} - Live")
        else:
            solara.Text(f"{exchange}:{symbol} - Explore")
        if bucket_seconds:
            solara.Text(f"Bucket: {bucket_seconds}s", style="color: var(--muted);")
        if override_range is not None:
            solara.Button("Back to Live", on_click=lambda: set_override_range(None), icon_name="mdi-broadcast")

    cov = coverage.value or {}
    if cov.get("trades"):
        first_ts = cov.get("first_timestamp")
        last_ts = cov.get("last_timestamp")
        solara.Text(
            f"Stored ticks: {cov.get('trades')} - {first_ts or '?'} -> {last_ts or '?'}",
            style="color: var(--muted);",
        )

    x = [t for t, _ in series]
    y = [p for _, p in series]

    neon_green = "#39ff14"
    neon_red = "#ff1744"
    neon_blue = "#00f5ff"
    neon_purple = "#ff2bd6"
    line_color = neon_blue
    if len(y) >= 2:
        line_color = neon_green if (y[-1] - y[0]) >= 0 else neon_red
    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=x,
            y=y,
            mode="lines",
            name=f"{exchange}:{symbol}",
            line=dict(color=line_color, width=2),
        )
    )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=30, b=10),
        title=f"Live price - {exchange}:{symbol}",
        xaxis_title="Time (UTC)",
        yaxis_title="Price",
        template="plotly_dark",
        font=dict(color="#e6f6ff"),
        title_font=dict(color=neon_blue),
        uirevision=f"{exchange}:{symbol}",
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
    )
    fig.update_xaxes(
        gridcolor="rgba(0, 245, 255, 0.10)",
        zerolinecolor="rgba(255, 43, 214, 0.15)",
        tickfont=dict(color="#e6f6ff"),
        title_font=dict(color=neon_purple),
    )
    fig.update_yaxes(
        gridcolor="rgba(0, 245, 255, 0.10)",
        zerolinecolor="rgba(255, 43, 214, 0.15)",
        tickfont=dict(color="#e6f6ff"),
        title_font=dict(color=neon_purple),
    )
    solara.FigurePlotly(fig, on_relayout=on_relayout)


@solara.component
def CandlestickVolumeChart(exchange: str, symbol: str, timeframe: str, history: str):
    """
    Candlestick + volume chart derived from persisted tick trades.

    - Timeframe controls candle resolution.
    - Zoom/pan loads more history; double-click resets to live-follow mode.
    """

    override_range, set_override_range = solara.use_state(None)  # (start_dt, end_dt) in UTC, or None to follow live
    last_relayout_at = solara.use_ref(0.0)

    def on_relayout(data):
        now = time.time()
        if now - last_relayout_at.current < 0.35:
            return
        last_relayout_at.current = now

        if not isinstance(data, dict):
            return

        if data.get("xaxis.autorange") is True or data.get("xaxis2.autorange") is True:
            set_override_range(None)
            return

        start_raw = data.get("xaxis.range[0]") or data.get("xaxis2.range[0]")
        end_raw = data.get("xaxis.range[1]") or data.get("xaxis2.range[1]")
        if start_raw is None or end_raw is None:
            rng = data.get("xaxis.range") or data.get("xaxis2.range")
            if isinstance(rng, (list, tuple)) and len(rng) >= 2:
                start_raw, end_raw = rng[0], rng[1]

        start_dt = _parse_plotly_datetime(start_raw)
        end_dt = _parse_plotly_datetime(end_raw)
        if start_dt is None or end_dt is None or start_dt >= end_dt:
            return
        set_override_range((start_dt, end_dt))

    def poll(stop_event: threading.Event):
        follow_live = override_range is None
        while not stop_event.is_set():
            if follow_live:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - _parse_duration(history)
            else:
                start_dt, end_dt = override_range
            try:
                resp = httpx.get(
                    f"{API_BASE_URL}/api/market/candles/{exchange}/{symbol}",
                    params={
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                        "timeframe": timeframe,
                        "max_points": 2000,
                    },
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    yield payload
                    if not follow_live:
                        return
            except Exception:
                pass
            time.sleep(1.0)

    candles_result = solara.use_thread(poll, dependencies=[exchange, symbol, timeframe, history, override_range])

    def fetch_coverage():
        try:
            resp = httpx.get(f"{API_BASE_URL}/api/market/coverage/{exchange}/{symbol}", timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            return None
        return None

    coverage = solara.use_thread(fetch_coverage, dependencies=[exchange, symbol])

    payload = candles_result.value or {}
    candles = payload.get("candles") or []
    bucket_seconds = payload.get("bucket_seconds")

    if not candles:
        solara.Info(f"Waiting for candles: {exchange}:{symbol}")
        return

    follow_live = override_range is None
    with solara.Row(justify="space-between"):
        solara.Text(f"{exchange}:{symbol} - {'Live' if follow_live else 'Explore'}")
        if timeframe:
            solara.Text(f"TF: {timeframe}", style="color: var(--muted);")
        if bucket_seconds:
            solara.Text(f"Bucket: {bucket_seconds}s", style="color: var(--muted);")
        if not follow_live:
            solara.Button("Back to Live", on_click=lambda: set_override_range(None), icon_name="mdi-broadcast")

    cov = coverage.value or {}
    if cov.get("trades"):
        first_ts = cov.get("first_timestamp")
        last_ts = cov.get("last_timestamp")
        solara.Text(
            f"Stored ticks: {cov.get('trades')} - {first_ts or '?'} -> {last_ts or '?'}",
            style="color: var(--muted);",
        )

    x: list[datetime] = []
    open_: list[float] = []
    high: list[float] = []
    low: list[float] = []
    close: list[float] = []
    volume: list[float] = []

    for c in candles:
        ts = _parse_plotly_datetime(c.get("timestamp"))
        if ts is None:
            continue
        x.append(ts)
        open_.append(float(c.get("open") or 0.0))
        high.append(float(c.get("high") or 0.0))
        low.append(float(c.get("low") or 0.0))
        close.append(float(c.get("close") or 0.0))
        volume.append(float(c.get("volume") or 0.0))

    if not x:
        solara.Info(f"Waiting for candles: {exchange}:{symbol}")
        return

    neon_green = "#39ff14"
    neon_red = "#ff1744"
    neon_blue = "#00f5ff"
    neon_purple = "#ff2bd6"
    volume_colors = [
        "rgba(57, 255, 20, 0.35)" if c >= o else "rgba(255, 23, 68, 0.35)"
        for o, c in zip(open_, close)
    ]

    close_s = pd.Series(close)
    ema_20 = close_s.ewm(span=20, adjust=False).mean().tolist()
    ema_50 = close_s.ewm(span=50, adjust=False).mean().tolist()

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
    )
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            name=f"{exchange}:{symbol}",
            increasing=dict(line=dict(color=neon_green, width=1), fillcolor="rgba(57, 255, 20, 0.18)"),
            decreasing=dict(line=dict(color=neon_red, width=1), fillcolor="rgba(255, 23, 68, 0.18)"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=ema_20,
            mode="lines",
            name="EMA20",
            line=dict(color=neon_blue, width=1),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=ema_50,
            mode="lines",
            name="EMA50",
            line=dict(color=neon_purple, width=1),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=x,
            y=volume,
            name="Volume",
            marker=dict(color=volume_colors),
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=30, b=10),
        title=f"Candles - {exchange}:{symbol} ({timeframe})",
        template="plotly_dark",
        font=dict(color="#e6f6ff"),
        title_font=dict(color=neon_blue),
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
        uirevision=f"{exchange}:{symbol}:{timeframe}",
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(
        gridcolor="rgba(0, 245, 255, 0.10)",
        zerolinecolor="rgba(255, 43, 214, 0.15)",
        tickfont=dict(color="#e6f6ff"),
        title_font=dict(color=neon_purple),
        rangeslider=dict(visible=False),
    )
    fig.update_yaxes(
        gridcolor="rgba(0, 245, 255, 0.10)",
        zerolinecolor="rgba(255, 43, 214, 0.15)",
        tickfont=dict(color="#e6f6ff"),
        title_font=dict(color=neon_purple),
    )

    solara.FigurePlotly(fig, on_relayout=on_relayout)


@solara.component
def CoinDataTable():
    """
    A component to display the list of coins in a table.
    """
    if error_message.value:
        solara.Error(error_message.value)

    if not coins.value:
        return solara.Info("Click the button to fetch coin data.")

    # Convert the list of dicts to a pandas DataFrame for display
    df = pd.DataFrame(coins.value)
    
    # Select and rename columns for clarity
    display_df = df[['market_cap_rank', 'name', 'symbol', 'current_price', 'market_cap']]
    display_df = display_df.rename(columns={
        'market_cap_rank': 'Rank',
        'name': 'Name',
        'symbol': 'Symbol',
        'current_price': 'Price (USD)',
        'market_cap': 'Market Cap (USD)'
    })
    
    solara.DataFrame(display_df)


@solara.component
def Page():
    """
    The main page component for the dashboard.
    """
    theme_mode, set_theme_mode = solara.use_state("Night")
    is_night = theme_mode == "Night"
    solara.Style(NEON_NIGHT_CSS if is_night else NEON_DAY_CSS)
    solara.Title("CryptoInsight Dashboard")

    with solara.AppBar():
        with solara.AppBarTitle():
            solara.Text("CryptoInsight")
        with solara.Row(style="margin-left: auto;", justify="end", gap="8px"):
            solara.ToggleButtonsSingle(
                value=theme_mode,
                values=["Day", "Night"],
                on_value=set_theme_mode,
                dense=True,
            )

    with solara.Sidebar():
        with solara.Card("Controls", margin=1):
            solara.Text("Live Stream", style="color: var(--muted);")
            solara.Select(
                label="Exchange",
                value=selected_exchange,
                values=["coinbase", "binance", "kraken"],
            )
            solara.InputText(label="Symbol (BASE-QUOTE)", value=selected_symbol)
            solara.Select(
                label="Chart",
                value=chart_type,
                values=["Candles", "Line"],
            )
            if chart_type.value == "Candles":
                solara.Select(
                    label="Candle Timeframe",
                    value=candles_timeframe,
                    values=["1s", "5s", "15s", "1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                )
            solara.Select(
                label="History Window",
                value=history_window,
                values=["5m", "15m", "30m", "1h", "6h", "24h", "7d"],
            )
            solara.Text("Tip: zoom/pan loads more history; double-click resets to live.", style="color: var(--muted);")
            solara.Button("Refresh Coin List", on_click=fetch_coins, icon_name="mdi-sync")

    with solara.Card("Market Overview", margin=10):
        CoinDataTable()

    with solara.Card("Live Chart", margin=10):
        symbol = selected_symbol.value.strip().upper() or "BTC-USD"
        if chart_type.value == "Candles":
            CandlestickVolumeChart(
                exchange=selected_exchange.value,
                symbol=symbol,
                timeframe=candles_timeframe.value,
                history=history_window.value,
            )
        else:
            LivePriceChart(
                exchange=selected_exchange.value,
                symbol=symbol,
                is_night=is_night,
                history=history_window.value,
            )
        
    # Automatically fetch data when the component is first rendered
    solara.use_effect(fetch_coins, [])
