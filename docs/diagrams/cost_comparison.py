"""docs/cost-comparison.md の損益分岐点グラフを生成する。

matplotlibを使わず依存なしでSVGを直接書く。日本語ラベルのフォントは閲覧側で
解決されるため、生成環境にCJKフォントがなくても正しく出力できる。
配色はdatavizスキルの既定カテゴリカルパレット(slot1 blue / slot2 orange)で、
CVD分離ΔE 24.7・コントラスト3:1以上を検証済み。

    python3 docs/diagrams/cost_comparison.py
"""

from __future__ import annotations

import math
from pathlib import Path

# --- モデル定数 (docs/cost-comparison.md 2章と一致させること) ---
LAMBDA_RATE_PER_SEC = 0.0000133334  # $/秒 (chat-fn 1.0GB × arm64 GB秒単価)
FIXED_BASE = 22.91  # $/月
TASK_UNIT = 2.088  # $/月 (FastAPI 1台 + パブリックIPv4 1個)
CHROMA_SERVER = 3.09  # $/月 n>=2で必要になるChromaサーバータスク(0.5vCPU・1GB) + IPv4
HOURS_PER_MONTH = 217  # 移植元アプリの稼働時間
CHAT_SECONDS = 30  # T
PER_CHAT_VARIABLE = 1.6e-5  # $/チャット (API Gatewayとapi-fnのリクエスト課金・実行時間)
FIXED_STORAGE = 0.4  # $/月 (本アプリの固定ストレージ費)
BREAK_EVEN_HOURS = 721.9

# --- 描画領域 ---
WIDTH, HEIGHT = 880, 480
PLOT = {"left": 82, "right": 726, "top": 74, "bottom": 416}
X_MAX_HOURS = 900
Y_MAX_DOLLARS = 45

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#7a7975"
GRID = "#e6e5e1"
SERIES_LAMBDA = "#2a78d6"
SERIES_ECS = "#eb6834"
FONT = "'Noto Sans JP','Hiragino Sans','Yu Gothic UI','Meiryo',sans-serif"


def lambda_cost(hours: float) -> float:
    chats = hours * 3600 / CHAT_SECONDS
    per_chat = LAMBDA_RATE_PER_SEC * CHAT_SECONDS + PER_CHAT_VARIABLE
    return per_chat * chats + FIXED_STORAGE


def ecs_cost(hours: float) -> float:
    tasks = max(1, math.ceil(hours / HOURS_PER_MONTH))
    # 2台以上ではChromaの単一ライター制約を外すためサーバーモードへの移行が要る
    migration = CHROMA_SERVER if tasks >= 2 else 0.0
    return FIXED_BASE + TASK_UNIT * (1 + tasks) + migration


def px_x(hours: float) -> float:
    span = PLOT["right"] - PLOT["left"]
    return PLOT["left"] + hours / X_MAX_HOURS * span


def px_y(dollars: float) -> float:
    span = PLOT["bottom"] - PLOT["top"]
    return PLOT["bottom"] - dollars / Y_MAX_DOLLARS * span


def step_path() -> str:
    """ECS版の階段関数のパス。帯の境界で垂直に立ち上げる。"""
    commands = [f"M {px_x(0):.1f} {px_y(ecs_cost(0.1)):.1f}"]
    boundary = HOURS_PER_MONTH
    while boundary < X_MAX_HOURS:
        commands.append(f"L {px_x(boundary):.1f} {px_y(ecs_cost(boundary)):.1f}")
        commands.append(f"L {px_x(boundary):.1f} {px_y(ecs_cost(boundary + 0.1)):.1f}")
        boundary += HOURS_PER_MONTH
    commands.append(f"L {px_x(X_MAX_HOURS):.1f} {px_y(ecs_cost(X_MAX_HOURS)):.1f}")
    return " ".join(commands)


def build_svg() -> str:
    parts: list[str] = []
    add = parts.append

    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" font-family="{FONT}" '
        f'role="img" aria-label="月間ストリーミング時間に対する両構成の月額費用。'
        f'722時間で交差する">'
    )
    add(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{SURFACE}"/>')

    add(
        f'<text x="{PLOT["left"]}" y="32" font-size="17" font-weight="600" '
        f'fill="{TEXT_PRIMARY}">月額費用の逆転点</text>'
    )
    add(
        f'<text x="{PLOT["left"]}" y="52" font-size="12.5" fill="{TEXT_SECONDARY}">'
        f'交差は722時間/月。移植元アプリが現行構成で捌ける上限(217時間)の3.3倍にあたる</text>'
    )

    # --- グリッドと軸 ---
    for dollars in range(0, Y_MAX_DOLLARS + 1, 10):
        y = px_y(dollars)
        add(
            f'<line x1="{PLOT["left"]}" y1="{y:.1f}" x2="{PLOT["right"]}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        add(
            f'<text x="{PLOT["left"] - 10}" y="{y + 4:.1f}" font-size="11.5" '
            f'text-anchor="end" fill="{TEXT_MUTED}">${dollars}</text>'
        )
    for hours in range(0, X_MAX_HOURS + 1, 100):
        x = px_x(hours)
        add(
            f'<text x="{x:.1f}" y="{PLOT["bottom"] + 20:.1f}" font-size="11.5" '
            f'text-anchor="middle" fill="{TEXT_MUTED}">{hours}</text>'
        )
    add(
        f'<line x1="{PLOT["left"]}" y1="{PLOT["bottom"]}" x2="{PLOT["right"]}" '
        f'y2="{PLOT["bottom"]}" stroke="{TEXT_MUTED}" stroke-width="1"/>'
    )
    add(
        f'<text x="{PLOT["right"]}" y="{PLOT["bottom"] + 40:.1f}" font-size="12" '
        f'text-anchor="end" fill="{TEXT_SECONDARY}">月間ストリーミング時間 (時間/月)</text>'
    )

    # --- 現行構成の上限 ---
    cap_x = px_x(HOURS_PER_MONTH)
    add(
        f'<line x1="{cap_x:.1f}" y1="{PLOT["top"] + 50}" x2="{cap_x:.1f}" '
        f'y2="{PLOT["bottom"]}" stroke="{TEXT_MUTED}" stroke-width="1.5" '
        f'stroke-dasharray="5 4"/>'
    )
    add(
        f'<text x="{cap_x + 8:.1f}" y="{PLOT["bottom"] - 46:.1f}" font-size="11.5" '
        f'fill="{TEXT_SECONDARY}">217時間 — 移植元アプリの</text>'
    )
    add(
        f'<text x="{cap_x + 8:.1f}" y="{PLOT["bottom"] - 31:.1f}" font-size="11.5" '
        f'fill="{TEXT_SECONDARY}">現行構成が捌ける上限</text>'
    )
    add(
        f'<text x="{cap_x + 8:.1f}" y="{PLOT["bottom"] - 14:.1f}" font-size="11" '
        f'fill="{TEXT_MUTED}">これより右はベクトル層の移行が前提</text>'
    )

    # --- 系列 ---
    add(
        f'<path d="{step_path()}" fill="none" stroke="{SERIES_ECS}" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )
    add(
        f'<line x1="{px_x(0):.1f}" y1="{px_y(lambda_cost(0)):.1f}" '
        f'x2="{px_x(X_MAX_HOURS):.1f}" y2="{px_y(lambda_cost(X_MAX_HOURS)):.1f}" '
        f'stroke="{SERIES_LAMBDA}" stroke-width="2"/>'
    )

    # --- 直接ラベル ---
    add(
        f'<text x="{PLOT["right"] + 8}" y="{px_y(ecs_cost(X_MAX_HOURS)) + 4:.1f}" '
        f'font-size="12" font-weight="600" fill="{TEXT_PRIMARY}">移植元アプリ</text>'
    )
    add(
        f'<text x="{PLOT["right"] + 8}" y="{px_y(lambda_cost(X_MAX_HOURS)) + 4:.1f}" '
        f'font-size="12" font-weight="600" fill="{TEXT_PRIMARY}">本アプリ</text>'
    )

    # --- 交点 ---
    bx, by = px_x(BREAK_EVEN_HOURS), px_y(lambda_cost(BREAK_EVEN_HOURS))
    add(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="7" fill="{SURFACE}"/>')
    add(
        f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="5" fill="none" '
        f'stroke="{TEXT_PRIMARY}" stroke-width="2"/>'
    )
    add(
        f'<text x="{bx - 10:.1f}" y="{by - 30:.1f}" font-size="13" font-weight="600" '
        f'text-anchor="end" fill="{TEXT_PRIMARY}">損益分岐点 722時間/月</text>'
    )
    add(
        f'<text x="{bx - 10:.1f}" y="{by - 14:.1f}" font-size="11.5" '
        f'text-anchor="end" fill="{TEXT_SECONDARY}">両者とも $36.44/月</text>'
    )

    # --- 凡例 ---
    legend_x, legend_y = PLOT["right"] - 232, 30
    for offset, (color, label) in enumerate(
        ((SERIES_LAMBDA, "本アプリ (Lambda)"), (SERIES_ECS, "移植元アプリ (ECS)"))
    ):
        x = legend_x + offset * 122
        add(
            f'<line x1="{x}" y1="26" x2="{x + 18}" y2="26" stroke="{color}" '
            f'stroke-width="2"/>'
        )
        add(
            f'<text x="{x + 24}" y="{legend_y}" font-size="11.5" '
            f'fill="{TEXT_SECONDARY}">{label}</text>'
        )

    add("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    output = Path(__file__).with_name("cost-comparison.svg")
    output.write_text(build_svg(), encoding="utf-8")
    print(f"wrote {output}")
