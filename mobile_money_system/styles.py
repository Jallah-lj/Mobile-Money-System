"""Design system for the Mobile Money web app.

`get_custom_css(dark=...)` returns a complete theme stylesheet built from
design tokens, so the light and dark themes share one source of truth.

Theme-safety rules (learned the hard way):
  * We never force a text color onto Streamlit's native components globally.
    Streamlit follows the browser's color scheme by default, so a global
    override can paint dark text onto dark native surfaces (invisible text).
    Native components keep their own theme; only our custom components use
    the tokens below.
  * In dark mode we additionally recolor only the native text that sits on
    the (now dark) canvas, via scoped selectors that do not touch the
    semantic colors inside our custom cards.
"""

# --- Design tokens -----------------------------------------------------------

LIGHT_TOKENS = {
    "bg": "#f4f6fb",
    "surface": "#ffffff",
    "surface-2": "#f8fafc",
    "text": "#0f172a",
    "muted": "#5c6a7d",
    "border": "#e2e8f0",
    "primary": "#00C853",
    "primary-dark": "#009624",
    "primary-deep": "#007a1e",
    "primary-soft": "#e8f9ee",
    "gold-dark": "#b45309",
    "danger": "#cc1843",
    "danger-soft": "#ffe4e9",
    "shadow": "0 10px 30px rgba(15, 23, 42, 0.08)",
    "shadow-sm": "0 2px 8px rgba(15, 23, 42, 0.06)",
    "title-gradient": "linear-gradient(135deg, #008a24 0%, #00701a 100%)",
    "btn-gradient": "linear-gradient(135deg, #008a24 0%, #005c14 100%)",
}

DARK_TOKENS = {
    "bg": "#0b1220",
    "surface": "#131c30",
    "surface-2": "#0f1729",
    "text": "#e6ecf7",
    "muted": "#94a3b8",
    "border": "#243452",
    "primary": "#00e676",
    "primary-dark": "#00c853",
    "primary-deep": "#00e676",
    "primary-soft": "#123524",
    "gold-dark": "#f59e0b",
    "danger": "#fb7185",
    "danger-soft": "#3f1d2b",
    "shadow": "0 10px 30px rgba(0, 0, 0, 0.45)",
    "shadow-sm": "0 2px 8px rgba(0, 0, 0, 0.35)",
    "title-gradient": "linear-gradient(135deg, #00e676 0%, #00c853 100%)",
    "btn-gradient": "linear-gradient(135deg, #008a24 0%, #005c14 100%)",
}

# Brand gradient for the wallet card. All text-on-gradient pairs are chosen
# to meet WCAG AA contrast (white on the green wallet card >= 4.5:1).
WALLET_GRADIENT = "linear-gradient(135deg, #008a24 0%, #00701a 60%, #005c14 100%)"


def _tokens_css(t: dict) -> str:
    return "\n".join(f"    --mms-{k}: {v};" for k, v in t.items())


def _dark_mode_overrides() -> str:
    """Dark-mode-only rules aligning native Streamlit elements with the dark canvas."""
    return """
        /* ===== Dark mode: align native elements with the dark canvas ===== */

        /* Sidebar text (themed via tokens in both modes, restated for clarity) */
        section[data-testid="stSidebar"] * {
            color: var(--mms-text);
        }

        /* Native text sitting directly on the dark canvas: markdown,
           headings, captions, alerts, tables, metrics, expanders and widget
           labels. Scoped selectors — they beat Streamlit's emotion classes
           by specificity but never flatten the semantic colors inside our
           custom cards. */
        .block-container [data-testid="stMarkdown"],
        .block-container [data-testid="stHeading"],
        .block-container [data-testid="stCaption"],
        .block-container [data-testid="stAlert"],
        .block-container [data-testid="stTable"],
        .block-container [data-testid="stDataFrame"],
        .block-container [data-testid="stMetric"],
        .block-container [data-testid="stExpander"],
        .block-container label {
            color: var(--mms-text);
        }

        /* Outline-button hover: the hover fill is the bright dark-mode green,
           so keep the label dark — white on it would be nearly invisible. */
        .stButton > button:hover {
            color: #0b1220 !important;
        }
    """


def _light_mode_overrides() -> str:
    """Light-mode rules pinning native Streamlit text to the dark token.

    Streamlit's native components can follow the browser's color scheme and
    render LIGHT text even when our canvas is pinned light — which makes
    headings, labels, alerts and messages invisible on the white canvas.
    Pinning the text color to the theme token keeps every native element
    readable on the light canvas, regardless of the browser's color scheme.
    """
    return """
        /* ===== Light mode: pin native text to the dark token ===== */

        /* Sidebar text on the light sidebar surface */
        section[data-testid="stSidebar"] * {
            color: var(--mms-text);
        }

        /* Native text sitting directly on the light canvas: markdown,
           headings, captions, alerts, tables, metrics, expanders and widget
           labels. Scoped selectors — they beat Streamlit's emotion classes
           by specificity but never flatten the semantic colors inside our
           custom cards. */
        .block-container [data-testid="stMarkdown"],
        .block-container [data-testid="stHeading"],
        .block-container [data-testid="stCaption"],
        .block-container [data-testid="stAlert"],
        .block-container [data-testid="stTable"],
        .block-container [data-testid="stDataFrame"],
        .block-container [data-testid="stMetric"],
        .block-container [data-testid="stExpander"],
        .block-container label {
            color: var(--mms-text);
        }
    """


def get_custom_css(dark: bool = False) -> str:
    t = DARK_TOKENS if dark else LIGHT_TOKENS
    theme_block = _dark_mode_overrides() if dark else _light_mode_overrides()
    return f"""
    <style>
        /* Import Google Font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        /* FontAwesome CDN */
        @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');

        :root {{
{_tokens_css(t)}
            --mms-wallet-gradient: {WALLET_GRADIENT};
        }}

        /* Page canvas. NOTE: we deliberately do NOT set a global text color on
           Streamlit's native elements ([class*="css"]) — Streamlit follows the
           browser color scheme, and forcing our token color there can make
           native text invisible. Only the font is shared. */
        html, body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--mms-bg);
            color: var(--mms-text);
        }}
        [class*="css"] {{
            font-family: 'Inter', sans-serif;
        }}

        /* App canvas follows the active theme */
        .stApp {{
            background-color: var(--mms-bg);
        }}

        /* Hides Streamlit Default chrome */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}

        .block-container {{
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
            max-width: 1200px;
        }}

        /* --- Animations --- */
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        @keyframes shimmer {{
            0% {{ background-position: -200% 0; }}
            100% {{ background-position: 200% 0; }}
        }}

        .stContainer, .css-1r6slb0, .css-12oz5g7 {{
            animation: fadeIn 0.5s ease-out;
        }}

        /* --- Sidebar --- */
        section[data-testid="stSidebar"] {{
            background-color: var(--mms-surface-2);
            border-right: 1px solid var(--mms-border);
        }}
        section[data-testid="stSidebar"] * {{
            color: var(--mms-text);
        }}

        /* --- Typography --- */
        /* App title: solid brand color as a safe fallback; the gradient text
           is only applied when the browser supports background-clip: text,
           so the title can never render invisible. Both the fallback and
           the gradient meet WCAG AA contrast on the canvas. */
        .app-title {{
            color: var(--mms-primary-deep);
            font-weight: 800;
        }}
        @supports ((-webkit-background-clip: text) or (background-clip: text)) {{
            .app-title {{
                background: var(--mms-title-gradient);
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
        }}

        /* --- Wallet Card --- */
        .wallet-card {{
            background: var(--mms-wallet-gradient);
            color: white;
            padding: 25px;
            border-radius: 20px;
            box-shadow: 0 10px 25px rgba(0, 200, 83, 0.3);
            margin-bottom: 20px;
            position: relative;
            overflow: hidden;
            animation: fadeIn 0.8s ease-out;
        }}
        .wallet-card::before {{
            content: "";
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.12) 0%, transparent 60%);
            transform: rotate(30deg);
        }}
        .balance-label {{
            font-size: 0.9rem;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .balance-value {{
            font-size: 2.5rem;
            font-weight: 800;
            margin: 10px 0;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .wallet-details {{
            display: flex;
            justify-content: space-between;
            font-size: 0.9rem;
            align-items: center;
        }}

        .stat-chip {{
            background: var(--mms-surface);
            border: 1px solid var(--mms-border);
            border-radius: 12px;
            padding: 14px 18px;
            box-shadow: var(--mms-shadow-sm);
            color: var(--mms-text);
        }}
        .stat-chip .stat-label {{
            color: var(--mms-muted);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat-chip .stat-value {{
            color: var(--mms-text);
            font-size: 1.4rem;
            font-weight: 700;
        }}

        /* --- Generic cards --- */
        .metric-card {{
            background-color: var(--mms-surface);
            border-radius: 12px;
            padding: 20px;
            box-shadow: var(--mms-shadow-sm);
            text-align: center;
            transition: transform 0.2s;
            margin-bottom: 10px;
            border: 1px solid var(--mms-border);
            border-left: 5px solid var(--mms-primary);
            color: var(--mms-text);
        }}
        .metric-card:hover {{ transform: translateY(-2px); }}
        .metric-title {{
            color: var(--mms-muted);
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .metric-value {{
            font-size: 1.9em;
            font-weight: 800;
            color: var(--mms-text);
        }}
        .conf-card {{
            background-color: var(--mms-surface);
            padding: 20px;
            border-radius: 14px;
            box-shadow: var(--mms-shadow-sm);
            border: 1px solid var(--mms-border);
            color: var(--mms-text);
        }}
        .conf-label {{
            color: var(--mms-muted);
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .conf-amount {{
            font-size: 1.8em;
            font-weight: 800;
            color: var(--mms-text);
        }}
        .empty-state {{
            text-align: center;
            padding: 40px 20px;
            color: var(--mms-muted);
            background: var(--mms-surface);
            border: 1px dashed var(--mms-border);
            border-radius: 14px;
        }}
        .empty-state i {{ font-size: 2.5rem; margin-bottom: 10px; color: var(--mms-primary-deep); }}

        /* --- Buttons --- */
        .stButton > button {{
            background-color: var(--mms-surface) !important;
            color: var(--mms-primary-deep) !important;
            border: 2px solid var(--mms-primary) !important;
            border-radius: 12px !important;
            padding: 0.5rem 1rem !important;
            font-weight: 600 !important;
            transition: all 0.25s ease !important;
            width: 100%;
        }}
        .stButton > button:hover {{
            background-color: var(--mms-primary-deep) !important;
            color: white !important;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 122, 30, 0.25);
        }}
        div[data-testid="stForm"] .stButton > button,
        .stButton > button[kind="primary"] {{
             background: var(--mms-btn-gradient) !important;
             color: white !important;
             border: none !important;
        }}
        .stButton > button[kind="primary"]:hover {{
             filter: brightness(1.08);
        }}

        /* --- Inputs --- */
        .stTextInput > div > div > input,
        .stNumberInput > div > div > input,
        .stSelectbox > div > div > div {{
            border-radius: 10px !important;
            border: 1px solid var(--mms-border) !important;
            background-color: var(--mms-surface) !important;
            color: var(--mms-text) !important;
        }}
        .stTextInput > div > div > input:focus,
        .stNumberInput > div > div > input:focus {{
            border-color: var(--mms-primary) !important;
            box-shadow: 0 0 0 3px var(--mms-primary-soft) !important;
        }}

        /* --- Forms --- */
        [data-testid="stForm"] {{
            background-color: var(--mms-surface);
            padding: 2rem;
            border-radius: 16px;
            box-shadow: var(--mms-shadow-sm);
            border: 1px solid var(--mms-border);
            color: var(--mms-text);
        }}

        /* --- Dataframes / tables --- */
        [data-testid="stDataFrame"] {{
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--mms-border);
        }}

        /* --- Action grid --- */
        .action-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            padding: 10px;
            background: var(--mms-surface);
            border-radius: 15px;
            box-shadow: var(--mms-shadow-sm);
            border: 1px solid var(--mms-border);
            margin-bottom: 20px;
        }}
        .action-item {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 10px;
            cursor: pointer;
            transition: transform 0.2s;
        }}
        .action-item:hover {{ transform: scale(1.08); }}
        .icon-circle {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 8px;
            font-size: 1.2rem;
            color: white;
            box-shadow: 0 4px 8px rgba(0,0,0,0.12);
        }}
        .bg-green {{ background: #00C853; }}
        .bg-blue {{ background: #2979FF; }}
        .bg-orange {{ background: #FF9100; }}
        .bg-red {{ background: #FF3D00; }}
        .bg-purple {{ background: #651FFF; }}
        .action-label {{
            font-size: 0.8rem;
            color: var(--mms-muted);
            font-weight: 500;
            text-align: center;
        }}

        /* --- Transaction list --- */
        .tx-card {{
            background: var(--mms-surface);
            padding: 15px;
            border-radius: 12px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            transition: background 0.2s;
            border: 1px solid var(--mms-border);
            border-left: 4px solid var(--mms-primary);
            box-shadow: var(--mms-shadow-sm);
            color: var(--mms-text);
        }}
        .tx-card:hover {{ background: var(--mms-surface-2); }}
        .tx-icon {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--mms-surface-2);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 15px;
            font-size: 1.1rem;
        }}
        .tx-details {{ flex-grow: 1; color: var(--mms-text); }}
        .tx-amount.credit {{ color: var(--mms-primary-deep); font-weight: 700; }}
        .tx-amount.debit {{ color: var(--mms-danger); font-weight: 700; }}
{theme_block}

        /* --- Accessibility --- */
        /* Respect users who prefer reduced motion: no infinite shimmer/pulse
           animations and no non-essential transitions (WCAG 2.2.2). */
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation: none !important;
                transition: none !important;
            }}
        }}

        /* Always show a clear, theme-aware focus indicator for keyboard
           users (WCAG 2.4.7 Focus Visible). */
        :focus-visible {{
            outline: 3px solid var(--mms-primary-deep) !important;
            outline-offset: 2px !important;
            border-radius: 4px;
        }}

        /* --- Mobile responsiveness --- */
        @media (max-width: 768px) {{
            .stButton>button {{ height: 3.5em; font-size: 1rem; }}
            .metric-value {{ font-size: 1.6em; }}
            .balance-value {{ font-size: 2rem; }}
            .conf-card {{ padding: 15px !important; }}
            .conf-amount {{ font-size: 1.5em !important; }}
            .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
            .action-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
    """
