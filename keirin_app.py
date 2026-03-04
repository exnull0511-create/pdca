"""
競輪予想統合UI - keirin_app.py
カレンダーで日付を選択 → 会場・レース選択
→ 出走表/ライン/オッズ/結果/S3予想を表示
"""
import sys
import os
from datetime import date, timedelta

import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import time
import re

# ---- パス設定 ----
# kdreams_scraper が c:\keirinbusines にある
KDREAMS_DIR = r"C:\keirinbusines"
if KDREAMS_DIR not in sys.path:
    sys.path.insert(0, KDREAMS_DIR)

# S3予想モジュールが c:\pdca にある
PDCA_DIR = r"C:\pdca"
if PDCA_DIR not in sys.path:
    sys.path.insert(0, PDCA_DIR)

from kdreams_scraper import KdreamsScraper
from s3_predictor import run_s3_prediction, load_sclass_db, load_racer_relations, load_racer_relations

# S級DB パス
SCLASS_DB_PATH       = r"C:\pdca\data\S級選手究極DB (1).xlsx"
RACER_RELATIONS_PATH = r"C:\pdca\data\s_class_racers.csv"

# 開催場コード → 会場名 / スラッグ マッピング
VENUE_CODE_MAP = {
    "11": ("前橋",     "maebashi"),
    "12": ("取手",     "toride"),
    "13": ("宇都宮",   "utsunomiya"),
    "14": ("大宮",     "omiya"),
    "15": ("西武園",   "seibuuen"),
    "16": ("京王閣",   "keioKaku"),
    "17": ("立川",     "tachikawa"),
    "21": ("松戸",     "matsudo"),
    "22": ("前橋",     "maebashi"),
    "23": ("川崎",     "kawasaki"),
    "24": ("平塚",     "hiratsuka"),
    "25": ("小田原",   "odawara"),
    "31": ("伊東",     "ito"),
    "32": ("静岡",     "shizuoka"),
    "33": ("浜松",     "hamamatsu"),
    "34": ("豊橋",     "toyohashi"),
    "35": ("岐阜",     "gifu"),
    "36": ("大垣",     "ogaki"),
    "37": ("名古屋",   "nagoya"),
    "38": ("津",       "tsu"),
    "39": ("松阪",     "matsusaka"),
    "41": ("奈良",     "nara"),
    "42": ("和歌山",   "wakayama"),
    "43": ("岸和田",   "kishiwada"),
    "44": ("京都向日町",  "kyoto"),
    "45": ("大阪",     "osaka"),
    "46": ("玉野",     "tamano"),
    "47": ("広島",     "hiroshima"),
    "48": ("防府",     "hofu"),
    "51": ("高松",     "takamatsu"),
    "52": ("小松島",   "komatsushima"),
    "53": ("高知",     "kochi"),
    "54": ("松山",     "matsuyama"),
    "55": ("今治",     "imabari"),
    "61": ("小倉",     "kokura"),
    "62": ("久留米",   "kurume"),
    "63": ("武雄",     "takeo"),
    "64": ("佐世保",   "sasebo"),
    "65": ("別府",     "beppu"),
    "66": ("熊本",     "kumamoto"),
    "67": ("玉名",     "tamana"),
    "68": ("大分",     "oita"),
    "69": ("宮崎",     "miyazaki"),
    "71": ("鹿児島",   "kagoshima"),
    "72": ("函館",     "hakodate"),
    "73": ("青森",     "aomori"),
    "74": ("弥彦",     "yahiko"),
    "75": ("新潟",     "niigata"),
    "76": ("長野",     "nagano"),
    "77": ("松本",     "matsumoto"),
    "78": ("富山",     "toyama"),
    "79": ("金沢",     "kanazawa"),
    "81": ("福井",     "fukui"),
    "82": ("奈良",     "nara"),
    "83": ("四日市",   "yokkaichi"),
    "84": ("大津",     "otsu"),
    "85": ("奈良",     "nara"),
}


def get_scraper():
    return KdreamsScraper()


@st.cache_resource
def get_sclass_db():
    if os.path.exists(SCLASS_DB_PATH):
        return load_sclass_db(SCLASS_DB_PATH)
    return None


@st.cache_resource
def get_racer_relations():
    """s_class_racers.csv をロードしキャッシュする"""
    if os.path.exists(RACER_RELATIONS_PATH):
        return load_racer_relations(RACER_RELATIONS_PATH)
    return None


def parse_venues(races: list) -> list:
    """
    scraper.get_races() の返値から slug / kaisai_id を抽出し
    keirin_app 内部形式に変換する。
    
    scraper の race['url'] は racecard URL:
      https://keirin.kdreams.jp/{slug}/racecard/{kaisai_id}/ など
    """
    venues = []
    seen   = set()
    for r in races:
        url = r.get('url', '')
        if not url:
            continue
        # racecard URL から slug と kaisai_id を抽出
        m = re.search(r'keirin\.kdreams\.jp/([a-z]+)/racecard/(\d{14})/', url)
        if not m:
            continue
        slug     = m.group(1)
        kaisai   = m.group(2)
        vname    = r.get('velodrome', r.get('name', '不明'))
        grade    = r.get('grade', '')
        day      = r.get('day', '')
        key      = kaisai
        if key in seen:
            continue
        seen.add(key)
        venues.append({
            'venue_name':   vname,
            'slug':         slug,
            'kaisai_id':    kaisai,
            'grade':        grade,
            'day':          day,
            'racecard_url': f"https://keirin.kdreams.jp/{slug}/racecard/{kaisai}/",
        })
    return venues



def build_race_url(slug: str, kaisai_id: str, race_no: int) -> str:
    """
    race_no: 1-indexed (1〜12)
    race_id = kaisai_id(14桁) + race_no 2桁ゼロ埋め = 16桁
    例: kaisai_id='44202602280300', race_no=1 → '4420260228030001'
    """
    race_id = f"{kaisai_id}{race_no:02d}"
    return f"https://keirin.kdreams.jp/{slug}/racedetail/{race_id}/"


# ==========================================
# メイン UI
# ==========================================
def main():
    st.set_page_config(
        page_title="競輪予想AI - S3ロジック",
        page_icon="🚴",
        layout="wide",
    )

    # ヘッダー
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { color: #e94560; margin: 0; font-size: 2rem; }
    .main-header p  { color: #aaa; margin: 0.3rem 0 0; }
    .ev-card {
        background: #1e1e2e;
        border: 1px solid #3a3a5c;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.5rem;
    }
    .ev-bar { background: #0f3460; height: 8px; border-radius: 4px; margin-top: 4px; }
    .ev-bar-fill { background: linear-gradient(90deg,#e94560,#f5a623); height: 8px; border-radius: 4px; }
    .s3-pass   { background: #1a3a1a; border: 1px solid #4caf50; border-radius: 8px; padding: 0.8rem; color: #e8f5e9; }
    .s3-skip   { background: #3a1a1a; border: 1px solid #f44336; border-radius: 8px; padding: 0.8rem; color: #ffebee; }
    .bet-chip  {
        display: inline-block; background:#0f3460; color:#fff;
        border-radius:4px; padding:2px 7px; margin:2px; font-size:0.85rem;
    }
    </style>
    <div class="main-header">
      <h1>🚴 競輪予想AI</h1>
      <p>S3ロジック（EVスコア + ライン構成 + Hidden Monster）</p>
    </div>
    """, unsafe_allow_html=True)

    scraper = get_scraper()
    db_all     = get_sclass_db()
    relations  = get_racer_relations()

    if db_all is None:
        st.error(f"S級選手究極DBが見つかりません: {SCLASS_DB_PATH}")
        return

    # =========================================
    # サイドバー
    # =========================================
    st.sidebar.header("📅 レース選択")

    date_option = st.sidebar.radio(
        "取得日程",
        ["📅 今日", "⏮️ 前日"],
        horizontal=True,
    )
    date_type = "today" if "今日" in date_option else "yesterday"
    today     = date.today()
    disp_date = today if date_type == "today" else today - timedelta(days=1)

    st.sidebar.caption(f"開催日: {disp_date.strftime('%Y/%m/%d')}")

    if st.sidebar.button("🔄 開催場一覧を取得", use_container_width=True, type="primary"):
        with st.spinner("開催場を取得中..."):
            raw    = scraper.get_races(date_type)
            venues = parse_venues(raw)
            st.session_state.venues       = venues
            st.session_state.disp_date    = disp_date
            st.session_state.race_data    = None
            if not venues:
                st.sidebar.error("開催場が見つかりませんでした")

    # 会場選択
    if 'venues' in st.session_state and st.session_state.venues:
        venues = st.session_state.venues
        venue_labels = [f"{v['venue_name']}" for v in venues]

        sel_v_idx = st.sidebar.selectbox(
            "会場", range(len(venue_labels)),
            format_func=lambda i: venue_labels[i],
            key="venue_sel"
        )
        sel_venue = venues[sel_v_idx]

        # レース番号選択
        race_no = st.sidebar.selectbox(
            "レース番号", list(range(1, 13)),
            format_func=lambda n: f"{n}R",
            key="race_no_sel"
        )

        race_url = build_race_url(
            sel_venue['slug'], sel_venue['kaisai_id'], race_no
        )
        st.sidebar.caption(f"URL: `{race_url}`")
        st.sidebar.markdown("---")

        if st.sidebar.button("📥 データ取得 + S3予想", use_container_width=True, type="primary"):
            with st.spinner("データ取得中...（20〜40秒）"):
                race_card  = scraper.get_race_card(race_url)
                lines      = scraper.get_race_lines(race_url)
                odds       = scraper.get_odds(race_url)
                results    = scraper.get_race_results(race_url)

                # S3予想
                pred = run_s3_prediction(
                    race_card_df=race_card,
                    lines=lines,
                    odds_df=odds,
                    db_all=db_all,
                    venue=sel_venue['venue_name'],
                    race_date=st.session_state.get('disp_date', date.today()),
                    relations_df=relations,
                )

                st.session_state.race_data = {
                    'race_card': race_card,
                    'lines':     lines,
                    'odds':      odds,
                    'results':   results,
                    'pred':      pred,
                    'venue':     sel_venue['venue_name'],
                    'race_no':   race_no,
                    'race_url':  race_url,
                    'date':      st.session_state.get('disp_date', date.today()),
                }
            st.rerun()

    elif 'venues' not in st.session_state:
        st.sidebar.info("👆 「開催場一覧を取得」を押してください")

    # =========================================
    # メインエリア
    # =========================================
    if 'race_data' in st.session_state and st.session_state.race_data:
        d = st.session_state.race_data

        st.subheader(
            f"🏁 {d['date'].strftime('%Y/%m/%d')}  "
            f"{d['venue']} {d['race_no']}R"
        )

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📋 出走表", "🔗 ライン構成", "💰 オッズ (1〜50位)",
            "🏆 レース結果", "🤖 S3予想"
        ])

        # ---- Tab1: 出走表 ----
        with tab1:
            rc = d['race_card']
            if rc is not None and not rc.empty:
                st.markdown(f"**{len(rc)}名出走**")
                st.dataframe(rc, use_container_width=True, height=400)
            else:
                st.warning("出走表データが取得できませんでした")

        # ---- Tab2: ライン構成 ----
        with tab2:
            lines = d['lines']
            if lines:
                for item in sorted(lines, key=lambda x: x['line']):
                    bibs  = item['bibs']
                    names = []
                    # 車番(int/float) → int 変換して名前ルックアップ
                    rc_df = d['race_card']
                    for b in bibs:
                        b_int = int(b)
                        name = f"#{b_int}"
                        if rc_df is not None and not rc_df.empty:
                            row = rc_df[rc_df['車番'].astype(int) == b_int]
                            if not row.empty:
                                name = str(row['選手名'].values[0])
                        names.append(name)

                    members = " → ".join(f"{b}{n}" for b, n in zip(bibs, names))
                    st.markdown(f"**ライン{item['line']}：** {members}")
                    st.progress(1.0)
            else:
                st.info("ライン構成データがありません")

        # ---- Tab3: オッズ ----
        with tab3:
            odds = d['odds']
            if odds is not None and not odds.empty:
                st.markdown(f"**{len(odds)}通りのオッズ取得**")
                # 1〜50位だけ表示
                st.dataframe(odds.head(50), use_container_width=True, height=500)
            else:
                st.warning("オッズデータを取得できませんでした（JS動的読み込みの場合は非対応）")

        # ---- Tab4: レース結果 ----
        with tab4:
            res = d['results']
            if res is not None and not res.empty:
                st.success("✅ レース終了済み")
                st.dataframe(res, use_container_width=True, height=350)
            else:
                st.info("レース結果はまだ確定していないか、取得できませんでした")

        # ---- Tab5: S3予想 ----
        with tab5:
            pred = d['pred']
            if not pred:
                st.error("予想データがありません")
            else:
                # S3フィルタ結果
                if pred['s3_pass']:
                    bet_unit = pred['bet_unit']
                    bets     = pred['bets']
                    st.markdown(f"""
                    <div class="s3-pass">
                    ✅ <b>S3フィルタ通過</b> ─ 買い目 <b>{len(bets)}点</b>
                    &nbsp;|&nbsp; 1点 <b>{bet_unit}円</b>
                    &nbsp;|&nbsp; 合計投資 <b>¥{len(bets)*bet_unit:,}</b>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="s3-skip">
                    ⏭️ <b>S3フィルタ ─ 見送り</b><br>
                    理由: {pred['s3_skip_reason']}
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("")

                # カオス/鬼脚バッジ
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("軸EVスコア", f"{pred['top_ev']:.1f}")
                c2.metric("EV差 (1-2位)", f"{pred['ev_gap']:.1f}")
                c3.metric("カオス展開", "⚡ YES" if pred['is_chaos'] else "✅ NO")
                c4.metric("Hidden Monster", "🔥 あり" if pred['has_monster'] else "なし")

                st.markdown("---")

                # EVランキング
                st.markdown("#### 📊 EVランキング")
                ranked = pred['ranked']
                if ranked:
                    max_ev = ranked[0][1]['ev_score']
                    for i, (num, d_score) in enumerate(ranked, 1):
                        ev  = d_score['ev_score']
                        try:
                            pct = 0 if (pd.isna(ev) or not max_ev or pd.isna(max_ev)) \
                                  else max(0, min(100, int(float(ev) / float(max_ev) * 100)))
                        except Exception:
                            pct = 0
                        mon  = "🔥" if d_score['is_monster'] else ""
                        unr  = "⚠️" if d_score['is_unreliable'] else ""
                        axis = "【軸】" if num == pred['axis_num'] else ""
                        line_info = (f"L{d_score['line_no']}-{d_score['pos_in_line']}番手"
                                     if d_score['line_no'] else "")
                        # 展開スコア内訳（relations_dfがある場合のみ）
                        syn  = d_score.get('synergy',   0)
                        dev  = d_score.get('dev_score', 0)
                        men  = d_score.get('mental',    0)
                        base = d_score.get('base_ev',   d_score['ev_score'])
                        dev_detail = (f" | 連携:{syn:.1f} 展開:{dev:.1f} 心理:{men:.1f}"
                                      if (syn or dev or men) else "")
                        st.markdown(
                            f"<div class='ev-card'>"
                            f"<b>{i}位 車番{num} {d_score['name']}</b> "
                            f"{axis}{mon}{unr} "
                            f"<span style='color:#aaa;font-size:0.85rem'>"
                            f"{line_info} | 展開EV:{ev:.1f} (基:{base:.1f}){dev_detail} "
                            f"| IP:{d_score['ip']:.1f} EP:{d_score['ep']:.1f} "
                            f"| DB:{d_score['hist_count']}戦</span>"
                            f"<div class='ev-bar'><div class='ev-bar-fill' style='width:{pct}%'></div></div>"
                            f"</div>",
                            unsafe_allow_html=True
                        )

                # 買い目表示（S3フィルタ結果に関係なく常に表示）
                if pred['bets']:
                    st.markdown("---")
                    label = "🎯 買い目（S3推奨）" if pred['s3_pass'] else "📋 買い目（参考 / S3見送り）"
                    st.markdown(f"#### {label}")
                    st.caption(f"軸: 車番{pred['axis_num']}  |  {len(pred['bets'])}点")
                    chips = "".join(
                        f"<span class='bet-chip'>{b}</span>"
                        for b in pred['bets']
                    )
                    st.markdown(chips, unsafe_allow_html=True)

    else:
        # ウェルカム画面
        st.markdown("""
        ### 👈 サイドバーの手順
        1. **日付を選択**（カレンダー）
        2. **「開催場一覧を取得」** ボタンを押す
        3. **会場** と **レース番号** を選択
        4. **「データ取得 + S3予想」** ボタンを押す

        #### 表示される情報
        | タブ | 内容 |
        |------|------|
        | 📋 出走表 | 選手名・競走得点・脚質など19カラム |
        | 🔗 ライン構成 | 各ラインの車番・選手 |
        | 💰 オッズ | 3連単 1〜50番人気 |
        | 🏆 レース結果 | 着順・着差・決まり手・上がり |
        | 🤖 S3予想 | EVランキング・買い目14点・フィルタ判定 |
        """)


if __name__ == "__main__":
    main()
