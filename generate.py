import requests
import pandas as pd
import numpy as np
import json
import math
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

# ==============================================================================
# MODUŁ PPDA / OPPDA — Zamrożone prawdziwe dane po GW8
# Gdy Understat wróci online, podmieniamy WYŁĄCZNIE tę jedną funkcję.
# ==============================================================================
def pobierz_ppda_oppda():
    return {
        'MCI': {'PPDA': 8.71,  'OPPDA': 12.57},
        'ARS': {'PPDA': 9.41,  'OPPDA': 12.99},
        'BHA': {'PPDA': 6.58,  'OPPDA': 19.30},
        'LIV': {'PPDA': 8.62,  'OPPDA': 11.52},
        'CHE': {'PPDA': 14.01, 'OPPDA': 11.00},
        'BRE': {'PPDA': 7.98,  'OPPDA': 8.49},
        'LEE': {'PPDA': 8.66,  'OPPDA': 10.23},
        'NEW': {'PPDA': 9.02,  'OPPDA': 10.76},
        'AVL': {'PPDA': 14.37, 'OPPDA': 7.76},
        'HUL': {'PPDA': 15.79, 'OPPDA': 8.03},
        'EVE': {'PPDA': 14.13, 'OPPDA': 9.86},
        'IPS': {'PPDA': 12.30, 'OPPDA': 11.64},
        'BOU': {'PPDA': 9.74,  'OPPDA': 10.15},
        'TOT': {'PPDA': 7.57,  'OPPDA': 12.21},
        'FUL': {'PPDA': 10.73, 'OPPDA': 16.81},
        'MUN': {'PPDA': 11.03, 'OPPDA': 11.36},
        'CRY': {'PPDA': 15.12, 'OPPDA': 10.01},
        'NFO': {'PPDA': 12.18, 'OPPDA': 8.90},
        'COV': {'PPDA': 19.47, 'OPPDA': 8.99},
        'SUN': {'PPDA': 10.77, 'OPPDA': 9.25},
    }

def norm_txt(s):
    s = str(s or '').lower().strip()
    repl = {
        'ß': 'ss', 'ø': 'o', 'ł': 'l', 'đ': 'd', 'ð': 'd',
        'ı': 'i', 'æ': 'ae', 'œ': 'oe', 'þ': 'th'
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    s = unicodedata.normalize('NFD', s)
    return ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')

def safe_num_col(df, col, default=0.0):
    if col in df.columns:
        return pd.to_numeric(df[col], errors='coerce').fillna(default)
    return pd.Series(default, index=df.index, dtype=float)

updated_at = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%Y-%m-%d %H:%M")
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

print("1/5 Pobieranie aktualnych danych z oficjalnego FPL API...")
r_base = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", headers=headers, timeout=25)
r_base.raise_for_status()
base_data = r_base.json()

r_fix = requests.get("https://fantasy.premierleague.com/api/fixtures/", headers=headers, timeout=25)
r_fix.raise_for_status()
fixtures_raw = r_fix.json()

elements_df = pd.DataFrame(base_data['elements'])
teams_df = pd.DataFrame(base_data['teams'])
events_df = pd.DataFrame(base_data['events'])
fixtures_df = pd.DataFrame(fixtures_raw)

id_to_team = dict(zip(teams_df['id'], teams_df['name']))
id_to_short = dict(zip(teams_df['id'], teams_df['short_name']))
pos_map = {1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD'}

next_ev = events_df[events_df['is_next'] == True]
if not next_ev.empty:
    next_gw_num = int(next_ev['id'].iloc[0])
else:
    curr_ev = events_df[events_df['is_current'] == True]
    next_gw_num = min(int(curr_ev['id'].iloc[0]) + 1, 38) if not curr_ev.empty else 1

# ==============================================================================
# POBIERANIE FORMY Z OSTATNICH 5 ZAKOŃCZONYCH KOLEJEK (L5)
# ==============================================================================
finished_gw_ids = sorted(events_df[events_df['finished'] == True]['id'].astype(int).tolist())
l5_gws = finished_gw_ids[-5:] if finished_gw_ids else []
l5_label = f"GW{l5_gws[0]}–GW{l5_gws[-1]}" if len(l5_gws) >= 2 else (f"GW{l5_gws[0]}" if l5_gws else "Brak")
print(f"2/5 Pobieranie formy L5 ({l5_label} — {len(l5_gws)} kolejek)...")

l5_stats = {}
for gw_id in l5_gws:
    try:
        r_live = requests.get(f"https://fantasy.premierleague.com/api/event/{gw_id}/live/", headers=headers, timeout=20)
        r_live.raise_for_status()
        for el in r_live.json().get('elements', []):
            eid = int(el['id'])
            st = el.get('stats', {})
            if eid not in l5_stats:
                l5_stats[eid] = {'min': 0, 'xg': 0.0, 'xa': 0.0, 'played': 0, 'last_min': 0}
            m_gw = int(st.get('minutes', 0) or 0)
            l5_stats[eid]['min'] += m_gw
            l5_stats[eid]['xg'] += float(st.get('expected_goals', 0.0) or 0.0)
            l5_stats[eid]['xa'] += float(st.get('expected_assists', 0.0) or 0.0)
            if m_gw > 0:
                l5_stats[eid]['played'] += 1
            if gw_id == l5_gws[-1]:
                l5_stats[eid]['last_min'] = m_gw
    except Exception as e:
        print(f"Ostrzeżenie: nie udało się pobrać kolejki GW{gw_id} dla L5 ({e})")

# ==============================================================================
# 1. TABELA PIŁKARZY (z DefCon, Saves, Bonus, BPS, Kartkami, Statusami i SFG)
# ==============================================================================
df_p = pd.DataFrame()
df_p['id'] = elements_df['id'].astype(int)
df_p['player'] = (elements_df['first_name'].astype(str) + " " + elements_df['second_name'].astype(str)).str.strip()
df_p['web_name'] = elements_df['web_name'].astype(str).str.strip()
df_p['team'] = elements_df['team'].map(id_to_team)
df_p['team_short'] = elements_df['team'].map(id_to_short)
df_p['team_id'] = elements_df['team'].astype(int)
df_p['apps'] = safe_num_col(elements_df, 'starts', 0).astype(int)
df_p['min'] = safe_num_col(elements_df, 'minutes', 0).astype(int)
df_p['G'] = safe_num_col(elements_df, 'goals_scored', 0).astype(int)
df_p['A'] = safe_num_col(elements_df, 'assists', 0).astype(int)
df_p['xG'] = safe_num_col(elements_df, 'expected_goals', 0.0)
df_p['NPxG'] = df_p['xG']
df_p['xA'] = safe_num_col(elements_df, 'expected_assists', 0.0)
df_p['xGChain'] = (
    safe_num_col(elements_df, 'expected_goal_involvements', 0.0)
    if 'expected_goal_involvements' in elements_df.columns
    else (df_p['xG'] + df_p['xA'])
)
df_p['xG90'] = np.where(df_p['min'] > 0, (df_p['xG'] / df_p['min']) * 90.0, 0.0)
df_p['xA90'] = np.where(df_p['min'] > 0, (df_p['xA'] / df_p['min']) * 90.0, 0.0)
df_p['Pozycja'] = elements_df['element_type'].map(pos_map)
df_p['Posiadanie'] = safe_num_col(elements_df, 'selected_by_percent', 0.0) / 100.0
df_p['Cena'] = safe_num_col(elements_df, 'now_cost', 0.0) / 10.0

# Nowe kolumny analityczne z FPL API (DefCon, Obrony, Bonus, BPS, Kartki)
if 'defensive_contribution' in elements_df.columns:
    df_p['DefCon'] = safe_num_col(elements_df, 'defensive_contribution', 0).astype(int)
else:
    cbi = safe_num_col(elements_df, 'clearances_blocks_interceptions', 0)
    tck = safe_num_col(elements_df, 'tackles', 0)
    rec = safe_num_col(elements_df, 'recoveries', 0)
    df_p['DefCon'] = np.where(df_p['Pozycja'] == 'DEF', cbi + tck, cbi + tck + rec).astype(int)

df_p['DefCon90'] = np.where(df_p['min'] > 0, (df_p['DefCon'] / df_p['min']) * 90.0, 0.0)
df_p['Obrony'] = safe_num_col(elements_df, 'saves', 0).astype(int)
df_p['Saves90'] = np.where(df_p['min'] > 0, (df_p['Obrony'] / df_p['min']) * 90.0, 0.0)
df_p['Bonus'] = safe_num_col(elements_df, 'bonus', 0).astype(int)
df_p['BPS'] = safe_num_col(elements_df, 'bps', 0).astype(int)
df_p['Bonus90'] = np.where(df_p['min'] > 0, (df_p['Bonus'] / df_p['min']) * 90.0, 0.0)
df_p['BPS90'] = np.where(df_p['min'] > 0, (df_p['BPS'] / df_p['min']) * 90.0, 0.0)
df_p['ZK'] = safe_num_col(elements_df, 'yellow_cards', 0).astype(int)
df_p['CzK'] = safe_num_col(elements_df, 'red_cards', 0).astype(int)

# Flagi dostępności / kontuzji oraz stałe fragmenty gry
df_p['status'] = elements_df['status'].fillna('a').astype(str) if 'status' in elements_df.columns else 'a'
df_p['news'] = elements_df['news'].fillna('').astype(str) if 'news' in elements_df.columns else ''

def calc_chance(row):
    raw = row.get('chance_of_playing_next_round', None)
    st = str(row.get('status', 'a') or 'a')
    if pd.notna(raw):
        return int(float(raw))
    if st == 'a':
        return 100
    if st in ('i', 's', 'u', 'n'):
        return 0
    return 50

df_p['chance'] = elements_df.apply(calc_chance, axis=1).astype(int)
pen_ord = safe_num_col(elements_df, 'penalties_order', 0)
cor_ord = safe_num_col(elements_df, 'corners_and_indirect_freekicks_order', 0)
dfk_ord = safe_num_col(elements_df, 'direct_freekicks_order', 0)
df_p['is_pen'] = (pen_ord == 1).astype(int)
df_p['is_setp'] = ((cor_ord == 1) | (dfk_ord == 1)).astype(int)

# Statystyki z ostatnich 5 kolejek (L5)
df_p['min_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('min', 0)).astype(int)
df_p['played_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('played', 0)).astype(int)
df_p['last_min'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('last_min', 0)).astype(int)
df_p['xg_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('xg', 0.0)).astype(float)
df_p['xa_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('xa', 0.0)).astype(float)

df_players = df_p[df_p['min'] > 0].copy()
max_price_slider = round(max(16.0, float(df_p['Cena'].max()) + 1.0), 1)

df_all_catalog = df_p[['player', 'web_name', 'team', 'team_short', 'Pozycja', 'Cena', 'status', 'chance', 'news']].copy()
df_all_catalog['Cena'] = df_all_catalog['Cena'].round(1)

catalog_norm_map = {norm_txt(row['player']): row['player'] for _, row in df_all_catalog.iterrows()}
def resolve_official_name(name):
    if not name:
        return ""
    n = norm_txt(name)
    for cand in [n, n.replace('dj', 'd')]:
        if cand in catalog_norm_map:
            return catalog_norm_map[cand]
    for cand in [n, n.replace('dj', 'd')]:
        for k, v in catalog_norm_map.items():
            if cand in k:
                return v
    return name

# ==============================================================================
# 2. TABELA PREMIER LEAGUE
# ==============================================================================
print("3/5 Przeliczanie Tabeli Premier League, Median i wskaźników FDR...")

ppda_baza = pobierz_ppda_oppda()
is_fin = (fixtures_df['finished'] == True)
if 'finished_provisional' in fixtures_df.columns:
    is_fin = is_fin | (fixtures_df['finished_provisional'] == True)

finished_fix = fixtures_df[
    is_fin &
    (fixtures_df['team_h_score'].notna()) &
    (fixtures_df['team_a_score'].notna())
].copy()

xg_by_team = df_p.groupby('team_id')['xG'].sum().to_dict()
gkp_df = elements_df[(elements_df['element_type'] == 1) & (safe_num_col(elements_df, 'minutes', 0) > 0)].copy()
gkp_df['xgc_f'] = safe_num_col(gkp_df, 'expected_goals_conceded', 0.0)
gkp_df['min_f'] = safe_num_col(gkp_df, 'minutes', 0.0)
gkp_agg = gkp_df.groupby('team').agg({'xgc_f': 'sum', 'min_f': 'sum'})
gkp_xgc90_map = np.where(gkp_agg['min_f'] > 0, (gkp_agg['xgc_f'] / gkp_agg['min_f']) * 90.0, 1.4)
team_id_to_xga90 = dict(zip(gkp_agg.index, gkp_xgc90_map))

clubs_rows = []
matched_ppda = 0
for _, t_row in teams_df.iterrows():
    tid = int(t_row['id'])
    tname = str(t_row['name']).strip()
    skrot = str(t_row['short_name']).strip()

    h_m = finished_fix[finished_fix['team_h'] == tid]
    a_m = finished_fix[finished_fix['team_a'] == tid]

    m_cnt = len(h_m) + len(a_m)
    m_safe = max(m_cnt, 1)
    wins = int((h_m['team_h_score'] > h_m['team_a_score']).sum() + (a_m['team_a_score'] > a_m['team_h_score']).sum())
    draws = int((h_m['team_h_score'] == h_m['team_a_score']).sum() + (a_m['team_a_score'] == a_m['team_h_score']).sum())
    loses = m_cnt - wins - draws
    goals = int(h_m['team_h_score'].sum() + a_m['team_a_score'].sum()) if m_cnt > 0 else 0
    ga = int(h_m['team_a_score'].sum() + a_m['team_h_score'].sum()) if m_cnt > 0 else 0
    pts = wins * 3 + draws

    xg_tot = float(xg_by_team.get(tid, 0.0))
    npxg_tot = xg_tot
    xga_tot = float(team_id_to_xga90.get(tid, 1.4)) * m_safe
    npxga_tot = xga_tot

    if skrot in ppda_baza:
        ppda_val = float(ppda_baza[skrot]['PPDA'])
        oppda_val = float(ppda_baza[skrot]['OPPDA'])
        matched_ppda += 1
    else:
        ppda_val, oppda_val = 11.0, 11.0

    clubs_rows.append({
        'team': tname, 'Skrót': skrot, 'matches': m_cnt,
        'wins': wins, 'draws': draws, 'loses': loses,
        'goals': goals, 'ga': ga, 'points': pts,
        'xG': xg_tot, 'NPxG': npxg_tot, 'xGA': xga_tot, 'NPxGA': npxga_tot,
        'PPDA': ppda_val, 'OPPDA': oppda_val, '_gd': goals - ga
    })

print(f"Dopasowano bazę PPDA/OPPDA dla {matched_ppda}/{len(clubs_rows)} klubów.")

df_clubs = pd.DataFrame(clubs_rows).sort_values(
    by=['points', '_gd', 'goals'], ascending=[False, False, False]
).reset_index(drop=True)

m_denom = df_clubs['matches'].replace(0, 1).astype(float)
med_npxgc90 = float(np.median(df_clubs['NPxGA'] / m_denom))
med_xg90 = float(np.median(df_clubs['xG'] / m_denom))
med_ppda = float(np.median(df_clubs['PPDA']))

def calc_takt_xgc90(r):
    m_s = max(float(r['matches']), 1.0)
    xgc_m = r['xGA'] / m_s
    ppda = r['PPDA']
    if ppda < 11 and xgc_m < 1.2: mod = 0.85
    elif ppda < 11 and xgc_m >= 1.2: mod = 1.2
    elif ppda > 14 and xgc_m < 1.2: mod = 0.9
    elif ppda > 14 and xgc_m >= 1.2: mod = 1.05
    else: mod = 1.0
    return xgc_m * mod

df_clubs['Taktyczne xGC90'] = df_clubs.apply(calc_takt_xgc90, axis=1)
df_clubs['xGD'] = (df_clubs['NPxG'] - df_clubs['NPxGA']) / m_denom

def calc_fdr_overall(r):
    xga_m = r['NPxGA'] / max(float(r['matches']), 1.0)
    if r['PPDA'] < med_ppda and xga_m <= med_npxgc90:
        mod_ppda = 0.15
    elif r['PPDA'] > 15 and xga_m > med_npxgc90:
        mod_ppda = -0.15
    else:
        mod_ppda = 0.0
    sila = r['xGD'] + mod_ppda
    if sila >= med_npxgc90 * 0.8: return 5
    elif sila >= med_npxgc90 * 0.4: return 4
    elif sila >= 0: return 3
    elif sila >= -(med_npxgc90 * 0.5): return 2
    else: return 1

def calc_fdr_atk(r):
    v = r['NPxGA'] / max(float(r['matches']), 1.0)
    if v < 1.1: return 5
    elif v < 1.35: return 4
    elif v < 1.6: return 3
    elif v < 1.85: return 2
    else: return 1

def calc_fdr_def(r):
    v = r['NPxG'] / max(float(r['matches']), 1.0)
    if v > 1.9: return 5
    elif v > 1.6: return 4
    elif v > 1.3: return 3
    elif v > 1.0: return 2
    else: return 1

df_clubs['FDR'] = df_clubs.apply(calc_fdr_overall, axis=1)
df_clubs['FDR_Atak'] = df_clubs.apply(calc_fdr_atk, axis=1)
df_clubs['FDR_Obrona'] = df_clubs.apply(calc_fdr_def, axis=1)

short_to_overall = dict(zip(df_clubs['Skrót'], df_clubs['FDR']))
short_to_atk = dict(zip(df_clubs['Skrót'], df_clubs['FDR_Atak']))
short_to_def = dict(zip(df_clubs['Skrót'], df_clubs['FDR_Obrona']))
short_to_xga = dict(zip(df_clubs['Skrót'], df_clubs['xGA']))
short_to_npxga = dict(zip(df_clubs['Skrót'], df_clubs['NPxGA']))
short_to_xg = dict(zip(df_clubs['Skrót'], df_clubs['xG']))
short_to_matches = dict(zip(df_clubs['Skrót'], df_clubs['matches'].replace(0, 1)))
short_to_ppda = dict(zip(df_clubs['Skrót'], df_clubs['PPDA']))
team_to_xga = dict(zip(df_clubs['team'], df_clubs['xGA']))
team_to_npxg = dict(zip(df_clubs['team'], df_clubs['NPxG']))
team_to_matches = dict(zip(df_clubs['team'], df_clubs['matches'].replace(0, 1)))
team_to_overall = dict(zip(df_clubs['team'], df_clubs['FDR']))
team_to_atk = dict(zip(df_clubs['team'], df_clubs['FDR_Atak']))
team_to_def = dict(zip(df_clubs['team'], df_clubs['FDR_Obrona']))
max_matches = max(float(df_clubs['matches'].max()), 1.0)
l5_denom = max(float(len(l5_gws)), 1.0)

# ==============================================================================
# 3. MACIERZ FDR & TABELA CHIPÓW
# ==============================================================================
gw_meta = []
for _, ev in events_df.sort_values('id').iterrows():
    gw_i = int(ev['id'])
    if gw_i < 1 or gw_i > 38:
        continue
    dl = str(ev.get('deadline_time', '') or '')
    dt_iso = dl[:10] if len(dl) >= 10 else ''
    dt_short = f"{dt_iso[8:10]}.{dt_iso[5:7]}" if len(dt_iso) == 10 else ''
    gw_meta.append({'gw': gw_i, 'label': f"GW{gw_i}", 'date': dt_iso, 'short_date': dt_short})

rolling_gws = [next_gw_num + i for i in range(6) if next_gw_num + i <= 38]
planer_gws = [next_gw_num + i for i in range(12) if next_gw_num + i <= 38]

sched_fix = fixtures_df[fixtures_df['event'].notna()].copy()
sched_fix['event'] = sched_fix['event'].astype(int)

fdr_matrix = []
team_fixtures = {}
team_fixtures_short = {}
chip_matrix = []
chip_scores_by_gw = {gw: [] for gw in range(1, 39)}

for _, t_row in teams_df.sort_values('name').iterrows():
    tid = int(t_row['id'])
    tname = str(t_row['name']).strip()
    tshort = str(t_row['short_name']).strip()

    row_fdr = {
        'Klub': tname,
        'FDR_Overall': int(team_to_overall.get(tname, 3)),
        'FDR_Atak': int(team_to_atk.get(tname, 3)),
        'FDR_Obrona': int(team_to_def.get(tname, 3)),
        'fixtures': []
    }
    row_chip = {'Klub': tname, 'scores': []}
    team_fixtures[tname] = {}
    team_fixtures_short[tshort] = {}

    t_npxg_90 = team_to_npxg.get(tname, 0.0) / team_to_matches.get(tname, 1.0)

    for gw_i in range(1, 39):
        m = sched_fix[(sched_fix['event'] == gw_i) & ((sched_fix['team_h'] == tid) | (sched_fix['team_a'] == tid))]
        if m.empty:
            cell_obj = {'text': 'BLANK', 'opp': '', 'ha': '', 'fdr_overall': 0, 'fdr_atk': 0, 'fdr_def': 0, 'matches': []}
            c_score = 0.0
        else:
            parts, ov_l, atk_l, def_l, m_details = [], [], [], [], []
            c_score = 0.0
            for _, mr in m.iterrows():
                if int(mr['team_h']) == tid:
                    opp = id_to_short[int(mr['team_a'])]
                    ha = "H"
                else:
                    opp = id_to_short[int(mr['team_h'])]
                    ha = "A"
                away_add = 1 if ha == "A" else 0
                f_ov = min(5, short_to_overall.get(opp, 3) + away_add)
                f_atk = min(5, short_to_atk.get(opp, 3) + away_add)
                f_def = min(5, short_to_def.get(opp, 3) + away_add)
                parts.append(f"{opp}-{ha}")
                ov_l.append(f_ov); atk_l.append(f_atk); def_l.append(f_def)
                m_details.append((opp, ha))

                opp_npxga_90 = short_to_npxga.get(opp, 0.0) / short_to_matches.get(opp, 1.0)
                c_score += t_npxg_90 * opp_npxga_90 * (1.15 if ha == "H" else 0.85) / 1.5

            cell_obj = {
                'text': " + ".join(parts),
                'opp': m_details[0][0],
                'ha': m_details[0][1],
                'fdr_overall': int(round(np.mean(ov_l))),
                'fdr_atk': int(round(np.mean(atk_l))),
                'fdr_def': int(round(np.mean(def_l))),
                'matches': m_details
            }

        slim = {k: cell_obj[k] for k in ['text', 'opp', 'ha', 'fdr_overall', 'fdr_atk', 'fdr_def']}
        row_fdr['fixtures'].append(slim)
        team_fixtures[tname][gw_i] = cell_obj
        team_fixtures_short[tshort][str(gw_i)] = slim
        row_chip['scores'].append(round(c_score, 2))
        chip_scores_by_gw[gw_i].append((tname, cell_obj['text'], c_score))

    fdr_matrix.append(row_fdr)
    chip_matrix.append(row_chip)
# ==============================================================================
# 4. SILNIK EXPECTED POINTS (xPts — 8 SKŁADNIKÓW) + KOKPIT + PLANER 12GW
# ==============================================================================
print("4/5 Przeliczanie silnika xPts (8 składników), Kokpitu i Skanera...")

def poisson_tail(k_min, lam):
    if lam <= 0.0:
        return 0.0
    cdf = 0.0
    term = math.exp(-lam)
    for k in range(k_min):
        if k > 0:
            term *= lam / k
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))

def expected_gc_moments(lam):
    if lam <= 0.0:
        return 0.0, 0.0
    e1, e2 = 0.0, 0.0
    term = math.exp(-lam)
    for k in range(1, 16):
        term *= lam / k
        if k >= 2:
            pen = k // 2
            e1 += pen * term
            e2 += (pen * pen) * term
    return e1, e2

def expected_saves_moments(lam):
    if lam <= 0.0:
        return 0.0, 0.0
    e1, e2 = 0.0, 0.0
    term = math.exp(-lam)
    for k in range(1, 24):
        term *= lam / k
        if k >= 3:
            pts = k // 3
            e1 += pts * term
            e2 += (pts * pts) * term
    return e1, e2

def mins_to_probs(xm):
    if xm <= 0.5:
        return 0.0, 0.0
    p_play = min(0.99, xm / 20.0) if xm < 20.0 else min(0.99, 0.85 + 0.14 * min(1.0, (xm - 20.0) / 55.0))
    p_60 = 1.0 / (1.0 + math.exp(-(xm - 56.0) / 8.5))
    if xm < 15.0:
        p_60 *= (xm / 15.0)
    p_60 = min(p_play, max(0.0, p_60))
    return p_play, p_60

# Średnie pozycyjne (priory do stabilizacji graczy z małą próbką minut)
default_priors = {
    'GKP': {'xg': 0.00, 'xa': 0.01, 'dc': 0.0, 'sv': 3.0, 'bon': 0.30, 'yc': 0.05, 'rc': 0.005},
    'DEF': {'xg': 0.06, 'xa': 0.07, 'dc': 7.5, 'sv': 0.0, 'bon': 0.25, 'yc': 0.18, 'rc': 0.010},
    'MID': {'xg': 0.22, 'xa': 0.16, 'dc': 6.5, 'sv': 0.0, 'bon': 0.28, 'yc': 0.18, 'rc': 0.008},
    'FWD': {'xg': 0.42, 'xa': 0.12, 'dc': 3.5, 'sv': 0.0, 'bon': 0.35, 'yc': 0.12, 'rc': 0.008},
}
pos_priors = {}
for pz in ['GKP', 'DEF', 'MID', 'FWD']:
    sub = df_p[(df_p['Pozycja'] == pz) & (df_p['min'] >= 270)]
    if len(sub) >= 5:
        m90 = sub['min'].sum() / 90.0
        pos_priors[pz] = {
            'xg': float(sub['xG'].sum() / m90),
            'xa': float(sub['xA'].sum() / m90),
            'dc': float(sub['DefCon'].sum() / m90),
            'sv': float(sub['Obrony'].sum() / m90),
            'bon': float(sub['Bonus'].sum() / m90),
            'yc': float(sub['ZK'].sum() / m90),
            'rc': float(sub['CzK'].sum() / m90),
        }
    else:
        pos_priors[pz] = default_priors[pz]

PRIOR_ATK = 270.0
PRIOR_DC = 270.0
PRIOR_BON = 360.0
PRIOR_CRD = 450.0
GOAL_PTS = {'GKP': 6.0, 'DEF': 6.0, 'MID': 5.0, 'FWD': 4.0}

scenariusz_map = {
    "MM": ("🚧 Elitarny Pressing (Ciężko o punkty, mało miejsca)", 0.85, 0.90),
    "MD": ("🎁 Samobójczy Pressing (Dziurawi. Autostrada na kontry!)", 1.25, 1.15),
    "DM": ("🧱 Elitarny Autobus (Szczelni. Bicie głową w mur)", 0.80, 0.88),
    "DD": ("🎪 Chłopcy do bicia (Słaby blok. Trening strzelecki)", 1.20, 1.12),
}

def calc_match_xpts(poz, x_mins_base, avail, xg90_eff, xa90_eff, defcon90_eff, saves90_eff,
                    bonus90_eff, yc90_eff, rc90_eff, xgc90_team, opp, ha, xpts_boost=1.0):
    if x_mins_base <= 0.1 or avail <= 0.0 or not opp:
        return [0.0] * 9, 0.0, 0.0, 0.0, 0.0

    p_play_raw, p_60_raw = mins_to_probs(x_mins_base)
    p_play = p_play_raw * avail
    p_60 = p_60_raw * avail
    mf_play = x_mins_base / 90.0
    mf = mf_play * avail

    # 1. Występ (1 pkt za grę + 1 pkt za >=60 min)
    pts_app = p_play + p_60

    # Parametry rywala (bez podwójnego liczenia xGA przez booster)
    opp_xga90 = short_to_xga.get(opp, med_npxgc90) / short_to_matches.get(opp, 1.0)
    opp_xg90 = short_to_xg.get(opp, med_xg90) / short_to_matches.get(opp, 1.0)
    opp_xga_ha = opp_xga90 * (1.15 if ha == "H" else 0.85)
    atk_mult = max(0.45, min(1.80, opp_xga_ha / max(med_npxgc90, 0.5)))

    # 2. Gole i 3. Asysty
    exp_g_cond = xg90_eff * mf_play * atk_mult
    exp_a_cond = xa90_eff * mf_play * atk_mult
    exp_g = exp_g_cond * avail
    exp_a = exp_a_cond * avail
    w_g = GOAL_PTS.get(poz, 4.0)
    pts_g = exp_g * w_g
    pts_a = exp_a * 3.0

    # 4. Czyste konto (iloczynowy model Poissona) i 5. Kara za stracone gole (-1 za każde 2)
    ha_def = 0.85 if ha == "H" else 1.15
    lam_gc = max(0.25, ((xgc90_team * opp_xg90) / max(med_xg90, 0.5)) * ha_def)
    cs_prob = math.exp(-lam_gc)
    cs_val = 4.0 if poz in ('GKP', 'DEF') else (1.0 if poz == 'MID' else 0.0)
    pts_cs = cs_prob * p_60 * cs_val
    gc_e1, gc_e2 = expected_gc_moments(lam_gc * mf_play) if poz in ('GKP', 'DEF') else (0.0, 0.0)
    pts_gc = -gc_e1 * avail

    # 6. DefCon (warunkowo przy pełnym występie mf_play, a dopiero wynik * avail)
    if poz in ('DEF', 'MID', 'FWD'):
        def_work_mult = max(0.85, min(1.15, ((opp_xg90 / max(med_xg90, 0.5)) ** 0.5) * (0.95 if ha == "H" else 1.05)))
        lam_dc = defcon90_eff * mf_play * def_work_mult
        p_dc = poisson_tail(10 if poz == 'DEF' else 12, lam_dc)
        pts_dc = p_dc * 2.0 * avail
    else:
        p_dc, pts_dc = 0.0, 0.0

    # 7. Obrony bramkarza (warunkowo przy pełnym występie mf_play, a dopiero wynik * avail)
    if poz == 'GKP':
        save_mult = max(0.75, min(1.35, (opp_xg90 / max(med_xg90, 0.5)) * (0.92 if ha == "H" else 1.08)))
        sv_e1, sv_e2 = expected_saves_moments(saves90_eff * mf_play * save_mult)
        pts_sv = sv_e1 * avail
    else:
        sv_e1, sv_e2, pts_sv = 0.0, 0.0, 0.0

    # 8. Bonus (hybryda: dorobek w meczu + historyczny magnes na bonusy) i Kartki
    match_bon = (
        exp_g * 0.85 + exp_a * 0.45 +
        (cs_prob * p_60 * 0.45 if poz in ('GKP', 'DEF') else 0.0) +
        pts_sv * 0.25 + pts_dc * 0.12
    )
    pts_bon = min(2.2 * avail, 0.55 * match_bon + 0.45 * (bonus90_eff * mf))
    pts_crd = -(yc90_eff * 1.0 + rc90_eff * 3.0) * mf

    brk = [pts_app, pts_g, pts_a, pts_cs, pts_gc, pts_dc, pts_sv, pts_bon, pts_crd]
    mean_cond = sum(brk) / avail

    # Wariancja meczu (warunkowa przy występie + prawo całkowitej wariancji dla avail)
    var_app = max(0.0, (p_play_raw + 3.0 * p_60_raw) - (p_play_raw + p_60_raw) ** 2)
    var_g = ((w_g + 0.75) ** 2) * exp_g_cond
    var_a = ((3.0 + 0.40) ** 2) * exp_a_cond
    p_cs_eff = cs_prob * p_60_raw
    cs_pay = cs_val + (0.45 if poz in ('GKP', 'DEF') else 0.0)
    var_cs = (cs_pay ** 2) * p_cs_eff * (1.0 - p_cs_eff)
    var_gc = max(0.0, gc_e2 - gc_e1 * gc_e1)
    var_def_shared = var_cs + var_gc + 2.0 * (cs_pay * p_cs_eff) * gc_e1
    var_dc = 4.0 * p_dc * (1.0 - p_dc)
    var_sv = max(0.0, sv_e2 - sv_e1 * sv_e1)
    bon_cond = pts_bon / avail
    var_bon_resid = max(0.0, 0.55 * bon_cond * (2.2 - bon_cond))
    var_crd = (yc90_eff * 1.0 + rc90_eff * 9.0) * mf_play

    var_cond = var_app + var_g + var_a + var_def_shared + var_dc + var_sv + var_bon_resid + var_crd
    var_tot = avail * var_cond + avail * (1.0 - avail) * (mean_cond ** 2)
    cs_sd = math.sqrt(max(0.0, var_def_shared)) * avail if poz in ('GKP', 'DEF', 'MID') else 0.0

    return brk, cs_prob, opp_xga_ha, var_tot, cs_sd

def get_scenario_for_opp(opp):
    if not opp:
        return "", "Brak danych", 1.0, 1.0
    ppda_o = short_to_ppda.get(opp, 0.0)
    xga90_o = short_to_xga.get(opp, 0.0) / short_to_matches.get(opp, 1.0)
    szyfr = ("D" if ppda_o > med_ppda else "M") + ("D" if xga90_o > med_npxgc90 else "M")
    desc, old_b, xpts_b = scenariusz_map.get(szyfr, ("Brak danych", 1.0, 1.0))
    return szyfr, desc, old_b, xpts_b

gw_date_map = {g['gw']: g['date'] for g in gw_meta}

def parse_return_date(news_str, ref_date_iso):
    if not news_str:
        return None
    low = news_str.lower()
    if "unknown return date" in low:
        return "UNKNOWN"
    m = re.search(r'(?:expected back|until)\s+(\d{1,2})\s+([a-z]{3})', low)
    if not m:
        return None
    mon_map = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    mon = mon_map.get(m.group(2))
    if not mon:
        return None
    try:
        ref_dt = datetime.strptime(ref_date_iso[:10], "%Y-%m-%d")
        yr = ref_dt.year
        if ref_dt.month >= 8 and mon <= 6:
            yr += 1
        elif ref_dt.month <= 6 and mon >= 8:
            yr -= 1
        return datetime(yr, mon, int(m.group(1))).strftime("%Y-%m-%d")
    except Exception:
        return None

def calc_gw_avail(status_p, chance_p, ret_date, gw_num):
    if status_p == 'u':
        return 0.0
    if gw_num == next_gw_num:
        return chance_p / 100.0
    gw_dt = gw_date_map.get(gw_num, '')
    if status_p == 's':
        if ret_date and ret_date != "UNKNOWN" and gw_dt and gw_dt < ret_date:
            return 0.0
        return 1.0
    if status_p in ('i', 'n') and chance_p == 0:
        if ret_date == "UNKNOWN":
            return 0.0
        if ret_date and gw_dt and gw_dt < ret_date:
            return 0.0
    return 1.0

kokpit_rows = []
planer_xpts_map = {}

for _, p in df_p.iterrows():
    zaw = p['player']
    klub = p['team']
    poz = p['Pozycja']
    if poz not in pos_priors:
        continue

    minuty = float(p['min'])
    min_l5 = float(p['min_l5'])
    played_l5 = int(p['played_l5'])
    last_min = int(p['last_min'])
    apps_p = int(p['apps'])
    club_m = max(float(team_to_matches.get(klub, 1.0)), 1.0)
    sr_min = min(90.0, minuty / club_m)
    sr_min_l5 = min(90.0, min_l5 / l5_denom) if l5_gws else sr_min

    status_p = str(p['status'])
    chance_p = int(p['chance'])
    news_p = str(p['news'])
    ret_date = parse_return_date(news_p, updated_at[:10])

    # Oczekiwane bazowe minuty: zdrowy starter wracający po pauzie nie traci za zera w L5
    if status_p == 'u':
        x_mins_base = 0.0
    elif not l5_gws:
        x_mins_base = sr_min
    elif chance_p >= 75 and last_min >= 60 and played_l5 > 0:
        sr_played_l5 = min(90.0, min_l5 / float(played_l5))
        sr_starts = min(90.0, minuty / max(float(apps_p), 1.0)) if apps_p > 0 else sr_played_l5
        base_active = 0.35 * sr_starts + 0.65 * sr_played_l5
        trust = min(1.0, max(float(apps_p), float(played_l5)) / 3.0)
        x_mins_base = min(90.0, max(0.0, trust * base_active + (1.0 - trust) * (0.40 * sr_min + 0.60 * sr_min_l5)))
    elif chance_p == 100 and last_min == 0 and played_l5 >= 2 and apps_p >= max(3, int(club_m * 0.6)):
        sr_starts = min(90.0, minuty / max(float(apps_p), 1.0))
        x_mins_base = min(90.0, max(0.0, 0.55 * sr_starts + 0.45 * (0.40 * sr_min + 0.60 * sr_min_l5)))
    else:
        x_mins_base = min(90.0, max(0.0, 0.40 * sr_min + 0.60 * sr_min_l5))

    # Stabilizowane wskaźniki (shrinkage na sezonie oraz na L5)
    pr = pos_priors[poz]
    xg90_stab = (float(p['xG']) + pr['xg'] * (PRIOR_ATK / 90.0)) / ((minuty + PRIOR_ATK) / 90.0)
    xa90_stab = (float(p['xA']) + pr['xa'] * (PRIOR_ATK / 90.0)) / ((minuty + PRIOR_ATK) / 90.0)
    xg_l5 = float(p['xg_l5'])
    xa_l5 = float(p['xa_l5'])
    if l5_gws and min_l5 > 0:
        xg90_l5_stab = (xg_l5 + xg90_stab * (180.0 / 90.0)) / ((min_l5 + 180.0) / 90.0)
        xa90_l5_stab = (xa_l5 + xa90_stab * (180.0 / 90.0)) / ((min_l5 + 180.0) / 90.0)
        w_l5 = 0.25 * min(1.0, min_l5 / 270.0)
        xg90_eff = (1.0 - w_l5) * xg90_stab + w_l5 * xg90_l5_stab
        xa90_eff = (1.0 - w_l5) * xa90_stab + w_l5 * xa90_l5_stab
    else:
        xg90_eff, xa90_eff = xg90_stab, xa90_stab

    defcon90_eff = (float(p['DefCon']) + pr['dc'] * (PRIOR_DC / 90.0)) / ((minuty + PRIOR_DC) / 90.0)
    saves90_eff = (float(p['Obrony']) + pr['sv'] * (PRIOR_DC / 90.0)) / ((minuty + PRIOR_DC) / 90.0)
    bonus90_eff = (float(p['Bonus']) + pr['bon'] * (PRIOR_BON / 90.0)) / ((minuty + PRIOR_BON) / 90.0)
    yc90_eff = (float(p['ZK']) + pr['yc'] * (PRIOR_CRD / 90.0)) / ((minuty + PRIOR_CRD) / 90.0)
    rc90_eff = (float(p['CzK']) + pr['rc'] * (PRIOR_CRD / 90.0)) / ((minuty + PRIOR_CRD) / 90.0)

    xgc90_team = team_to_xga.get(klub, med_npxgc90) / club_m

    # Oblicz prognozę xPts dla wszystkich 12 kolejek Planera (z datami powrotu po kontuzjach)
    gw_xpts_dict = {}
    gw_details = {}
    for gw_num in planer_gws:
        fx = team_fixtures.get(klub, {}).get(gw_num, {'text': '', 'opp': '', 'ha': '', 'fdr_atk': 0, 'fdr_def': 0, 'matches': []})
        avail = calc_gw_avail(status_p, chance_p, ret_date, gw_num)

        tot_brk = [0.0] * 9
        tot_var = 0.0
        tot_cs_var = 0.0
        cs_list = []
        xgc_sum = 0.0
        if fx['matches']:
            for o, h in fx['matches']:
                m_brk, m_cs, m_xgc, m_var, m_cs_sd = calc_match_xpts(
                    poz, x_mins_base, avail, xg90_eff, xa90_eff, defcon90_eff, saves90_eff,
                    bonus90_eff, yc90_eff, rc90_eff, xgc90_team, o, h
                )
                for k_i in range(9):
                    tot_brk[k_i] += m_brk[k_i]
                tot_var += m_var
                tot_cs_var += m_cs_sd * m_cs_sd
                cs_list.append(m_cs)
                xgc_sum += m_xgc

        gw_tot = sum(tot_brk)
        cs_gw = (1.0 - float(np.prod([1.0 - c for c in cs_list]))) if cs_list else 0.0
        brk_round = [round(v, 2) for v in tot_brk]
        gw_sd = round(math.sqrt(max(0.0, tot_var)), 2)
        gw_cs_sd = round(math.sqrt(max(0.0, tot_cs_var)), 2)
        gw_xpts_dict[str(gw_num)] = {'t': round(gw_tot, 2), 'b': brk_round, 'v': round(tot_var, 2), 'cv': gw_cs_sd}
        gw_details[gw_num] = {
            'fx': fx, 'tot': gw_tot, 'brk': brk_round, 'cs': cs_gw, 'xgc': xgc_sum, 'sd': gw_sd
        }
        }

    xpts_6gw_sum = sum(gw_details[g]['tot'] for g in rolling_gws if g in gw_details)
    planer_xpts_map[zaw] = {
        'x6': round(xpts_6gw_sum, 2),
        'xm': int(round(x_mins_base)),
        'gws': gw_xpts_dict
    }

    # Filtr wejściowy do Kokpitu (>=50 min średnio w sezonie, w L5 LUB powrót >=60 min w ostatniej kolejce)
    if minuty <= 0 or (sr_min < 50.0 and sr_min_l5 < 50.0 and last_min < 60):
        continue

    posiadanie = float(p['Posiadanie'])
    cena = float(p['Cena'])
    xgi90 = ((float(p['NPxG']) + float(p['xA'])) / minuty * 90.0) if minuty > 0 else 0.0
    xgi90_l5 = ((xg_l5 + xa_l5) / min_l5 * 90.0) if min_l5 > 0 else 0.0

    if not l5_gws or min_l5 < 90.0:
        trend_code, trend_icon = "LOW_MIN", "⏸️"
    elif xgi90 > 0:
        if xgi90_l5 >= xgi90 * 1.20 and (xgi90_l5 - xgi90) >= 0.05:
            trend_code, trend_icon = "UP", "📈"
        elif xgi90_l5 <= xgi90 * 0.80 and (xgi90 - xgi90_l5) >= 0.05:
            trend_code, trend_icon = "DOWN", "📉"
        else:
            trend_code, trend_icon = "STABLE", "➡️"
    else:
        trend_code, trend_icon = ("UP", "📈") if xgi90_l5 >= 0.10 else ("STABLE", "➡️")

    if poz == "FWD": w1 = "🔥 Elita" if xgi90 >= 0.6 else ("✅ Grywalny" if xgi90 >= 0.4 else "❌ Odrzuć")
    elif poz == "MID": w1 = "🔥 Elita" if xgi90 >= 0.5 else ("✅ Grywalny" if xgi90 >= 0.3 else "❌ Odrzuć")
    elif poz == "DEF": w1 = "🔥 Elita" if xgi90 >= 0.25 else ("✅ Grywalny" if xgi90 >= 0.1 else "❌ Odrzuć")
    else: w1 = "🧤 Bramkarz"

    ocena_obr = "Brak Danych" if xgc90_team == 0 else ("🛡️ Mur (xGC < 1.30)" if xgc90_team <= 1.3 else "⚠️ Dziurawi")

    if poz in ["DEF", "GKP"]: w2 = "✅ Solidny Tył" if xgc90_team <= 1.3 else "❌ Dziurawa obrona"
    elif poz in ["MID", "FWD"]: w2 = "🔥 Elita!" if xgi90 >= 0.5 else ("✅ Grywalny" if xgi90 >= 0.35 else "❌ Za słabe xGI")
    else: w2 = "❓ Zła pozycja"

    status_eo = "🗡️ Super Diff (Miecz)" if posiadanie < 0.10 else "🛡️ Szablon (Tarcza)"

    m_list = []
    xpts_6_list = []
    for gw_num in rolling_gws:
        gd = gw_details[gw_num]
        fx = gd['fx']
        fdr_pos = (fx['fdr_atk'] if poz in ["MID", "FWD"] else fx['fdr_def']) if fx['matches'] else 0
        m_list.append({
            'text': fx['text'], 'opp': fx['opp'], 'ha': fx['ha'],
            'xgc': round(gd['xgc'], 2), 'fdr': fdr_pos, 'xp': round(gd['tot'], 2)
        })
        xpts_6_list.append({'gw': f"GW{gw_num}", 'xp': round(gd['tot'], 2), 'fx': fx['text'] or 'BLANK'})

    while len(m_list) < 6:
        m_list.append({'text': '', 'opp': '', 'ha': '', 'xgc': 0.0, 'fdr': 0, 'xp': 0.0})

    opp1 = m_list[0]['opp']
    szyfr, scenariusz, _, xpts_boost1 = get_scenario_for_opp(opp1)

    gd1 = gw_details.get(rolling_gws[0], {'tot': 0.0, 'brk': [0.0]*9, 'cs': 0.0}) if rolling_gws else {'tot': 0.0, 'brk': [0.0]*9, 'cs': 0.0}
    brk1 = gd1['brk']
    xpts_gw1 = round(gd1['tot'], 2)
    szansa_cs = gd1['cs']

    if l5_gws and sr_min >= 50.0 and sr_min_l5 < 35.0:
        status_min = "⚠️ Spadek minut (L5)"
    elif sr_min >= 70.0 or sr_min_l5 >= 70.0:
        status_min = "🟢 Pewniak (>70m)"
    else:
        status_min = "🟡 Rotacja (50-70m)"

    kokpit_rows.append({
        'Zawodnik': zaw, 'Klub': klub, 'Cena': round(cena, 1), 'Minuty': int(minuty),
        'xMins': int(round(x_mins_base)),
        'xGI90': round(xgi90, 2),
        'DefCon90': round(float(p['DefCon90']), 1),
        'Min_L5': int(min_l5), 'xG_L5': round(xg_l5, 2), 'xGI90_L5': round(xgi90_l5, 2),
        'Trend_Code': trend_code, 'Trend_Icon': trend_icon,
        'xGC90_Team': round(xgc90_team, 2), 'Werdykt1': w1,
        'Ocena_Obrony': ocena_obr, 'Szansa_CS': round(szansa_cs * 100, 1),
        'xPts_GW': xpts_gw1, 'xPts_GW_Brk': brk1, 'xPts_GW_SD': round(gd1.get('sd', 0.0), 2),
        'xPts_Atk1': round(brk1[1] + brk1[2], 2),
        'xPts_Def1': round(brk1[3] + brk1[4] + brk1[6], 2),
        'xPts_DC1': round(brk1[5], 2),
        'xPts_Bon1': round(brk1[7] + brk1[8], 2),
        'Pozycja': poz, 'Posiadanie': round(posiadanie * 100, 1), 'Werdykt2': w2, 'Status_EO': status_eo,
        'm1': m_list[0], 'm2': m_list[1], 'm3': m_list[2], 'm4': m_list[3], 'm5': m_list[4], 'm6': m_list[5],
        'xPts_6GW': round(xpts_6gw_sum, 2), 'xPts_6_List': xpts_6_list,
        'xPts_Val': round(xpts_6gw_sum / max(cena, 3.5), 2),
        'Radar': '', 'Status_Min': status_min,
        'Szyfr': szyfr, 'Scenariusz': scenariusz, 'Booster': xpts_boost1,
        'status': status_p, 'chance': chance_p, 'news': news_p,
        'is_pen': int(p['is_pen']), 'is_setp': int(p['is_setp'])
    })

# Dynamiczna kalibracja progów Radaru osobno dla każdej pozycji (top 20% = Priorytet, środek = Dobra, dół 35% = Pozbądź się)
radar_floors = {
    'GKP': (20.0, 16.0), 'DEF': (22.0, 17.0), 'MID': (26.0, 19.0), 'FWD': (26.0, 19.0)
}
radar_cuts = {}
for pz in ['GKP', 'DEF', 'MID', 'FWD']:
    vals = [r['xPts_6GW'] for r in kokpit_rows if r['Pozycja'] == pz and r['xPts_6GW'] > 0]
    f_hi, f_lo = radar_floors[pz]
    if len(vals) >= 6:
        p80 = max(f_hi, float(np.percentile(vals, 80)))
        p35 = max(f_lo, float(np.percentile(vals, 35)))
    else:
        p80, p35 = f_hi, f_lo
    radar_cuts[pz] = (round(p80, 1), round(p35, 1))

for r in kokpit_rows:
    v6 = r['xPts_6GW']
    hi_cut, lo_cut = radar_cuts.get(r['Pozycja'], (25.0, 18.0))
    if v6 <= 0:
        r['Radar'] = "Brak Danych"
    elif v6 >= hi_cut:
        r['Radar'] = "🛒 Priorytet Kupna"
    elif v6 >= lo_cut:
        r['Radar'] = "✅ Dobra Opcja"
    else:
        r['Radar'] = "❌ Pozbądź się"

kokpit_rows.sort(key=lambda x: x['xPts_6GW'], reverse=True)

# ==============================================================================
# 5. SKANER WILDCARD I FREE HIT (filtr WC: min. 3/5 kolejek >= MEDIANA)
# ==============================================================================
at_vals, top5_labels = [], []
for gw_i in range(1, 39):
    sorted_clubs = sorted(chip_scores_by_gw[gw_i], key=lambda x: x[2], reverse=True)
    if max_matches < 5:
        at_vals.append(0.0)
        top5_labels.append("—")
    else:
        at_vals.append(float(sum(x[2] for x in sorted_clubs[:5])))
        top5_labels.append(", ".join([f"{x[0]} ({x[1]})" for x in sorted_clubs[:5]]))

avg_at_19 = float(np.mean(at_vals[:19]))
std_at_19 = float(np.std(at_vals[:19], ddof=1))

aw_vals = [0.0 if at_vals[i] == 0 else float(np.mean(at_vals[i:i+5])) for i in range(38)]
avg_aw_37 = float(np.mean(aw_vals[:37]))
std_aw_37 = float(np.std(aw_vals[:37], ddof=1))
med_at_37 = float(np.median(at_vals[:37]))

scanner_rows = []
for i in range(38):
    gw_i = i + 1
    at_v, aw_v = at_vals[i], aw_vals[i]
    window_5 = at_vals[i:i+5]

    if at_v == 0: fh_verdict = "⏳ Trwa zbieranie danych (Odblokowanie po GW5)"
    elif at_v >= (avg_at_19 + std_at_19): fh_verdict = "💣 WYBUCHOWA - Rozważ Free Hit!"
    elif at_v >= avg_at_19: fh_verdict = "✅ Dobry moment na atak"
    else: fh_verdict = "⚠️ Trudna (Giganci grają ze sobą)"

    cnt_good = sum(1 for x in window_5 if x >= med_at_37)
    if aw_v == 0: wc_verdict = "⏳ Trwa zbieranie danych..."
    elif aw_v >= (avg_aw_37 + std_aw_37) and cnt_good >= 3: wc_verdict = "💣 ODPALAJ WILDCARD!"
    elif aw_v >= avg_aw_37 and cnt_good >= 3: wc_verdict = "✅ Długoterminowa autostrada"
    else: wc_verdict = "⚠️ Trudny kalendarz (Nie używaj WC)"

    scanner_rows.append({
        'GW': gw_i, 'Data': gw_meta[i]['date'] if i < len(gw_meta) else '',
        'FH_Score': round(at_v, 2), 'FH_Verdict': fh_verdict,
        'WC_Score': round(aw_v, 2), 'WC_Verdict': wc_verdict,
        'Top5_Kluby': top5_labels[i]
    })

# ==============================================================================
# 6. DOMYŚLNY STAN PLANERA I SERIALIZACJA DANYCH DO JSON
# ==============================================================================
default_planer_squad = [
    {"player": resolve_official_name("Caoimhin Kelleher"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Lukás Hornícek"), "status": "", "outGw": "10"},
    {"player": resolve_official_name("Michael Kayode"), "status": "", "outGw": "12"},
    {"player": resolve_official_name("Riccardo Calafiori"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Maxim De Cuyper"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Leif Davis"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Timothy Castagne"), "status": "", "outGw": "11"},
    {"player": resolve_official_name("Bryan Mbeumo"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Marcus Tavernier"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Cole Palmer"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Pascal Groß"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Jack Rudoni"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Thierno Barry"), "status": "", "outGw": ""},
    {"player": resolve_official_name("Gonzalo García"), "status": "", "outGw": "11"},
    {"player": resolve_official_name("Erling Haaland"), "status": "", "outGw": ""},
]
default_planer_targets = [
    {"player": resolve_official_name("Alexander Isak"), "status": "💎 Premium", "inGw": "11"},
    {"player": resolve_official_name("Djordje Petrovic"), "status": "💎 Premium", "inGw": "10"},
    {"player": resolve_official_name("Jay Dasilva"), "status": "🪵 Słup", "inGw": "11"},
    {"player": resolve_official_name("James Justin"), "status": "♻️ Rotacja", "inGw": "12"},
    {"player": resolve_official_name("Nicolas Jackson"), "status": "🪵 Słup", "inGw": "14"},
]

pl_cols = ['team', 'Skrót', 'matches', 'wins', 'draws', 'loses', 'goals', 'ga', 'points',
           'xG', 'NPxG', 'xGA', 'NPxGA', 'PPDA', 'OPPDA', 'Taktyczne xGC90', 'xGD', 'FDR']
df_pl_out = df_clubs[pl_cols].copy()
for c in ['xG', 'NPxG', 'xGA', 'NPxGA', 'PPDA', 'OPPDA', 'Taktyczne xGC90', 'xGD']:
    df_pl_out[c] = df_pl_out[c].round(2)

players_cols = [
    'player', 'team', 'Pozycja', 'Cena', 'status', 'chance', 'news',
    'apps', 'min', 'G', 'A', 'xG', 'NPxG', 'xA', 'xGChain', 'xG90', 'xA90',
    'DefCon', 'DefCon90', 'Obrony', 'Bonus', 'BPS90', 'ZK', 'Posiadanie'
]
df_players_out = df_players[players_cols].copy()
for c in ['xG', 'NPxG', 'xA', 'xGChain', 'xG90', 'xA90', 'BPS90']:
    df_players_out[c] = df_players_out[c].round(2)
df_players_out['DefCon90'] = df_players_out['DefCon90'].round(1)
df_players_out['Cena'] = df_players_out['Cena'].round(1)

json_pl = df_pl_out.to_json(orient='records')
json_players = df_players_out.to_json(orient='records')
json_catalog = df_all_catalog.to_json(orient='records')
json_fdr = json.dumps(fdr_matrix)
json_team_fix_short = json.dumps(team_fixtures_short)
json_gw_meta = json.dumps(gw_meta)
json_kokpit = json.dumps(kokpit_rows)
json_planer_xpts = json.dumps(planer_xpts_map)
json_radar_cuts = json.dumps(radar_cuts)
json_rolling_gws = json.dumps([f"GW{g}" for g in rolling_gws] + [""] * (6 - len(rolling_gws)))
json_planer_gws = json.dumps(planer_gws)
json_scanner = json.dumps(scanner_rows)
json_chip_matrix = json.dumps(chip_matrix)
json_def_squad = json.dumps(default_planer_squad)
json_def_targets = json.dumps(default_planer_targets)

print("5/5 Budowanie pliku index.html...")
html_app = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FPL Plik</title>
<style>
  :root {{ --excel-green: #107c41; --excel-border: #d4d4d4; --bg-soft: #eef2f0; }}
  * {{ box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
  body {{ margin: 0; padding: 0; background: #f8f9fa; color: #222; display: flex; flex-direction: column; height: 100vh; }}

  .top-bar {{
    background: var(--excel-green); color: white; padding: 10px 18px;
    display: flex; align-items: center; justify-content: space-between; font-weight: 600; font-size: 15px; flex-wrap: wrap; gap: 8px;
  }}
  .top-bar .badge {{ background: rgba(255,255,255,0.18); padding: 4px 10px; border-radius: 4px; font-size: 12px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }}

  .toolbar {{
    background: var(--bg-soft); border-bottom: 1px solid var(--excel-border); padding: 8px 14px;
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 12.5px;
  }}
  .toolbar-group {{ display: flex; align-items: center; gap: 6px; }}
  .toolbar-group label {{ font-weight: 600; color: #333; }}
  .toolbar-group input, .toolbar-group select {{
    padding: 4px 8px; border: 1px solid #bbb; border-radius: 4px; font-size: 12.5px; background: white;
  }}
  .mode-btn, .act-btn {{
    padding: 5px 10px; border: 1px solid #aaa; background: white; border-radius: 4px;
    cursor: pointer; font-size: 12px; font-weight: 600; color: #333;
  }}
  .mode-btn.active, .act-btn.primary {{ background: var(--excel-green); color: white; border-color: var(--excel-green); }}
  .act-btn:hover {{ filter: brightness(0.95); }}
  .act-btn.danger {{ color: #a8071a; border-color: #ffa39e; background: #fff1f0; }}

  .info-icon {{
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; margin-left: 3px; cursor: help;
    color: #107c41; opacity: 0.85; vertical-align: middle; padding: 0 2px;
    transition: opacity 0.12s, transform 0.12s;
  }}
  .info-icon:hover {{ opacity: 1; transform: scale(1.15); }}
  .top-bar .info-icon, .mode-btn.active .info-icon, th.gw-now .info-icon {{ color: #ffffff; opacity: 0.9; }}

  #fplTooltip {{
    display: none; position: fixed; z-index: 20000;
    background: #1e293b; color: #f8fafc; padding: 10px 13px; border-radius: 7px;
    font-size: 12.5px; line-height: 1.48; max-width: 350px; min-width: 200px;
    box-shadow: 0 10px 26px rgba(0,0,0,0.34); border: 1px solid rgba(255,255,255,0.14);
    pointer-events: none; text-align: left; font-weight: 400; white-space: normal;
  }}
  #fplTooltip b {{ color: #86efac; font-weight: 700; }}
  #fplTooltip .tip-title {{ font-weight: 700; color: #ffffff; margin-bottom: 5px; font-size: 13px; border-bottom: 1px solid rgba(255,255,255,0.16); padding-bottom: 3px; }}
  #fplTooltip .tip-muted {{ color: #cbd5e1; font-size: 11.5px; display: block; margin-top: 5px; }}
  .tip-grid {{ display: grid; grid-template-columns: 1fr auto; gap: 2px 14px; font-size: 12px; }}
  .tip-val {{ font-weight: 700; text-align: right; color: #e2e8f0; }}
  .tip-pos {{ color: #86efac; }}
  .tip-neg {{ color: #fca5a5; }}
  .tip-total {{ margin-top: 6px; padding-top: 5px; border-top: 1px solid rgba(255,255,255,0.18); display: flex; justify-content: space-between; font-weight: 700; font-size: 13px; color: #ffffff; }}

  .sheet-container {{ flex: 1; overflow: auto; background: white; }}
  .tab-view {{ display: none; width: 100%; height: 100%; flex-direction: column; }}
  .tab-view.active {{ display: flex; }}
  .table-scroll {{ flex: 1; overflow: auto; }}

  table.excel-table {{ border-collapse: collapse; width: max-content; min-width: 100%; font-size: 12.5px; }}
  table.excel-table th {{
    position: sticky; top: 0; background: #e6e6e6; color: #111; font-weight: 600;
    border: 1px solid #bdbdbd; padding: 6px 8px; text-align: center; cursor: pointer;
    user-select: none; z-index: 3; white-space: nowrap;
  }}
  table.excel-table th:hover {{ background: #d6d6d6; }}
  table.excel-table th.gw-now {{ background: #107c41; color: white; }}
  table.excel-table th.l5-hdr {{ background: #d9ead3; color: #0f5132; border-bottom: 2px solid #107c41; }}
  table.excel-table th.xpts-hdr {{ background: #d6eaf8; color: #0b4a7d; border-bottom: 2px solid #1b6ca8; }}
  table.excel-table td {{ border: 1px solid var(--excel-border); padding: 4px 7px; white-space: nowrap; text-align: right; }}
  table.excel-table td.text-left {{ text-align: left; font-weight: 500; }}
  table.excel-table td.text-center {{ text-align: center; }}
  table.excel-table tr:nth-child(even) td {{ background-color: #fafafa; }}
  table.excel-table tr:hover td {{ background-color: #e8f4ee !important; }}
  table.excel-table td.sticky-col, table.excel-table th.sticky-col {{
    position: sticky; left: 0; z-index: 2; background: #f3f2f1;
  }}
  table.excel-table th.sticky-col {{ z-index: 4; background: #dcdcdc; }}

  .xpts-cell {{
    font-weight: 700; color: #0b4a7d; background-color: #eef6fc !important;
    cursor: help; text-decoration: underline dotted rgba(11,74,125,0.45); text-underline-offset: 2px;
  }}
  .xpts-cell:hover {{ background-color: #d6eaf8 !important; }}
  .dc-hi {{ background-color: #e3f5e8 !important; color: #0f5132 !important; font-weight: 700; }}

  .st-dot {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px;
    vertical-align: middle; cursor: help; flex-shrink: 0;
  }}
  .st-ok {{ background: #16a34a; }}
  .st-75 {{ background: #eab308; box-shadow: 0 0 0 1px #a16207; }}
  .st-50 {{ background: #f97316; box-shadow: 0 0 0 1px #c2410c; }}
  .st-0  {{ background: #dc2626; box-shadow: 0 0 0 1px #991b1b; }}
  .tag-icon {{ margin-left: 3px; font-size: 11.5px; cursor: help; }}
  .btn-mini-in {{
    margin-left: 5px; padding: 0 5px; font-size: 11px; font-weight: 700; line-height: 17px;
    border: 1px solid #107c41; border-radius: 3px; background: #fff; color: #107c41;
    cursor: pointer; vertical-align: middle;
  }}
  .btn-mini-in:hover {{ background: #107c41; color: #fff; }}

  .l5-col {{ background-color: #f4faf5; }}
  .trend-UP {{ background-color: #d4edda !important; color: #0f5132 !important; font-weight: 700; }}
  .trend-DOWN {{ background-color: #f8d7da !important; color: #842029 !important; font-weight: 700; }}
  .trend-STABLE {{ background-color: #f4faf5 !important; color: #222; font-weight: 600; }}
  .trend-LOW_MIN {{ background-color: #fff3cd !important; color: #7a4f00 !important; font-weight: 600; }}
  .min-warn {{ background-color: #fff0c2 !important; color: #7a4f00 !important; font-weight: 700; }}

  .fdr-1 {{ background-color: #00B050 !important; color: #ffffff !important; font-weight: 700; text-align: center !important; }}
  .fdr-2 {{ background-color: #92D050 !important; color: #111111 !important; font-weight: 700; text-align: center !important; }}
  .fdr-3 {{ background-color: #FFFF00 !important; color: #111111 !important; font-weight: 700; text-align: center !important; }}
  .fdr-4 {{ background-color: #FF0000 !important; color: #ffffff !important; font-weight: 700; text-align: center !important; }}
  .fdr-5 {{ background-color: #C00000 !important; color: #ffffff !important; font-weight: 700; text-align: center !important; }}
  .fdr-0 {{ background-color: #eeeeee !important; color: #777777 !important; text-align: center !important; }}

  .xp-tier-5 {{ background-color: #009e49 !important; color: #ffffff !important; font-weight: 700; text-align: center !important; }}
  .xp-tier-4 {{ background-color: #7cc943 !important; color: #111111 !important; font-weight: 700; text-align: center !important; }}
  .xp-tier-3 {{ background-color: #fff066 !important; color: #111111 !important; font-weight: 700; text-align: center !important; }}
  .xp-tier-2 {{ background-color: #f8b4b4 !important; color: #7f1d1d !important; font-weight: 700; text-align: center !important; }}
  .xp-tier-0 {{ background-color: #eeeeee !important; color: #777777 !important; text-align: center !important; }}

  .scen-MD {{ background-color: #d4edda !important; color: #155724 !important; font-weight: 600; text-align: left !important; }}
  .scen-DD {{ background-color: #c3e6cb !important; color: #0f401b !important; font-weight: 600; text-align: left !important; }}
  .scen-MM {{ background-color: #fff3cd !important; color: #856404 !important; font-weight: 600; text-align: left !important; }}
  .scen-DM {{ background-color: #f8d7da !important; color: #721c24 !important; font-weight: 600; text-align: left !important; }}

  .verd-bomb {{ background-color: #d4edda !important; color: #0f5132 !important; font-weight: 700; text-align: left !important; }}
  .verd-ok {{ background-color: #e9f7ef !important; color: #1e7e34 !important; font-weight: 600; text-align: left !important; }}
  .verd-warn {{ background-color: #fceaea !important; color: #842029 !important; text-align: left !important; }}
  .gw-highlight td {{ border-top: 2px solid #107c41 !important; border-bottom: 2px solid #107c41 !important; }}

  .scanner-legend {{
    margin: 12px 14px; padding: 11px 15px; background: #f3f8f5;
    border: 1px solid #c5dfd0; border-left: 4px solid var(--excel-green);
    border-radius: 5px; font-size: 12.5px; line-height: 1.5; color: #222;
  }}
  .scanner-legend-title {{ font-weight: 700; color: #0f5132; margin-bottom: 5px; font-size: 13px; }}
  .scanner-legend ul {{ margin: 0; padding-left: 18px; }}
  .scanner-legend li {{ margin-bottom: 3px; }}

  .planer-wrap {{ display: flex; flex-direction: column; gap: 16px; padding: 12px 14px 28px; }}
  .planer-card {{ border: 1px solid #d0d7d3; border-radius: 6px; background: white; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .planer-card-hdr {{
    background: #eef4f0; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #d0d7d3; font-weight: 700; color: #107c41; font-size: 13.5px; flex-wrap: wrap; gap: 8px;
  }}
  .sec-divider-row td {{
    background: #dfeee5 !important; color: #0b5d30 !important; font-weight: 700 !important;
    text-align: left !important; padding: 7px 10px !important; border-top: 3px solid #107c41 !important;
    border-bottom: 2px solid #107c41 !important;
  }}

  tr.zone-GKP td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #DAE3F3 !important; }}
  tr.zone-DEF td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #FBE5D6 !important; }}
  tr.zone-MID td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #EDEDED !important; }}
  tr.zone-FWD td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #FFF2CC !important; }}
  tr.zone-NEW td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #ffffff !important; }}

  tr.zone-GKP:hover td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #c8d7f0 !important; }}
  tr.zone-DEF:hover td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #f8d4bc !important; }}
  tr.zone-MID:hover td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #dedede !important; }}
  tr.zone-FWD:hover td:not(.cell-fix):not([class*="dec-"]):not(.xpts-cell) {{ background-color: #ffe8a3 !important; }}

  tr.zone-border-top td {{ border-top: 3px solid #1f2937 !important; }}
  tr.zone-border-bottom td {{ border-bottom: 3px solid #1f2937 !important; }}

  @keyframes rowHighlightPulse {{
    0%   {{ outline: 3px solid #107c41; filter: brightness(0.92); }}
    100% {{ outline: 3px solid transparent; filter: brightness(1); }}
  }}
  tr.just-placed {{ animation: rowHighlightPulse 1.4s ease-out; }}

  .pos-pills {{ display: inline-flex; gap: 6px; margin-left: 10px; font-size: 11.5px; font-weight: 700; }}
  .pos-pill {{ padding: 2px 7px; border-radius: 4px; border: 1px solid #999; color: #111; }}
  .pos-pill.p-GKP {{ background: #DAE3F3; }}
  .pos-pill.p-DEF {{ background: #FBE5D6; }}
  .pos-pill.p-MID {{ background: #EDEDED; }}
  .pos-pill.p-FWD {{ background: #FFF2CC; }}

  .p-combo-wrap {{ display: flex; align-items: center; gap: 3px; }}
  .p-input {{
    width: 175px; padding: 4px 7px; border: 1px solid #999; border-radius: 4px;
    font-size: 12px; background: rgba(255,255,255,0.88); transition: border-color 0.15s, box-shadow 0.15s;
  }}
  .p-input:focus {{ outline: none; border-color: var(--excel-green); background: #fff; box-shadow: 0 0 0 2px rgba(16,124,65,0.18); }}
  .p-input.invalid-flash {{ border-color: #d32f2f !important; background: #fff2f0 !important; }}
  .p-sel {{ padding: 3px 5px; border: 1px solid #aaa; border-radius: 3px; font-size: 12px; background: rgba(255,255,255,0.88); }}
  .p-gw-in {{ width: 48px; padding: 3px 4px; border: 1px solid #aaa; border-radius: 3px; font-size: 12px; text-align: center; background: rgba(255,255,255,0.88); }}

  #playerDropdownMenu {{
    display: none; position: fixed; z-index: 9999; background: #ffffff;
    border: 1px solid #107c41; border-radius: 5px; box-shadow: 0 6px 18px rgba(0,0,0,0.18);
    max-height: 250px; overflow-y: auto; width: 295px; font-size: 12.5px;
  }}
  .dd-item {{
    padding: 6px 10px; cursor: pointer; display: flex; justify-content: space-between;
    align-items: center; border-bottom: 1px solid #f0f0f0;
  }}
  .dd-item:last-child {{ border-bottom: none; }}
  .dd-item:hover, .dd-item.active {{ background: #e6f4ec; }}
  .dd-meta {{ font-size: 11px; color: #555; font-weight: 600; white-space: nowrap; margin-left: 8px; }}
  .dd-empty {{ padding: 9px 10px; color: #b00020; font-size: 12px; font-weight: 600; text-align: center; }}

  #planerToast {{
    display: none; position: fixed; bottom: 52px; right: 20px; z-index: 10000;
    background: #222; color: #fff; padding: 9px 14px; border-radius: 6px;
    font-size: 12.5px; font-weight: 600; box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  }}

  .cell-fix {{ cursor: pointer; position: relative; transition: opacity 0.15s; }}
  .cell-fix:hover {{ outline: 2px solid #111; z-index: 1; }}
  .cell-inactive {{ opacity: 0.25 !important; text-decoration: line-through; }}
  .cell-bench {{ box-shadow: inset 0 0 0 2px #111; opacity: 0.62; }}
  .badge-mini {{
    display: inline-block; font-size: 9.5px; font-weight: 700; padding: 1px 3px; border-radius: 3px;
    margin-left: 3px; background: rgba(0,0,0,0.75); color: #fff; vertical-align: middle;
  }}
  .cap-badge {{
    display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 4px; border-radius: 3px;
    margin-left: 4px; background: #1e293b; color: #facc15; vertical-align: middle;
  }}
  .dec-now {{ background: #ffd6d6 !important; color: #900 !important; font-weight: 700; text-align: left !important; }}
  .dec-soon {{ background: #fff0c2 !important; color: #7a4f00 !important; font-weight: 700; text-align: left !important; }}
  .dec-plan {{ background: #e8f1ff !important; color: #0b4a99 !important; font-weight: 600; text-align: left !important; }}
  .dec-ok {{ background: #e6f6ec !important; color: #0f5132 !important; font-weight: 600; text-align: left !important; }}
  .dec-hold {{ background: #f3ecff !important; color: #4b1d8c !important; font-weight: 600; text-align: left !important; }}

  .gw-pills {{ display: flex; flex-wrap: wrap; gap: 5px; padding: 9px 12px; background: #f8faf9; border-bottom: 1px solid #e0e0e0; align-items: center; }}
  .gw-pill {{
    padding: 5px 10px; border: 1px solid #bbb; border-radius: 16px; background: white; cursor: pointer;
    font-size: 12px; font-weight: 600; color: #333;
  }}
  .gw-pill.active {{ background: var(--excel-green); color: white; border-color: var(--excel-green); }}
  .lineup-tables-grid {{ display: grid; grid-template-columns: 1.35fr 1fr; gap: 14px; padding: 12px; align-items: start; }}
  @media (max-width: 960px) {{ .lineup-tables-grid {{ grid-template-columns: 1fr; }} }}
  .mini-tbl-box {{ border: 1px solid #d4d4d4; border-radius: 5px; overflow: hidden; background: white; }}
  .mini-tbl-hdr {{
    background: #f3f7f5; padding: 7px 10px; font-size: 13px; font-weight: 700; color: #107c41;
    border-bottom: 1px solid #d4d4d4; display: flex; justify-content: space-between; align-items: center;
  }}
  table.mini-table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; }}
  table.mini-table th {{ background: #e8e8e8; padding: 5px 7px; border: 1px solid #ccc; text-align: center; font-weight: 600; }}
  table.mini-table td {{ padding: 5px 7px; border: 1px solid #e0e0e0; text-align: center; white-space: nowrap; }}
  table.mini-table td.text-left {{ text-align: left; font-weight: 500; }}

  .val-bar {{ display: flex; flex-wrap: wrap; gap: 14px; padding: 9px 12px; background: #f3f6f4; border-top: 1px solid #e0e0e0; font-size: 12.5px; align-items: center; }}
  .val-ok {{ color: #0f5132; font-weight: 700; }}
  .val-err {{ color: #b00020; font-weight: 700; }}
  .val-xpts {{ background: #d6eaf8; color: #0b4a7d; padding: 3px 9px; border-radius: 4px; font-weight: 700; }}
  .val-cap {{ background: #fef3c7; color: #92400e; padding: 3px 9px; border-radius: 4px; font-weight: 700; }}
  .val-rng {{ background: #ede9fe; color: #5b21b6; padding: 3px 9px; border-radius: 4px; font-weight: 700; cursor: help; }}

  .bottom-tabs {{
    background: #e1dfdd; border-top: 1px solid #c8c6c4; display: flex; align-items: center;
    padding: 0 10px; height: 40px; gap: 4px; overflow-x: auto;
  }}
  .sheet-tab {{
    padding: 7px 15px; background: #edebe9; border: 1px solid #c8c6c4; border-bottom: none;
    font-size: 13px; cursor: pointer; color: #333; border-radius: 4px 4px 0 0; white-space: nowrap;
  }}
  .sheet-tab.active {{ background: #ffffff; color: var(--excel-green); font-weight: 700; border-bottom: 3px solid var(--excel-green); }}
  .sub-section {{ padding: 14px 16px 6px; font-weight: 700; color: #107c41; font-size: 14px; background: #f8f9fa; border-top: 2px solid #d4d4d4; }}
</style>
</head>
<body>

<div id="fplTooltip"></div>
<div id="playerDropdownMenu" onmousedown="event.preventDefault()"></div>
<div id="planerToast"></div>

<div class="top-bar">
  <div>📊 FPL Plik</div>
  <div class="badge">
    <span>🕒 {updated_at}</span>
    <span>| Najbliższa: GW{next_gw_num}</span>
    <span>| Forma L5: {l5_label}<span class="info-icon" data-tip="TOP_L5" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></span>
    <span>| Mediana xGC/90: {med_npxgc90:.3f}<span class="info-icon" data-tip="TOP_XGC" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></span>
    <span>| Mediana PPDA: {med_ppda:.2f}<span class="info-icon" data-tip="TOP_PPDA" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></span>
  </div>
</div>

<div class="sheet-container">

  <!-- 1. TABELA PREMIER LEAGUE -->
  <div id="tab-pl" class="tab-view">
    <div class="toolbar">
      <b>🏆 Tabela Premier League</b>
      <span style="margin-left:auto; color:#555;">Najedź na ⓘ, aby zobaczyć objaśnienie · Kliknij nagłówek, aby posortować</span>
    </div>
    <div class="table-scroll"><table class="excel-table" id="tbl-pl"></table></div>
  </div>

  <!-- 2. TABELA PIŁKARZY -->
  <div id="tab-players" class="tab-view">
    <div class="toolbar">
      <div class="toolbar-group"><label>Szukaj:</label><input type="text" id="pSearch" placeholder="Piłkarz..." oninput="renderPlayers()"></div>
      <div class="toolbar-group"><label>Klub:</label><select id="pTeam" onchange="renderPlayers()"><option value="ALL">Wszystkie</option></select></div>
      <div class="toolbar-group"><label>Pozycja:</label>
        <select id="pPos" onchange="renderPlayers()">
          <option value="ALL">Wszystkie</option><option value="GKP">GKP</option><option value="DEF">DEF</option><option value="MID">MID</option><option value="FWD">FWD</option>
        </select>
      </div>
      <div style="margin-left:auto; font-weight:600; color:#107c41;" id="pCount"></div>
    </div>
    <div class="table-scroll"><table class="excel-table" id="tbl-players"></table></div>
  </div>

  <!-- 3. FDR -->
  <div id="tab-fdr" class="tab-view">
    <div class="toolbar">
      <b>Tryb kolorowania kalendarza:</b>
      <button class="mode-btn active" onclick="setFdrMode('fdr_overall', this)">FDR Ogólny <span class="info-icon" data-tip="FDR_ALL" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></button>
      <button class="mode-btn" onclick="setFdrMode('fdr_atk', this)">Atak (MID/FWD) <span class="info-icon" data-tip="FDR_ATK" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></button>
      <button class="mode-btn" onclick="setFdrMode('fdr_def', this)">Obrona (DEF/GKP) <span class="info-icon" data-tip="FDR_DEF" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></button>
      <span style="margin-left:auto; font-size:12px; color:#555;">Reguła: na wyjeździe (A) trudność rywala +1 (maks. 5)</span>
    </div>
    <div class="table-scroll"><table class="excel-table" id="tbl-fdr"></table></div>
  </div>

  <!-- 4. KOKPIT -->
  <div id="tab-kokpit" class="tab-view active">
    <div class="toolbar">
      <div class="toolbar-group"><label>Szukaj:</label><input type="text" id="kSearch" placeholder="Zawodnik / klub..." oninput="renderKokpit()"></div>
      <div class="toolbar-group"><label>Pozycja:</label>
        <select id="kPos" onchange="renderKokpit()">
          <option value="ALL">Wszystkie</option><option value="GKP">GKP</option><option value="DEF">DEF</option><option value="MID">MID</option><option value="FWD">FWD</option>
        </select>
      </div>
      <div class="toolbar-group"><label>Maks. Cena (£):</label>
        <input type="range" id="kPrice" min="3.8" max="{max_price_slider:.1f}" step="0.1" value="{max_price_slider:.1f}" oninput="document.getElementById('kPriceVal').innerText=Number(this.value).toFixed(1); renderKokpit()">
        <span id="kPriceVal" style="font-weight:700; min-width:34px;">{max_price_slider:.1f}</span>
      </div>
      <div class="toolbar-group"><label>Forma L5 ({l5_label}):</label>
        <select id="kTrend" onchange="renderKokpit()">
          <option value="ALL">Wszystkie</option>
          <option value="UP">📈 Rośnie (&ge;+20%)</option>
          <option value="STABLE">➡️ Stabilna</option>
          <option value="DOWN">📉 Spadek (&le;-20%)</option>
          <option value="LOW_MIN">⏸️ Mało min (&lt;90m)</option>
        </select>
      </div>
      <div class="toolbar-group"><label>Status min.:</label>
        <select id="kMinStat" onchange="renderKokpit()">
          <option value="ALL">Wszyscy</option>
          <option value="🟢 Pewniak (>70m)">🟢 Pewniak (&gt;70m)</option>
          <option value="🟡 Rotacja (50-70m)">🟡 Rotacja (50-70m)</option>
          <option value="⚠️ Spadek minut (L5)">⚠️ Spadek minut (L5)</option>
        </select>
      </div>
      <div class="toolbar-group"><label>Scenariusz (GW{next_gw_num}):</label>
        <select id="kScen" onchange="renderKokpit()">
          <option value="ALL">Wszystkie</option>
          <option value="MD">🎁 Samobójczy Pressing (MD)</option>
          <option value="DD">🎪 Chłopcy do bicia (DD)</option>
          <option value="MM">🚧 Elitarny Pressing (MM)</option>
          <option value="DM">🧱 Elitarny Autobus (DM)</option>
        </select>
      </div>
      <div class="toolbar-group">
        <label style="cursor:pointer;"><input type="checkbox" id="kOnlyMine" onchange="renderKokpit()"> Tylko mój skład (👕)</label>
      </div>
      <div class="toolbar-group">
        <label style="cursor:pointer;"><input type="checkbox" id="kHideInj" onchange="renderKokpit()"> Ukryj kontuzjowanych (0%)</label>
      </div>
      <div class="toolbar-group">
        <label style="cursor:pointer;"><input type="checkbox" id="kShowTech" onchange="renderKokpit()"> Pokaż ukryte (składowe xPts, xGC 2-6, Szyfr)</label>
      </div>
      <div style="margin-left:auto; font-weight:700; color:#107c41;" id="kCount"></div>
    </div>
    <div class="table-scroll"><table class="excel-table" id="tbl-kokpit"></table></div>
  </div>

  <!-- 5. SKANER WILDCARD I FREE HIT -->
  <div id="tab-scanner" class="tab-view">
    <div class="toolbar">
      <b>💣 Skaner Wildcard (5 GW) i Free Hit</b>
      <div class="toolbar-group" style="margin-left:16px;">
        <label>Zakres kolejek:</label>
        <select id="sScope" onchange="renderScanner()">
          <option value="FUTURE">Od najbliższej (GW{next_gw_num}–GW38)</option>
          <option value="ALL">Cały sezon (GW1–GW38)</option>
        </select>
      </div>
      <span style="margin-left:auto; font-size:12px; color:#555;">Próg Free Hit: {(avg_at_19+std_at_19):.2f} | Próg Wildcard: {(avg_aw_37+std_aw_37):.2f} | Mediana kolejki: {med_at_37:.2f}</span>
    </div>
    <div class="table-scroll">
      <table class="excel-table" id="tbl-scanner"></table>
      <div class="scanner-legend">
        <div class="scanner-legend-title">ℹ️ Jak działa Skaner Wildcard i Free Hit?</div>
        <ul>
          <li><b>Skąd biorą się punkty:</b> w każdej kolejce algorytm liczy siłę ofensywną meczu dla każdego z 20 klubów (<code>NPxG drużyny × NPxGA rywala</code>, skorygowane o grę u siebie/na wyjeździe — pełne liczby widać niżej w Tabeli Chipów). Wynik kolejki to suma <b>5 najlepszych klubów</b>.</li>
          <li><b>Free Hit (1 GW):</b> werdykt <b>💣 WYBUCHOWA</b> zapala się, gdy wynik kolejki przekracza próg statystyczny (średnia + odchylenie standardowe z I rundy = <b>{(avg_at_19+std_at_19):.2f}</b>) — oznacza wyjątkowo korzystną kolejkę dla faworytów.</li>
          <li><b>Wildcard (5 GW):</b> średnia z 5 kolejnych kolejek (od danej GW włącznie). Werdykt <b>💣 ODPALAJ WILDCARD!</b> pojawia się dopiero, gdy średnia 5-kolejkowa przekracza próg (<b>{(avg_aw_37+std_aw_37):.2f}</b>) <b>oraz</b> minimum 3 z 5 kolejek osiągają co najmniej ligową medianę (<b>{med_at_37:.2f}</b>) — chroni to przed pułapką jednej łatwej kolejki maskującej trudny terminarz.</li>
        </ul>
      </div>
      <div class="sub-section">📋 Podgląd Tabeli Chipów (siła 20 klubów na GW — źródło dla Skanera)</div>
      <table class="excel-table" id="tbl-chips"></table>
    </div>
  </div>

  <!-- 6. PLANER -->
  <div id="tab-planer" class="tab-view">
    <div class="toolbar">
      <b>🗓️ Planer Składu (strefy GKP / DEF / MID / FWD + silnik xPts)</b>
      <div class="toolbar-group">
        <button class="mode-btn active" id="pViewTxt" onclick="setPlanerCellMode('text', this)">Rywale (EVE-H)</button>
        <button class="mode-btn" id="pViewNum" onclick="setPlanerCellMode('num', this)">Trudność (1–5)</button>
        <button class="mode-btn" id="pViewXp" onclick="setPlanerCellMode('xpts', this)">Prognoza (xPts)</button>
      </div>
      <div class="toolbar-group" style="margin-left:auto;">
        <button class="act-btn" onclick="exportPlaner()">💾 Eksportuj JSON</button>
        <button class="act-btn" onclick="importPlaner()">📂 Importuj JSON</button>
        <button class="act-btn danger" onclick="resetPlaner()">↺ Resetuj</button>
      </div>
    </div>
    <div class="table-scroll" id="planerScrollArea">
      <div class="planer-wrap">
        <div class="planer-card">
          <div class="planer-card-hdr">
            <span>📋 TABELA 1: PLANER DŁUGOTERMINOWY (Skład w strefach pozycji + Cele IN)</span>
            <div style="display:flex; gap:6px;">
              <button class="act-btn primary" onclick="addPlanerRow('squad')">+ Dodaj do składu</button>
              <button class="act-btn" onclick="addPlanerRow('targets')">+ Dodaj cel IN</button>
            </div>
          </div>
          <div style="overflow-x:auto;"><table class="excel-table" id="tbl-planer-main"></table></div>
        </div>

        <div class="planer-card">
          <div class="planer-card-hdr">
            <span>⚽ TABELA 2: PRZYMIARKA SKŁADU NA WYBRANĄ KOLEJKĘ (Wyjściowa 11 i Ławka)</span>
            <div style="display:flex; gap:8px; align-items:center;">
              <button class="act-btn primary" onclick="autoPickBenchForGw()">⚡ Auto-ławka (xPts) <span class="info-icon" data-tip="PLR_AUTO" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span></button>
              <span id="lineupGwInfo" style="font-weight:600; font-size:12.5px;"></span>
            </div>
          </div>
          <div class="gw-pills" id="planerGwPills"></div>
          <div class="lineup-tables-grid">
            <div class="mini-tbl-box">
              <div class="mini-tbl-hdr"><span>🟢 Wyjściowa 11</span><span id="xiCountBadge"></span></div>
              <table class="mini-table" id="tbl-lineup-xi"></table>
            </div>
            <div class="mini-tbl-box">
              <div class="mini-tbl-hdr"><span>🪑 Ławka rezerwowych</span><span id="benchCountBadge"></span></div>
              <table class="mini-table" id="tbl-lineup-bench"></table>
            </div>
          </div>
          <div class="val-bar" id="lineupValidation"></div>
        </div>
      </div>
    </div>
  </div>

</div>

<div class="bottom-tabs">
  <div class="sheet-tab" onclick="switchTab('pl', this)">1. 🏆 Tabela Premier League</div>
  <div class="sheet-tab" onclick="switchTab('players', this)">2. 👤 Tabela Piłkarzy</div>
  <div class="sheet-tab" onclick="switchTab('fdr', this)">3. 📅 FDR</div>
  <div class="sheet-tab active" onclick="switchTab('kokpit', this)">4. 🎛️ Kokpit</div>
  <div class="sheet-tab" onclick="switchTab('scanner', this)">5. 💣 Skaner Wildcard i Free Hit</div>
  <div class="sheet-tab" onclick="switchTab('planer', this)">6. 🗓️ Planer</div>
</div>

<script>
const dataPL = {json_pl};
const dataPlayers = {json_players};
const dataCatalog = {json_catalog};
const dataFDR = {json_fdr};
const teamFixShort = {json_team_fix_short};
const gwMeta = {json_gw_meta};
const dataKokpit = {json_kokpit};
const planerXptsMap = {json_planer_xpts};
const radarCuts = {json_radar_cuts};
const rollingGWs = {json_rolling_gws};
const planerGWs = {json_planer_gws};
const dataScanner = {json_scanner};
const dataChips = {json_chip_matrix};
const nextGwNum = {next_gw_num};
const defaultSquad = {json_def_squad};
const defaultTargets = {json_def_targets};

// ============================================================================
// SYSTEM DYMKÓW (TOOLTIPÓW) ⓘ ORAZ PARAGONÓW xPts
// ============================================================================
const TIPS = {{
  TOP_L5: {{
    title: 'Okno formy (L5)',
    body: 'Ostatnie 5 zakończonych kolejek. Silnik xPts łączy ustabilizowany sezon z formą L5 (waga L5 do maks. <b>25%</b> po stabilizacji małej próbki) oraz uwzględnia powroty starterów w xMins.'
  }},
  TOP_XGC: {{
    title: 'Ligowa mediana xGC/90',
    body: 'Środkowa wartość oczekiwanych bramek traconych na mecz w Premier League — punkt odniesienia dla silnika xPts, FDR i Scenariuszy.'
  }},
  TOP_PPDA: {{
    title: 'Ligowa mediana PPDA',
    body: 'Środkowa wartość intensywności pressingu w lidze — oddziela drużyny pressujące wysoko od broniących głębiej.'
  }},

  // Zakładka 1: Tabela Premier League
  PL_XG: {{ title: 'xG (Expected Goals)', body: 'Oczekiwane bramki zdobyte. Suma jakości wszystkich oddanych strzałów drużyny.' }},
  PL_NPXG: {{ title: 'NPxG (Non-Penalty xG)', body: 'Oczekiwane bramki bez rzutów karnych.<span class="tip-muted">Tymczasowo równe xG podczas przerwy Understatu.</span>' }},
  PL_XGA: {{ title: 'xGA (Expected Goals Against)', body: 'Oczekiwane bramki stracone — im niższa wartość, tym szczelniejsza defensywa.' }},
  PL_NPXGA: {{ title: 'NPxGA (Non-Penalty xGA)', body: 'Oczekiwane bramki stracone bez rzutów karnych.<span class="tip-muted">Tymczasowo równe xGA podczas przerwy Understatu.</span>' }},
  PL_PPDA: {{ title: 'PPDA (Intensywność pressingu)', body: 'Liczba podań, na jakie zespół pozwala rywalowi na jego połowie, zanim spróbuje odebrać piłkę. <b>Im niższa wartość, tym agresywniejszy pressing.</b><span class="tip-muted">Tymczasowo zamrożone po GW8 do powrotu Understatu.</span>' }},
  PL_OPPDA: {{ title: 'OPPDA (Odporność na pressing)', body: 'Średnia liczba podań, jaką drużyna wymienia na własnej połowie przed atakiem rywala. <b>Im wyższa wartość</b>, tym łatwiej zespół rozgrywa piłkę.' }},
  PL_TAKT: {{ title: 'Taktyczne xGC90', body: 'Skorygowane zagrożenie defensywne na mecz (<b>xGA / mecze × mnożnik stylu</b>):<br>• ostry pressing (&lt;11) + szczelna obrona (&lt;1.2) → <b>×0.85</b><br>• ostry pressing (&lt;11) + dziurawa obrona (≥1.2) → <b>×1.20</b><br>• głęboki blok (&gt;14) + szczelna obrona (&lt;1.2) → <b>×0.90</b><br>• głęboki blok (&gt;14) + słaba obrona (≥1.2) → <b>×1.05</b>.' }},
  PL_XGD: {{ title: 'xGD (Różnica xG na mecz)', body: 'Średnia różnica oczekiwanych bramek na mecz: <b>(NPxG − NPxGA) / mecze</b>. Pokazuje realną siłę netto drużyny.' }},
  PL_FDR: {{ title: 'FDR (Wskaźnik trudności rywala)', body: 'Własny wskaźnik trudności rywala (<b>1 = najłatwiejszy, 5 = najtrudniejszy</b>) liczony na żywo z xGD i pressingu (PPDA).' }},

  // Zakładka 2: Tabela Piłkarzy
  P_STATUS: {{ title: 'Status dostępności (FPL API)', body: 'Aktualna flaga zdrowia/zawieszenia z oficjalnego FPL API: 🟢 100%, 🟡 75%, 🟠 50%/25%, 🔴 0%. Najedź na kropkę, aby przeczytać komunikat.' }},
  P_XGCHAIN: {{ title: 'xGChain', body: 'Wskaźnik podglądowy udziału w akcjach bramkowych.<span class="tip-muted">Tymczasowo pokazuje oficjalne xGI z FPL (xG + xA) do powrotu Understatu.</span>' }},
  P_DEFCON: {{ title: 'DefCon (Defensive Contributions)', body: 'Akcje defensywne punktowane w FPL (+2 pkt za mecz): dla <b>DEF</b> próg to <b>≥10</b> (wybicia, bloki, przechwyty, odbiory), a dla <b>MID/FWD</b> próg to <b>≥12</b> (wraz z odzyskaniami piłki).' }},
  P_SAVES: {{ title: 'Obrony (Saves)', body: 'Łączna liczba interwencji bramkarza w sezonie (+1 pkt w FPL za każde 3 obrony w meczu).' }},
  P_BONUS: {{ title: 'Bonus i BPS/90', body: 'Punkty bonusowe (1–3 pkt dla top 3 zawodników meczu wg systemu BPS) oraz średnia liczba punktów BPS na 90 minut.' }},

  // Zakładka 3: FDR
  FDR_ALL: {{ title: 'FDR Ogólny', body: 'Ogólna trudność rywala wyliczona z xGD i PPDA. <b>Im wyższa liczba (1–5), tym trudniejszy mecz</b> (na wyjeździe +1, maks. 5).' }},
  FDR_ATK: {{ title: 'Trudność dla Ataku (MID / FWD)', body: 'Trudność meczu dla Twoich graczy ofensywnych na podstawie szczelności obrony rywala (NPxGA/mecz). <b>Im wyższa (1–5), tym trudniej o punkty w ataku.</b>' }},
  FDR_DEF: {{ title: 'Trudność dla Obrony (DEF / GKP)', body: 'Trudność meczu dla Twoich obrońców i bramkarzy na podstawie siły ataku rywala (NPxG/mecz). <b>Im wyższa (1–5), tym trudniej o czyste konto.</b>' }},

  // Zakładka 4: Kokpit
  K_XMINS: {{ title: 'xMins (Przewidywane minuty)', body: 'Oczekiwana liczba minut na mecz (miks sezonu i L5 z ochroną pewniaków wracających po krótkiej pauzie). Wyznacza szanse na 1 pkt za grę, 2 pkt za ≥60 min oraz skaluje statystyki.' }},
  K_XGI90: {{ title: 'xGI90 (Sezon)', body: 'Oczekiwany udział przy golach (<b>xG + xA</b>) na 90 minut za cały sezon.' }},
  K_DEFCON90: {{ title: 'DefCon/90', body: 'Średnia akcji defensywnych na 90 minut. Zielone podświetlenie oznacza graczy regularnie dobijających do progu <b>+2 pkt</b> (<b>≥10</b> dla DEF, <b>≥12</b> dla MID/FWD).' }},
  K_MIN_L5: {{ title: 'Min L5 (Minuty z 5 GW)', body: 'Suma minut z ostatnich 5 kolejek (maks. 450). Żółte tło (<b>&lt; 175 min</b>) ostrzega przed rotacją lub urazem.' }},
  K_XG_L5: {{ title: 'xG L5 (Forma strzelecka)', body: 'Suma oczekiwanych bramek (xG) z ostatnich 5 kolejek.' }},
  K_XGI90_L5: {{ title: 'xGI90 L5 (Trend formy)', body: 'Aktualna forma ofensywna na 90 minut z L5 w porównaniu z sezonem: 📈 zwyżka (≥+20%), ➡️ stabilna, 📉 spadek (≤−20%), ⏸️ za mało minut (&lt;90m).' }},
  K_XGC_TEAM: {{ title: 'xGC/90 Drużyny', body: 'Średnie oczekiwane bramki tracone przez całą drużynę na mecz. Im niżej, tym szczelniejsza defensywa.' }},
  K_W1: {{ title: 'Werdykt (Atak)', body: 'Ocena czysto ofensywna na bazie xGI90 (pomaga wyłapać również ofensywnych obrońców).' }},
  K_OBR: {{ title: 'Ocena obrony', body: '🛡️ Mur przy xGC/90 ≤ 1.30, powyżej ⚠️ Dziurawi.' }},
  K_CS: {{ title: 'Szansa na CS (Poisson)', body: 'Prawdopodobieństwo czystego konta w najbliższej kolejce z iloczynowego rozkładu Poissona: (xGA/90 klubu × xG/90 rywala ÷ mediana ligi) z korektą dom/wyjazd.' }},
  K_XPTS_GW: {{ title: 'xPts GW (Pełna prognoza na najbliższą kolejkę)', body: 'Kompletna prognoza punktów FPL obejmująca <b>8 składników</b>: Występ (xMins + flaga kontuzji), Gole, Asysty, CS (także +1 dla MID), kary za 2+ stracone gole, <b>DefCon</b> (Poisson), <b>Obrony</b> (GKP), <b>Bonus</b> i Kartki.<span class="tip-muted">Najedź na dowolną liczbę w tej kolumnie, aby zobaczyć pełny paragon punktowy!</span>' }},
  K_W2: {{ title: 'Werdykt (Poz)', body: 'Szybka ocena dopasowana do pozycji: dla DEF/GKP patrzy na obronę zespołu, dla MID/FWD na xGI90.' }},
  K_EO: {{ title: 'Status EO (Posiadanie)', body: '🗡️ Super Diff (poniżej 10% posiadania) vs 🛡️ Szablon (od 10% w górę).' }},
  K_GC_OPP: {{ title: 'GC Rywala (H/A)', body: 'Oczekiwane bramki tracone na mecz przez najbliższego rywala, <b>już skorygowane o boisko</b> (×1.15 u siebie, ×0.85 na wyjeździe).' }},
  K_XPTS_6GW: {{ title: 'xPts 6GW (Suma punktów za 6 kolejek)', body: 'Realna <b>suma przewidywanych punktów FPL</b> w najbliższych 6 kolejkach (uwzględnia DGW, BLANKI oraz daty powrotu po kontuzjach z komunikatów FPL API).<span class="tip-muted">Najedź na liczbę, aby zobaczyć rozbicie po każdej kolejce!</span>' }},
  K_XPTS_VAL: {{ title: 'xPts/£ (Wartość za milion)', body: 'Stosunek <b>xPts 6GW ÷ Cena</b>. Pozwala błyskawicznie znaleźć najlepsze tanie opcje (np. obrońców za £4.5m z wysokim DefCon).' }},
  K_RADAR: {{ title: 'Radar (Dynamiczne progi)', body: 'Klasyfikacja oparta na realnym rozkładzie <b>xPts 6GW</b> osobno w ramach każdej pozycji: top 20% = 🛒 Priorytet Kupna, środek = ✅ Dobra Opcja, dół 35% = ❌ Pozbądź się.' }},
  K_SCEN: {{ title: 'Przewidywany Scenariusz (GW+1)', body: 'Podglądowy profil taktyczny najbliższego rywala na podstawie jego pressingu (PPDA) i szczelności obrony (xGA/90) względem mediany ligi. Nie nakłada już podwójnego mnożnika na xPts, bo siła defensywy rywala jest bezpośrednio uwzględniona w silniku.' }},

  // Zakładka 5: Skaner
  S_FH_SC: {{ title: 'Skaner Free Hit (Wynik 1 GW)', body: 'Suma siły ofensywnej 5 najlepszych klubów w tej kolejce (z Tabeli Chipów niżej).' }},
  S_FH_VR: {{ title: 'Werdykt Free Hit', body: '💣 WYBUCHOWA zapala się powyżej progu statystycznego (średnia + odchylenie standardowe).' }},
  S_WC_SC: {{ title: 'Skaner Wildcard (Średnia 5 GW)', body: 'Średni wynik z 5 kolejnych kolejek (od tej kolejki włącznie).' }},
  S_WC_VR: {{ title: 'Werdykt Wildcard', body: '💣 ODPALAJ WILDCARD! wymaga średniej 5 GW powyżej progu oraz min. 3 z 5 kolejek ≥ mediana ligi.' }},

  // Zakładka 6: Planer
  PLR_STATUS: {{ title: 'Status gracza w Planerze', body: '💎 Premium (bez alarmu sprzedaży), 🪵 Słup (tani rezerwowy, priorytet na ławkę w Auto-ławce), ♻️ Rotacja (oceniany pod kątem terminarza).' }},
  PLR_DEC: {{ title: 'Decyzja (Alarm kalendarzowy)', body: 'Ostrzega przed serią 3 trudnych meczów pod rząd (FDR 4 lub 5 dopasowany do pozycji) w oknie 12 GW.' }},
  PLR_OUTIN: {{ title: 'Kolumna OUT / IN', body: 'Wpisz numer kolejki sprzedaży (OUT) lub zakupu (IN). Kliknięcie kafelka meczu sadza gracza na ławce (Ł).' }},
  PLR_AUTO: {{ title: '⚡ Auto-ławka (po xPts)', body: 'Automatycznie wybiera optymalną wyjściową 11 na wybraną kolejkę pod <b>najwyższą sumę xPts</b> (z zachowaniem legalnej formacji FPL, sadzając najpierw graczy ze statusem 🪵 Słup i kontuzjowanych 0%).' }}
}};

let pinnedTipEl = null;

function escHtml(s) {{
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}}

function tipIcon(key) {{
  if (!key || !TIPS[key]) return '';
  return `<span class="info-icon" data-tip="${{key}}" onclick="event.stopPropagation(); toggleTip(this)" onmouseenter="showTip(this)" onmouseleave="hideTip()">ⓘ</span>`;
}}

function positionTooltip(anchorEl) {{
  const box = document.getElementById('fplTooltip');
  const rect = anchorEl.getBoundingClientRect();
  box.style.visibility = 'hidden';
  box.style.display = 'block';
  const bw = box.offsetWidth;
  const bh = box.offsetHeight;
  const pad = 10;

  let left = rect.left + rect.width / 2 - bw / 2;
  if (left < pad) left = pad;
  if (left + bw > window.innerWidth - pad) left = window.innerWidth - bw - pad;

  let top = rect.bottom + 8;
  if (top + bh > window.innerHeight - pad) {{
    top = rect.top - bh - 8;
    if (top < pad) top = pad;
  }}

  box.style.left = left + 'px';
  box.style.top = top + 'px';
  box.style.visibility = 'visible';
}}

function showHtmlTip(anchorEl, html) {{
  const box = document.getElementById('fplTooltip');
  box.innerHTML = html;
  positionTooltip(anchorEl);
}}

function showTip(anchorEl) {{
  const key = anchorEl.getAttribute('data-tip');
  const data = TIPS[key];
  if (!data) return;
  showHtmlTip(anchorEl, `<div class="tip-title">${{data.title}}</div><div>${{data.body}}</div>`);
}}

function hideTip(force) {{
  if (!force && pinnedTipEl) return;
  pinnedTipEl = null;
  document.getElementById('fplTooltip').style.display = 'none';
}}

function toggleTip(anchorEl) {{
  if (pinnedTipEl === anchorEl) {{ hideTip(true); }}
  else {{ pinnedTipEl = anchorEl; showTip(anchorEl); }}
}}

function toggleHtmlTip(anchorEl, html) {{
  if (pinnedTipEl === anchorEl) {{ hideTip(true); }}
  else {{ pinnedTipEl = anchorEl; showHtmlTip(anchorEl, html); }}
}}

function showInlineTip(anchorEl) {{
  const raw = anchorEl.getAttribute('data-tip-html');
  if (raw) showHtmlTip(anchorEl, decodeURIComponent(raw));
}}

function toggleInlineTip(anchorEl) {{
  const raw = anchorEl.getAttribute('data-tip-html');
  if (raw) toggleHtmlTip(anchorEl, decodeURIComponent(raw));
}}

document.addEventListener('click', (e) => {{
  if (pinnedTipEl && !e.target.closest('.info-icon,.xpts-cell,.st-dot,.tag-icon')) hideTip(true);
}});
window.addEventListener('resize', () => hideTip(true));
document.addEventListener('scroll', () => hideTip(true), true);

function statusDotHtml(status, chance, news) {{
  let cls = 'st-ok', lbl = 'Dostępny (100%)';
  if (status === 'u') {{ cls = 'st-0'; lbl = 'Niedostępny (poza kadrą)'; }}
  else if (chance === 0) {{ cls = 'st-0'; lbl = 'Niedostępny / Kontuzja / Zawieszenie (0%)'; }}
  else if (chance <= 50) {{ cls = 'st-50'; lbl = `Wątpliwy występ (${{chance}}%)`; }}
  else if (chance < 100) {{ cls = 'st-75'; lbl = `Lekki znak zapytania (${{chance}}%)`; }}
  const body = news ? `${{escHtml(lbl)}}<span class="tip-muted">${{escHtml(news)}}</span>` : escHtml(lbl);
  const html = encodeURIComponent(`<div class="tip-title">Status FPL</div><div>${{body}}</div>`);
  return `<span class="st-dot ${{cls}}" data-tip-html="${{html}}" onclick="event.stopPropagation(); toggleInlineTip(this)" onmouseenter="showInlineTip(this)" onmouseleave="hideTip()"></span>`;
}}

function calcSingleRange(mu, sd) {{
  if (mu <= 0.05 || sd <= 0.05) return {{ lo: Math.max(0, mu), hi: Math.max(0, mu) }};
  return {{
    lo: Math.max(0, mu - 0.75 * sd),
    hi: mu + 0.85 * sd
  }};
}}

function calcTeamRange(mu, sd) {{
  if (mu <= 0.5 || sd <= 0.05) return {{ lo: Math.max(0, mu), hi: Math.max(0, mu) }};
  const cv2 = Math.pow(sd / mu, 2);
  const sig = Math.sqrt(Math.log(1 + cv2));
  const muLn = Math.log(mu) - 0.5 * sig * sig;
  const z = 0.84162;
  return {{
    lo: Math.max(0, Math.exp(muLn - z * sig)),
    hi: Math.max(mu, Math.exp(muLn + z * sig))
  }};
}}

function buildXptsReceiptHtml(brk, title, total, extraNote, sdVal) {{
  const labels = [
    ['Występ (xMins)', brk[0]],
    ['Gole (xG)', brk[1]],
    ['Asysty (xA)', brk[2]],
    ['Czyste konto (CS)', brk[3]],
    ['Stracone gole (−1/2g)', brk[4]],
    ['DefCon (+2 pkt)', brk[5]],
    ['Obrony (+1/3 obr.)', brk[6]],
    ['Bonus (BPS)', brk[7]],
    ['Kartki (ŻK / CzK)', brk[8]],
  ];
  let rows = '';
  labels.forEach(([lbl, val]) => {{
    if (Math.abs(val) < 0.005) return;
    const vCls = val > 0 ? 'tip-pos' : 'tip-neg';
    const sign = val > 0 ? '+' : '';
    rows += `<div>${{lbl}}</div><div class="tip-val ${{vCls}}">${{sign}}${{val.toFixed(2)}}</div>`;
  }});
  if (!rows) rows = `<div>Brak punktów (BLANK / 0% szans)</div><div class="tip-val">0.00</div>`;
  let rangeHtml = '';
  if (sdVal && sdVal > 0.05 && total > 0.05) {{
    const rng = calcSingleRange(Number(total), Number(sdVal));
    rangeHtml = `<div style="margin-top:4px; font-size:11.5px; color:#cbd5e1; display:flex; justify-content:space-between; gap:10px;"><span>📉 Podłoga / 📈 Sufit (P20–P80):</span><b style="color:#fde68a;">${{rng.lo.toFixed(1)}} – ${{rng.hi.toFixed(1)}} pkt</b></div><div style="font-size:11px; color:#94a3b8; text-align:right;">Odchylenie std (σ): ±${{Number(sdVal).toFixed(2)}} pkt</div>`;
  }}
  const noteHtml = extraNote ? `<span class="tip-muted">${{escHtml(extraNote)}}</span>` : '';
  return `<div class="tip-title">${{escHtml(title)}}</div><div class="tip-grid">${{rows}}</div><div class="tip-total"><span>Razem xPts</span><span>${{Number(total).toFixed(2)}} pkt</span></div>${{rangeHtml}}${{noteHtml}}`;
}}

function buildXpts6Html(list, playerName, total) {{
  let rows = '';
  (list || []).forEach(it => {{
    rows += `<div>${{escHtml(it.gw)}} (${{escHtml(it.fx)}})</div><div class="tip-val tip-pos">${{Number(it.xp).toFixed(2)}}</div>`;
  }});
  return `<div class="tip-title">${{escHtml(playerName)}} — 6 kolejek</div><div class="tip-grid">${{rows}}</div><div class="tip-total"><span>Suma 6 GW</span><span>${{Number(total).toFixed(2)}} pkt</span></div>`;
}}

function xptsTierClass(v) {{
  if (v <= 0.05) return 'xp-tier-0';
  if (v >= 5.5) return 'xp-tier-5';
  if (v >= 4.0) return 'xp-tier-4';
  if (v >= 2.7) return 'xp-tier-3';
  return 'xp-tier-2';
}}
let plSort = {{ col: 'points', asc: false }};
let pSort = {{ col: 'G', asc: false }};
let kSort = {{ col: 'xPts_6GW', asc: false }};
let fdrMode = 'fdr_overall';
let planerCellMode = 'text';
let selectedLineupGw = planerGWs[0] || nextGwNum;
let lastPlacedPlayer = null;

const POS_RANK = {{ GKP: 1, DEF: 2, MID: 3, FWD: 4 }};
const STORAGE_KEY = 'fpl_v7_planer_state_v3';

function normStr(s) {{
  return (s || '')
    .toLowerCase()
    .replace(/ß/g, 'ss')
    .replace(/ø/g, 'o')
    .replace(/ł/g, 'l')
    .replace(/đ/g, 'd')
    .replace(/ð/g, 'd')
    .replace(/ı/g, 'i')
    .replace(/æ/g, 'ae')
    .replace(/œ/g, 'oe')
    .replace(/þ/g, 'th')
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '')
    .trim();
}}

function findExactPlayer(name) {{
  if (!name || !name.trim()) return null;
  const q = normStr(name);
  const qAlt = q.replace(/dj/g, 'd');
  return dataCatalog.find(p => {{
    const np = normStr(p.player);
    return np === q || np === qAlt;
  }}) || null;
}}

function migrateSavedNames(stateObj) {{
  let changed = false;
  ['squad', 'targets'].forEach(sec => {{
    (stateObj[sec] || []).forEach(r => {{
      if (r.player) {{
        const match = findExactPlayer(r.player);
        if (match && match.player !== r.player) {{
          r.player = match.player;
          changed = true;
        }}
      }}
    }});
  }});
  return changed;
}}

let planerState = loadPlanerState();

function loadPlanerState() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem('fpl_v7_planer_state_v2') || localStorage.getItem('fpl_v7_planer_state_v1');
    if (raw) {{
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.squad) && Array.isArray(parsed.targets)) {{
        parsed.benchMap = parsed.benchMap || {{}};
        if (migrateSavedNames(parsed)) {{
          try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed)); }} catch (e) {{}}
        }}
        return parsed;
      }}
    }}
  }} catch (e) {{}}
  return {{
    squad: JSON.parse(JSON.stringify(defaultSquad)),
    targets: JSON.parse(JSON.stringify(defaultTargets)),
    benchMap: {{}}
  }};
}}

function savePlanerState() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(planerState)); }} catch (e) {{}}
}}

function getMySquadSet() {{
  const s = new Set();
  (planerState.squad || []).forEach(r => {{
    if (r.player) s.add(r.player);
  }});
  return s;
}}

function getMyTargetsSet() {{
  const s = new Set();
  (planerState.targets || []).forEach(r => {{
    if (r.player) s.add(r.player);
  }});
  return s;
}}

function addTargetFromKokpit(playerName) {{
  if (!playerName) return;
  const inSquad = getMySquadSet().has(playerName);
  if (inSquad) {{
    showToast(`👕 ${{playerName}} jest już w Twoim składzie w Planerze.`);
    return;
  }}
  const already = (planerState.targets || []).some(r => r.player === playerName);
  if (already) {{
    showToast(`🎯 ${{playerName}} jest już na liście celów IN w Planerze.`);
    return;
  }}
  planerState.targets.push({{ player: playerName, status: '', inGw: String(nextGwNum) }});
  savePlanerState();
  renderPlaner();
  renderKokpit();
  showToast(`🎯 Dodano ${{playerName}} do Celów IN w Planerze (GW${{nextGwNum}}).`);
}}

let toastTimer = null;
function showToast(msg) {{
  const el = document.getElementById('planerToast');
  el.innerText = msg;
  el.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {{ el.style.display = 'none'; }}, 2800);
}}

function switchTab(id, el) {{
  closePlayerDropdown();
  hideTip(true);
  document.querySelectorAll('.tab-view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.sheet-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  el.classList.add('active');
}}

function cmpVal(a, b, asc) {{
  if (typeof a === 'string' && typeof b === 'string') return asc ? a.localeCompare(b) : b.localeCompare(a);
  return asc ? (a - b) : (b - a);
}}

// ============================================================================
// 1. TABELA PREMIER LEAGUE
// ============================================================================
const PL_TIP_MAP = {{
  'xG': 'PL_XG', 'NPxG': 'PL_NPXG', 'xGA': 'PL_XGA', 'NPxGA': 'PL_NPXGA',
  'PPDA': 'PL_PPDA', 'OPPDA': 'PL_OPPDA', 'Taktyczne xGC90': 'PL_TAKT',
  'xGD': 'PL_XGD', 'FDR': 'PL_FDR'
}};

function renderPL() {{
  const cols = Object.keys(dataPL[0] || {{}});
  const rows = [...dataPL].sort((a, b) => cmpVal(a[plSort.col], b[plSort.col], plSort.asc));
  let html = '<thead><tr><th>#</th>' + cols.map(c =>
    `<th onclick="sortPL('${{c}}')">${{c}}${{tipIcon(PL_TIP_MAP[c])}} ${{plSort.col===c ? (plSort.asc?'▲':'▼') : ''}}</th>`
  ).join('') + '</tr></thead><tbody>';
  rows.forEach((r, idx) => {{
    html += `<tr><td class="text-center">${{idx+1}}</td>`;
    cols.forEach(c => {{
      let cls = '';
      if (c === 'team') cls = 'text-left';
      else if (c === 'Skrót') cls = 'text-center';
      else if (c === 'FDR') cls = 'fdr-' + r[c];
      html += `<td class="${{cls}}">${{escHtml(r[c])}}</td>`;
    }});
    html += '</tr>';
  }});
  document.getElementById('tbl-pl').innerHTML = html + '</tbody>';
}}
function sortPL(c) {{ plSort = {{ col: c, asc: plSort.col === c ? !plSort.asc : false }}; renderPL(); }}

// ============================================================================
// 2. TABELA PIŁKARZY (Status, DefCon, Obrony, Bonus, BPS/90, ŻK)
// ============================================================================
function initPlayersFilter() {{
  const teams = [...new Set(dataPlayers.map(p => p.team))].sort();
  const sel = document.getElementById('pTeam');
  teams.forEach(t => {{ const o = document.createElement('option'); o.value = t; o.textContent = t; sel.appendChild(o); }});
}}

function renderPlayers() {{
  const q = normStr(document.getElementById('pSearch').value);
  const qAlt = q.replace(/dj/g, 'd');
  const team = document.getElementById('pTeam').value;
  const pos = document.getElementById('pPos').value;
  let rows = dataPlayers.filter(r => {{
    if (q) {{
      const np = normStr(r.player);
      const nt = normStr(r.team);
      if (!np.includes(q) && !np.includes(qAlt) && !nt.includes(q)) return false;
    }}
    if (team !== 'ALL' && r.team !== team) return false;
    if (pos !== 'ALL' && r.Pozycja !== pos) return false;
    return true;
  }});
  rows.sort((a, b) => cmpVal(a[pSort.col], b[pSort.col], pSort.asc));
  document.getElementById('pCount').innerText = `Piłkarze: ${{rows.length}} / ${{dataPlayers.length}}`;

  const cols = [
    {{ k: 'player', lbl: 'Piłkarz', cls: 'text-left sticky-col' }},
    {{ k: 'team', lbl: 'Klub', cls: 'text-left' }},
    {{ k: 'Pozycja', lbl: 'Poz', cls: 'text-center' }},
    {{ k: 'Cena', lbl: 'Cena', fmt: v => Number(v).toFixed(1) }},
    {{ k: 'chance', lbl: 'Status', cls: 'text-center', isStatus: true, tip: 'P_STATUS' }},
    {{ k: 'apps', lbl: 'Starty' }},
    {{ k: 'min', lbl: 'Min' }},
    {{ k: 'G', lbl: 'G' }},
    {{ k: 'A', lbl: 'A' }},
    {{ k: 'xG', lbl: 'xG' }},
    {{ k: 'NPxG', lbl: 'NPxG' }},
    {{ k: 'xA', lbl: 'xA' }},
    {{ k: 'xGChain', lbl: 'xGChain', tip: 'P_XGCHAIN' }},
    {{ k: 'xG90', lbl: 'xG90' }},
    {{ k: 'xA90', lbl: 'xA90' }},
    {{ k: 'DefCon', lbl: 'DefCon', tip: 'P_DEFCON' }},
    {{ k: 'DefCon90', lbl: 'DefCon/90', tip: 'P_DEFCON', isDC: true }},
    {{ k: 'Obrony', lbl: 'Obrony', tip: 'P_SAVES' }},
    {{ k: 'Bonus', lbl: 'Bonus', tip: 'P_BONUS' }},
    {{ k: 'BPS90', lbl: 'BPS/90', tip: 'P_BONUS' }},
    {{ k: 'ZK', lbl: 'ŻK' }},
    {{ k: 'Posiadanie', lbl: 'Posiadanie', fmt: v => (Number(v) * 100).toFixed(1) + '%' }}
  ];

  let html = '<thead><tr><th>#</th>' + cols.map(c => {{
    const sticky = c.k === 'player' ? 'sticky-col' : '';
    return `<th class="${{sticky}}" onclick="sortPlayers('${{c.k}}')">${{c.lbl}}${{tipIcon(c.tip)}} ${{pSort.col===c.k ? (pSort.asc?'▲':'▼') : ''}}</th>`;
  }}).join('') + '</tr></thead><tbody>';

  rows.forEach((r, idx) => {{
    html += `<tr><td class="text-center">${{idx+1}}</td>`;
    cols.forEach(c => {{
      if (c.isStatus) {{
        const pct = r.status === 'u' ? 'OUT' : (r.chance + '%');
        html += `<td class="text-center">${{statusDotHtml(r.status, r.chance, r.news)}}<span style="font-size:11px;">${{pct}}</span></td>`;
      }} else if (c.isDC) {{
        const hi = (r.Pozycja === 'DEF' && r.DefCon90 >= 10) || ((r.Pozycja === 'MID' || r.Pozycja === 'FWD') && r.DefCon90 >= 12);
        html += `<td class="${{hi ? 'dc-hi' : ''}}">${{Number(r.DefCon90).toFixed(1)}}</td>`;
      }} else {{
        const val = c.fmt ? c.fmt(r[c.k]) : r[c.k];
        html += `<td class="${{c.cls || ''}}">${{escHtml(val)}}</td>`;
      }}
    }});
    html += '</tr>';
  }});
  document.getElementById('tbl-players').innerHTML = html + '</tbody>';
}}
function sortPlayers(c) {{ pSort = {{ col: c, asc: pSort.col === c ? !pSort.asc : false }}; renderPlayers(); }}

// ============================================================================
// 3. FDR
// ============================================================================
function setFdrMode(mode, btn) {{
  fdrMode = mode;
  document.querySelectorAll('#tab-fdr .mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderFDR();
}}
function renderFDR() {{
  let html = `<thead><tr>
    <th class="sticky-col">Klub</th>
    <th>FDR Ogólny${{tipIcon('FDR_ALL')}}</th>
    <th>Atak${{tipIcon('FDR_ATK')}}</th>
    <th>Obrona${{tipIcon('FDR_DEF')}}</th>`;
  gwMeta.forEach(g => {{
    const nowCls = g.gw === nextGwNum ? 'gw-now' : '';
    html += `<th class="${{nowCls}}">${{g.label}}<br><span style="font-weight:400;font-size:10px;">${{g.short_date}}</span></th>`;
  }});
  html += '</tr></thead><tbody>';
  dataFDR.forEach(r => {{
    html += `<tr><td class="text-left sticky-col"><b>${{escHtml(r.Klub)}}</b></td>`;
    html += `<td class="fdr-${{r.FDR_Overall}}">${{r.FDR_Overall}}</td>`;
    html += `<td class="fdr-${{r.FDR_Atak}}">${{r.FDR_Atak}}</td>`;
    html += `<td class="fdr-${{r.FDR_Obrona}}">${{r.FDR_Obrona}}</td>`;
    r.fixtures.forEach(fx => {{ html += `<td class="fdr-${{fx[fdrMode]}}">${{fx.text}}</td>`; }});
    html += '</tr>';
  }});
  document.getElementById('tbl-fdr').innerHTML = html + '</tbody>';
}}

// ============================================================================
// 4. KOKPIT (silnik xPts, paragony w dymkach, SFG, flagi zdrowia, link do Planera)
// ============================================================================
function getKokpitSortValue(row, col) {{
  if (['m1','m2','m3','m4','m5','m6'].includes(col)) return row[col].fdr;
  if (col.startsWith('xgc')) return row['m' + col.slice(3)].xgc;
  return row[col];
}}

function renderKokpit() {{
  const q = normStr(document.getElementById('kSearch').value);
  const qAlt = q.replace(/dj/g, 'd');
  const pos = document.getElementById('kPos').value;
  const maxP = parseFloat(document.getElementById('kPrice').value);
  const trend = document.getElementById('kTrend').value;
  const minSt = document.getElementById('kMinStat').value;
  const scen = document.getElementById('kScen').value;
  const onlyMine = document.getElementById('kOnlyMine').checked;
  const hideInj = document.getElementById('kHideInj').checked;
  const showTech = document.getElementById('kShowTech').checked;

  const mySquadSet = getMySquadSet();
  const myTargetsSet = getMyTargetsSet();

  let rows = dataKokpit.filter(r => {{
    if (q) {{
      const np = normStr(r.Zawodnik);
      const nk = normStr(r.Klub);
      if (!np.includes(q) && !np.includes(qAlt) && !nk.includes(q)) return false;
    }}
    if (pos !== 'ALL' && r.Pozycja !== pos) return false;
    if (r.Cena > maxP) return false;
    if (trend !== 'ALL' && r.Trend_Code !== trend) return false;
    if (minSt !== 'ALL' && r.Status_Min !== minSt) return false;
    if (scen !== 'ALL' && r.Szyfr !== scen) return false;
    if (onlyMine && !mySquadSet.has(r.Zawodnik)) return false;
    if (hideInj && (r.chance === 0 || r.status === 'u')) return false;
    return true;
  }});

  rows.sort((a, b) => cmpVal(getKokpitSortValue(a, kSort.col), getKokpitSortValue(b, kSort.col), kSort.asc));
  document.getElementById('kCount').innerText = `Gracze w Kokpicie: ${{rows.length}} (>=50m sezon lub L5)`;

  let cols = [
    {{ k: 'Zawodnik', lbl: 'Zawodnik', cls: 'text-left sticky-col', isPlayer: true }},
    {{ k: 'Klub', lbl: 'Klub', cls: 'text-left' }},
    {{ k: 'Pozycja', lbl: 'Poz', cls: 'text-center' }},
    {{ k: 'Cena', lbl: 'Cena', fmt: v => Number(v).toFixed(1) }},
    {{ k: 'Minuty', lbl: 'Min' }},
    {{ k: 'xMins', lbl: 'xMins', tip: 'K_XMINS' }},
    {{ k: 'xGI90', lbl: 'xGI90', fmt: v => Number(v).toFixed(2), tip: 'K_XGI90' }},
    {{ k: 'DefCon90', lbl: 'DefCon/90', isDC: true, tip: 'K_DEFCON90' }},
    {{ k: 'Min_L5', lbl: 'Min L5', thCls: 'l5-hdr', cls: 'l5-col', isMinL5: true, tip: 'K_MIN_L5' }},
    {{ k: 'xG_L5', lbl: 'xG L5', thCls: 'l5-hdr', cls: 'l5-col', fmt: v => Number(v).toFixed(2), tip: 'K_XG_L5' }},
    {{ k: 'xGI90_L5', lbl: 'xGI90 L5', thCls: 'l5-hdr', isL5Trend: true, tip: 'K_XGI90_L5' }},
    {{ k: 'xGC90_Team', lbl: 'xGC/90 Drużyny', fmt: v => Number(v).toFixed(2), tip: 'K_XGC_TEAM' }},
    {{ k: 'Szansa_CS', lbl: 'Szansa na CS', fmt: v => v + '%', tip: 'K_CS' }},
    {{ k: 'xPts_GW', lbl: `xPts ${{rollingGWs[0] || 'GW'}}`, thCls: 'xpts-hdr', isXpts1: true, tip: 'K_XPTS_GW' }},
  ];

  if (showTech) {{
    cols.push(
      {{ k: 'xPts_Atk1', lbl: 'xPts Atak', thCls: 'xpts-hdr', fmt: v => Number(v).toFixed(2) }},
      {{ k: 'xPts_Def1', lbl: 'xPts CS/Obr', thCls: 'xpts-hdr', fmt: v => Number(v).toFixed(2) }},
      {{ k: 'xPts_DC1', lbl: 'xPts DefCon', thCls: 'xpts-hdr', fmt: v => Number(v).toFixed(2) }},
      {{ k: 'xPts_Bon1', lbl: 'xPts Bon/K', thCls: 'xpts-hdr', fmt: v => Number(v).toFixed(2) }}
    );
  }}

  cols.push(
    {{ k: 'xPts_6GW', lbl: 'xPts 6GW', thCls: 'xpts-hdr', isXpts6: true, tip: 'K_XPTS_6GW' }},
    {{ k: 'xPts_Val', lbl: 'xPts/£', thCls: 'xpts-hdr', fmt: v => Number(v).toFixed(2), tip: 'K_XPTS_VAL' }},
    {{ k: 'Radar', lbl: 'Radar', cls: 'text-left', tip: 'K_RADAR' }},
    {{ k: 'Werdykt1', lbl: 'Werdykt (Atak)', cls: 'text-left', tip: 'K_W1' }},
    {{ k: 'Ocena_Obrony', lbl: 'Ocena obrony', cls: 'text-left', tip: 'K_OBR' }},
    {{ k: 'Werdykt2', lbl: 'Werdykt (Poz)', cls: 'text-left', tip: 'K_W2' }},
    {{ k: 'Posiadanie', lbl: 'Posiadanie', fmt: v => v + '%' }},
    {{ k: 'Status_EO', lbl: 'Status EO', cls: 'text-left', tip: 'K_EO' }},
    {{ k: 'm1', lbl: rollingGWs[0] || 'Mecz 1', isFix: true }},
    {{ k: 'xgc1', lbl: 'GC Rywala (H/A)', fmt: v => Number(v).toFixed(2), tip: 'K_GC_OPP' }},
    {{ k: 'm2', lbl: rollingGWs[1] || 'Mecz 2', isFix: true }}
  );
  if (showTech) cols.push({{ k: 'xgc2', lbl: 'xGC 2' }});
  cols.push({{ k: 'm3', lbl: rollingGWs[2] || 'Mecz 3', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc3', lbl: 'xGC 3' }});
  cols.push({{ k: 'm4', lbl: rollingGWs[3] || 'Mecz 4', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc4', lbl: 'xGC 4' }});
  cols.push({{ k: 'm5', lbl: rollingGWs[4] || 'Mecz 5', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc5', lbl: 'xGC 5' }});
  cols.push({{ k: 'm6', lbl: rollingGWs[5] || 'Mecz 6', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc6', lbl: 'xGC 6' }});

  cols.push({{ k: 'Status_Min', lbl: 'Status minutowy', cls: 'text-left' }});
  if (showTech) cols.push({{ k: 'Szyfr', lbl: 'Szyfr', cls: 'text-center' }});
  cols.push({{ k: 'Scenariusz', lbl: `Przewidywany Scenariusz (${{rollingGWs[0]}})`, isScen: true, tip: 'K_SCEN' }});

  let html = '<thead><tr><th>#</th>' + cols.map(c => {{
    const sticky = c.k === 'Zawodnik' ? 'sticky-col' : '';
    const extraTh = c.thCls || '';
    return `<th class="${{sticky}} ${{extraTh}}" onclick="sortKokpit('${{c.k}}')">${{c.lbl}}${{tipIcon(c.tip)}} ${{kSort.col===c.k ? (kSort.asc?'▲':'▼') : ''}}</th>`;
  }}).join('') + '</tr></thead><tbody>';

  rows.forEach((r, idx) => {{
    html += `<tr><td class="text-center">${{idx+1}}</td>`;
    cols.forEach(c => {{
      if (c.isPlayer) {{
        const dot = statusDotHtml(r.status, r.chance, r.news);
        const mine = mySquadSet.has(r.Zawodnik)
          ? `<span class="tag-icon" title="Ten zawodnik jest w Twoim składzie w Planerze">👕</span>`
          : '';
        const penTag = r.is_pen
          ? `<span class="tag-icon" title="1. wykonawca rzutów karnych (FPL API)">🎯</span>`
          : '';
        const spTag = r.is_setp
          ? `<span class="tag-icon" title="1. wykonawca rzutów rożnych / wolnych (FPL API)">🚩</span>`
          : '';
        const inBtn = (!mySquadSet.has(r.Zawodnik) && !myTargetsSet.has(r.Zawodnik))
          ? `<button class="btn-mini-in" data-p="${{escHtml(r.Zawodnik)}}" title="Dodaj do Celów IN w Planerze" onclick="event.stopPropagation(); addTargetFromKokpit(this.dataset.p)">+</button>`
          : (myTargetsSet.has(r.Zawodnik) ? `<span class="tag-icon" title="Już na liście Celów IN w Planerze">🎯IN</span>` : '');
        html += `<td class="${{c.cls}}">${{dot}}${{escHtml(r.Zawodnik)}}${{mine}}${{penTag}}${{spTag}}${{inBtn}}</td>`;
      }} else if (c.isXpts1) {{
        const note = r.chance < 100 ? `Uwzględniono flagę dostępności: ${{r.chance}}%` : `xMins bazowe: ${{r.xMins}} min`;
        const tipHtml = encodeURIComponent(buildXptsReceiptHtml(r.xPts_GW_Brk, `${{r.Zawodnik}} — ${{rollingGWs[0]}} (${{r.m1.text || 'BLANK'}})`, r.xPts_GW, note, r.xPts_GW_SD));
        html += `<td class="xpts-cell" data-tip-html="${{tipHtml}}" onclick="event.stopPropagation(); toggleInlineTip(this)" onmouseenter="showInlineTip(this)" onmouseleave="hideTip()">${{r.xPts_GW.toFixed(2)}}</td>`;
      }} else if (c.isXpts6) {{
        const tipHtml = encodeURIComponent(buildXpts6Html(r.xPts_6_List, r.Zawodnik, r.xPts_6GW));
        html += `<td class="xpts-cell" data-tip-html="${{tipHtml}}" onclick="event.stopPropagation(); toggleInlineTip(this)" onmouseenter="showInlineTip(this)" onmouseleave="hideTip()">${{r.xPts_6GW.toFixed(2)}}</td>`;
      }} else if (c.isDC) {{
        const hi = (r.Pozycja === 'DEF' && r.DefCon90 >= 10) || ((r.Pozycja === 'MID' || r.Pozycja === 'FWD') && r.DefCon90 >= 12);
        html += `<td class="${{hi ? 'dc-hi' : ''}}">${{Number(r.DefCon90).toFixed(1)}}</td>`;
      }} else if (c.isFix) {{
        const fx = r[c.k];
        html += `<td class="fdr-${{fx.fdr}}" title="Prognoza w tym meczu: ${{Number(fx.xp || 0).toFixed(2)}} xPts">${{fx.text}}</td>`;
      }} else if (c.isScen) {{
        html += `<td class="scen-${{r.Szyfr}}">${{r.Scenariusz}}</td>`;
      }} else if (c.isL5Trend) {{
        const tip = `Sezon xGI90: ${{r.xGI90.toFixed(2)}} | Ostatnie 5 GW xGI90: ${{r.xGI90_L5.toFixed(2)}} (${{r.Min_L5}} min)`;
        html += `<td class="trend-${{r.Trend_Code}}" title="${{tip}}">${{r.xGI90_L5.toFixed(2)}} ${{r.Trend_Icon}}</td>`;
      }} else if (c.isMinL5) {{
        const warnCls = r.Min_L5 < 175 ? 'min-warn' : 'l5-col';
        html += `<td class="${{warnCls}}" title="Suma minut w ostatnich 5 GW (${{Math.round(r.Min_L5/5)}} min/mecz)">${{r.Min_L5}}</td>`;
      }} else {{
        const raw = getKokpitSortValue(r, c.k);
        html += `<td class="${{c.cls || ''}}">${{escHtml(c.fmt ? c.fmt(raw) : raw)}}</td>`;
      }}
    }});
    html += '</tr>';
  }});
  document.getElementById('tbl-kokpit').innerHTML = html + '</tbody>';
}}
function sortKokpit(c) {{ kSort = {{ col: c, asc: kSort.col === c ? !kSort.asc : false }}; renderKokpit(); }}

// ============================================================================
// 5. SKANER WILDCARD I FREE HIT
// ============================================================================
function verdClass(v) {{
  if (v.includes('💣')) return 'verd-bomb';
  if (v.includes('✅')) return 'verd-ok';
  if (v.includes('⚠️')) return 'verd-warn';
  return 'text-left';
}}
function renderScanner() {{
  const scope = document.getElementById('sScope').value;
  const rows = scope === 'FUTURE' ? dataScanner.filter(r => r.GW >= nextGwNum) : dataScanner;
  let html = `<thead><tr>
    <th>GW</th>
    <th>Data</th>
    <th>Skaner Free Hit${{tipIcon('S_FH_SC')}}</th>
    <th>Werdykt Free Hit${{tipIcon('S_FH_VR')}}</th>
    <th>Skaner Wildcard (5 GW)${{tipIcon('S_WC_SC')}}</th>
    <th>Werdykt Wildcard${{tipIcon('S_WC_VR')}}</th>
    <th>Top 5 klubów w tej kolejce</th>
  </tr></thead><tbody>`;
  rows.forEach(r => {{
    const hi = r.GW === nextGwNum ? 'gw-highlight' : '';
    html += `<tr class="${{hi}}">
      <td class="text-center"><b>GW${{r.GW}}</b></td>
      <td class="text-center">${{r.Data}}</td>
      <td><b>${{r.FH_Score.toFixed(2)}}</b></td>
      <td class="${{verdClass(r.FH_Verdict)}}">${{r.FH_Verdict}}</td>
      <td><b>${{r.WC_Score.toFixed(2)}}</b></td>
      <td class="${{verdClass(r.WC_Verdict)}}">${{r.WC_Verdict}}</td>
      <td class="text-left" style="font-size:11.5px; color:#444;">${{escHtml(r.Top5_Kluby)}}</td>
    </tr>`;
  }});
  document.getElementById('tbl-scanner').innerHTML = html + '</tbody>';

  let cHtml = '<thead><tr><th class="sticky-col">Klub (Tabela chipów)</th>';
  gwMeta.forEach(g => {{ cHtml += `<th class="${{g.gw===nextGwNum?'gw-now':''}}">${{g.label}}</th>`; }});
  cHtml += '</tr></thead><tbody>';
  dataChips.forEach(r => {{
    cHtml += `<tr><td class="text-left sticky-col"><b>${{escHtml(r.Klub)}}</b></td>`;
    r.scores.forEach(sc => {{
      let bg = sc >= 2.2 ? 'background:#d4edda;font-weight:700;' : (sc >= 1.7 ? 'background:#eef9f0;' : (sc <= 0.9 ? 'color:#999;' : ''));
      cHtml += `<td style="${{bg}}">${{sc.toFixed(2)}}</td>`;
    }});
    cHtml += '</tr>';
  }});
  document.getElementById('tbl-chips').innerHTML = cHtml + '</tbody>';
}}

// ============================================================================
// 6. PLANER (z pełną integracją xPts, prognozą XI, kapitanem i Auto-ławką xPts)
// ============================================================================
function getPlayerGwXptsObj(playerName, gw) {{
  const rec = planerXptsMap[playerName];
  if (!rec || !rec.gws) return {{ t: 0.0, b: [0,0,0,0,0,0,0,0,0], v: 0.0, cv: 0.0 }};
  return rec.gws[String(gw)] || {{ t: 0.0, b: [0,0,0,0,0,0,0,0,0], v: 0.0, cv: 0.0 }};
}}

function getPlayer6GwXpts(playerName) {{
  const rec = planerXptsMap[playerName];
  return rec ? Number(rec.x6 || 0) : 0.0;
}}

function sortSquadByPosition() {{
  const indexed = planerState.squad.map((row, i) => {{
    const pInfo = findExactPlayer(row.player);
    const rank = pInfo ? (POS_RANK[pInfo.Pozycja] || 5) : 6;
    return {{ row, rank, origIdx: i }};
  }});
  indexed.sort((a, b) => a.rank - b.rank || a.origIdx - b.origIdx);
  planerState.squad = indexed.map(x => x.row);
}}

let ddCtx = {{ inputEl: null, section: null, idx: null, matches: [], activeIdx: 0, picked: false }};

function searchCatalog(query) {{
  const q = normStr(query);
  const qAlt = q.replace(/dj/g, 'd');
  if (!q) return dataCatalog.slice(0, 25);
  const scored = [];
  for (const p of dataCatalog) {{
    const full = normStr(p.player);
    const web = normStr(p.web_name);
    const club = normStr(p.team_short);
    if (full.startsWith(q) || web.startsWith(q) || full.startsWith(qAlt) || web.startsWith(qAlt)) scored.push({{ p, score: 1 }});
    else if (full.includes(' ' + q) || full.includes(' ' + qAlt)) scored.push({{ p, score: 2 }});
    else if (full.includes(q) || web.includes(q) || full.includes(qAlt) || web.includes(qAlt)) scored.push({{ p, score: 3 }});
    else if (club === q) scored.push({{ p, score: 4 }});
  }}
  scored.sort((a, b) => a.score - b.score || a.p.player.localeCompare(b.p.player));
  return scored.slice(0, 25).map(x => x.p);
}}

function positionDropdown(inputEl) {{
  const menu = document.getElementById('playerDropdownMenu');
  const rect = inputEl.getBoundingClientRect();
  const spaceBelow = window.innerHeight - rect.bottom;
  menu.style.left = Math.min(rect.left, window.innerWidth - 305) + 'px';
  if (spaceBelow < 220 && rect.top > 240) {{
    menu.style.top = 'auto';
    menu.style.bottom = (window.innerHeight - rect.top + 2) + 'px';
  }} else {{
    menu.style.bottom = 'auto';
    menu.style.top = (rect.bottom + 2) + 'px';
  }}
}}

function openPlayerDropdown(inputEl, section, idx) {{
  ddCtx.inputEl = inputEl;
  ddCtx.section = section;
  ddCtx.idx = idx;
  ddCtx.picked = false;
  ddCtx.activeIdx = 0;
  renderPlayerDropdown(inputEl.value);
}}

function renderPlayerDropdown(query) {{
  const menu = document.getElementById('playerDropdownMenu');
  if (!ddCtx.inputEl) {{ menu.style.display = 'none'; return; }}
  ddCtx.matches = searchCatalog(query);
  if (ddCtx.activeIdx >= ddCtx.matches.length) ddCtx.activeIdx = 0;
  positionDropdown(ddCtx.inputEl);

  if (!ddCtx.matches.length) {{
    menu.innerHTML = `<div class="dd-empty">❌ Brak takiego zawodnika w bazie FPL</div>`;
    menu.style.display = 'block';
    return;
  }}

  menu.innerHTML = ddCtx.matches.map((p, i) => `
    <div class="dd-item ${{i === ddCtx.activeIdx ? 'active' : ''}}"
         onmousedown="event.preventDefault(); selectDropdownPlayer(${{i}})">
      <span><b>${{escHtml(p.player)}}</b></span>
      <span class="dd-meta">${{p.team_short}} · ${{p.Pozycja}} · £${{p.Cena.toFixed(1)}}</span>
    </div>
  `).join('');
  menu.style.display = 'block';
}}

function selectDropdownPlayer(matchIdx) {{
  const chosen = ddCtx.matches[matchIdx];
  if (!chosen || !ddCtx.section) return;
  const sec = ddCtx.section;
  ddCtx.picked = true;
  planerState[sec][ddCtx.idx].player = chosen.player;
  if (sec === 'squad') {{
    sortSquadByPosition();
    lastPlacedPlayer = chosen.player;
    showToast(`✅ ${{chosen.player}} trafił do strefy ${{chosen.Pozycja}}`);
  }}
  savePlanerState();
  closePlayerDropdown();
  renderPlaner();
  renderKokpit();
}}

function handleComboKeydown(ev, section, idx) {{
  const menu = document.getElementById('playerDropdownMenu');
  const isOpen = menu.style.display === 'block';
  if (ev.key === 'ArrowDown') {{
    ev.preventDefault();
    if (!isOpen) openPlayerDropdown(ev.target, section, idx);
    else if (ddCtx.matches.length) {{
      ddCtx.activeIdx = (ddCtx.activeIdx + 1) % ddCtx.matches.length;
      renderPlayerDropdown(ev.target.value);
    }}
  }} else if (ev.key === 'ArrowUp') {{
    ev.preventDefault();
    if (isOpen && ddCtx.matches.length) {{
      ddCtx.activeIdx = (ddCtx.activeIdx - 1 + ddCtx.matches.length) % ddCtx.matches.length;
      renderPlayerDropdown(ev.target.value);
    }}
  }} else if (ev.key === 'Enter') {{
    ev.preventDefault();
    if (ev.target.value.trim() === '') {{
      ddCtx.picked = true;
      planerState[section][idx].player = '';
      if (section === 'squad') sortSquadByPosition();
      savePlanerState();
      closePlayerDropdown();
      renderPlaner();
      renderKokpit();
    }} else if (ddCtx.matches.length) {{
      selectDropdownPlayer(ddCtx.activeIdx);
    }} else {{
      ev.target.classList.add('invalid-flash');
      showToast('⚠️ Wybierz zawodnika z rozwijanej listy — brak takiego piłkarza w bazie.');
    }}
  }} else if (ev.key === 'Escape') {{
    ev.preventDefault();
    ev.target.value = planerState[section][idx].player || '';
    closePlayerDropdown();
    ev.target.blur();
  }}
}}

function handleComboBlur(inputEl, section, idx) {{
  setTimeout(() => {{
    if (ddCtx.picked) {{ ddCtx.picked = false; return; }}
    const typed = inputEl.value.trim();
    const prevVal = planerState[section][idx].player || '';
    closePlayerDropdown();

    if (typed === '') {{
      if (prevVal !== '') {{
        planerState[section][idx].player = '';
        if (section === 'squad') sortSquadByPosition();
        savePlanerState();
        renderPlaner();
        renderKokpit();
      }}
      return;
    }}
    const exact = findExactPlayer(typed);
    if (exact) {{
      if (exact.player !== prevVal) {{
        planerState[section][idx].player = exact.player;
        if (section === 'squad') {{
          sortSquadByPosition();
          lastPlacedPlayer = exact.player;
          showToast(`✅ ${{exact.player}} trafił do strefy ${{exact.Pozycja}}`);
        }}
        savePlanerState();
        renderPlaner();
        renderKokpit();
      }} else {{
        inputEl.value = exact.player;
      }}
    }} else {{
      inputEl.value = prevVal;
      inputEl.classList.add('invalid-flash');
      setTimeout(() => inputEl.classList.remove('invalid-flash'), 900);
      showToast('⚠️ Wybierz piłkarza z rozwijanej listy (kliknięciem lub Enterem).');
    }}
  }}, 120);
}}

function closePlayerDropdown() {{
  document.getElementById('playerDropdownMenu').style.display = 'none';
  ddCtx.inputEl = null;
}}

window.addEventListener('resize', closePlayerDropdown);
document.addEventListener('scroll', (e) => {{
  if (e.target && e.target.id === 'playerDropdownMenu') return;
  closePlayerDropdown();
}}, true);

function getPosFixture(teamShort, pos, gw) {{
  const fx = (teamFixShort[teamShort] || {{}})[String(gw)];
  if (!fx) return {{ text: '—', fdr: 0 }};
  const fdr = (pos === 'MID' || pos === 'FWD') ? fx.fdr_atk : fx.fdr_def;
  return {{ text: fx.text, fdr: fdr }};
}}

function calcPlanerDecision(row, pInfo, isSquad) {{
  if (!row.player || !row.player.trim()) return {{ text: '', cls: '', tip: '' }};
  if (row.status === '💎 Premium') return {{ text: 'Trzymaj (Premium)', cls: 'dec-hold', tip: 'Status Premium' }};
  if (isSquad && row.status === '🪵 Słup') return {{ text: 'Trzymaj (Słup na ławce)', cls: 'dec-hold', tip: 'Status Słup na ławce' }};
  if (!pInfo) return {{ text: 'Wybierz z listy', cls: '', tip: 'Wybierz poprawnego zawodnika z listy' }};

  const fxs = planerGWs.map(gw => ({{ gw, ...getPosFixture(pInfo.team_short, pInfo.Pozycja, gw) }}));
  for (let i = 0; i <= fxs.length - 3; i++) {{
    if (fxs[i].fdr >= 4 && fxs[i+1].fdr >= 4 && fxs[i+2].fdr >= 4) {{
      const reason = `3 trudne pod rząd: ${{fxs[i].text}}, ${{fxs[i+1].text}}, ${{fxs[i+2].text}}`;
      if (i === 0) return {{ text: `🚨 Sprzedaj TERAZ (GW${{fxs[0].gw}})`, cls: 'dec-now', tip: reason }};
      if (i === 1) return {{ text: `⏳ Sprzedaj przed GW${{fxs[1].gw}}`, cls: 'dec-soon', tip: reason }};
      return {{ text: `📅 Wymień przed GW${{fxs[i].gw}}`, cls: 'dec-plan', tip: reason }};
    }}
  }}
  return {{ text: '✅ Bezpieczny', cls: 'dec-ok', tip: 'Brak serii 3 trudnych meczów (>=4) w 12 GW' }};
}}

function isBenchInGw(playerName, gw) {{
  return (planerState.benchMap[String(gw)] || []).includes(playerName);
}}
function toggleBenchInGw(playerName, gw) {{
  if (!playerName) return;
  const key = String(gw);
  if (!planerState.benchMap[key]) planerState.benchMap[key] = [];
  const idx = planerState.benchMap[key].indexOf(playerName);
  if (idx >= 0) planerState.benchMap[key].splice(idx, 1);
  else planerState.benchMap[key].push(playerName);
  savePlanerState();
  renderPlaner();
}}
function setPlanerCellMode(mode, btn) {{
  planerCellMode = mode;
  ['pViewTxt', 'pViewNum', 'pViewXp'].forEach(id => document.getElementById(id).classList.remove('active'));
  btn.classList.add('active');
  renderPlaner();
}}
function updatePlanerField(section, idx, field, val) {{
  planerState[section][idx][field] = val;
  savePlanerState();
  renderPlaner();
}}
function addPlanerRow(section) {{
  if (section === 'squad') planerState.squad.push({{ player: '', status: '', outGw: '' }});
  else planerState.targets.push({{ player: '', status: '', inGw: String(nextGwNum) }});
  savePlanerState();
  renderPlaner();
  setTimeout(() => {{
    const inputs = document.querySelectorAll(`input[data-section="${{section}}"]`);
    if (inputs.length) inputs[inputs.length - 1].focus();
  }}, 30);
}}
function deletePlanerRow(section, idx) {{
  planerState[section].splice(idx, 1);
  savePlanerState();
  renderPlaner();
  renderKokpit();
}}
function promoteTargetToSquad(idx) {{
  const t = planerState.targets[idx];
  if (!t || !t.player) return;
  const pInfo = findExactPlayer(t.player);
  planerState.squad.push({{ player: t.player, status: t.status, outGw: '' }});
  planerState.targets.splice(idx, 1);
  sortSquadByPosition();
  lastPlacedPlayer = t.player;
  savePlanerState();
  renderPlaner();
  renderKokpit();
  showToast(`⬆️ ${{t.player}} wskoczył prosto do strefy ${{pInfo ? pInfo.Pozycja : 'składu'}}!`);
}}
function exportPlaner() {{
  const txt = JSON.stringify(planerState, null, 2);
  if (navigator.clipboard) navigator.clipboard.writeText(txt).catch(() => {{}});
  prompt("Skopiuj poniższy JSON (został też skopiowany do schowka):", txt);
}}
function importPlaner() {{
  const raw = prompt("Wklej wcześniej wyeksportowany JSON Planera:");
  if (!raw) return;
  try {{
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed.squad) && Array.isArray(parsed.targets)) {{
      parsed.benchMap = parsed.benchMap || {{}};
      migrateSavedNames(parsed);
      planerState = parsed;
      sortSquadByPosition();
      savePlanerState();
      renderPlaner();
      renderKokpit();
      showToast("✅ Zaimportowano stan Planera!");
    }} else alert("❌ Nieprawidłowy format danych.");
  }} catch (e) {{ alert("❌ Błąd parsowania JSON: " + e.message); }}
}}
function resetPlaner() {{
  if (!confirm("Przywrócić domyślny skład i cele?")) return;
  planerState = {{
    squad: JSON.parse(JSON.stringify(defaultSquad)),
    targets: JSON.parse(JSON.stringify(defaultTargets)),
    benchMap: {{}}
  }};
  sortSquadByPosition();
  savePlanerState();
  renderPlaner();
  renderKokpit();
}}

function buildPlanerRowsHtml(section) {{
  const isSquad = section === 'squad';
  const rows = planerState[section];
  let html = '';
  let prevZone = null;

  rows.forEach((r, idx) => {{
    const pInfo = findExactPlayer(r.player);
    const teamShort = pInfo ? pInfo.team_short : '—';
    const pos = pInfo ? pInfo.Pozycja : '—';
    const price = pInfo ? pInfo.Cena.toFixed(1) : '—';
    const x6 = pInfo ? getPlayer6GwXpts(pInfo.player).toFixed(1) : '—';
    const dec = calcPlanerDecision(r, pInfo, isSquad);
    const boundGw = parseInt(isSquad ? r.outGw : r.inGw, 10);

    let rowClasses = [];
    if (isSquad) {{
      const zone = pInfo ? pInfo.Pozycja : 'NEW';
      rowClasses.push('zone-' + zone);
      if (prevZone !== null && prevZone !== zone) rowClasses.push('zone-border-top');
      if (idx === rows.length - 1) rowClasses.push('zone-border-bottom');
      prevZone = zone;
      if (lastPlacedPlayer && pInfo && pInfo.player === lastPlacedPlayer) rowClasses.push('just-placed');
    }} else {{
      rowClasses.push('zone-NEW');
    }}

    const safeName = escHtml(r.player || '');
    const dotHtml = pInfo ? statusDotHtml(pInfo.status, pInfo.chance, pInfo.news) : '';
    const stOpts = ['', '💎 Premium', '🪵 Słup', '♻️ Rotacja'].map(s =>
      `<option value="${{s}}" ${{r.status===s?'selected':''}}>${{s || '—'}}</option>`
    ).join('');

    html += `<tr class="${{rowClasses.join(' ')}}">
      <td class="text-left sticky-col">
        <div class="p-combo-wrap">
          ${{dotHtml}}
          <input class="p-input" data-section="${{section}}" type="text" autocomplete="off" value="${{safeName}}" placeholder="Wpisz i wybierz z listy..."
                 onfocus="this.select(); openPlayerDropdown(this, '${{section}}', ${{idx}})"
                 oninput="renderPlayerDropdown(this.value)"
                 onkeydown="handleComboKeydown(event, '${{section}}', ${{idx}})"
                 onblur="handleComboBlur(this, '${{section}}', ${{idx}})">
        </div>
      </td>
      <td class="text-center">
        <select class="p-sel" onchange="updatePlanerField('${{section}}', ${{idx}}, 'status', this.value)">${{stOpts}}</select>
      </td>
      <td class="text-center"><b>${{teamShort}}</b></td>
      <td class="text-center"><b>${{pos}}</b></td>
      <td>${{price}}</td>
      <td class="xpts-cell" style="cursor:default; text-decoration:none;">${{x6}}</td>`;

    planerGWs.forEach(gw => {{
      const fx = pInfo ? getPosFixture(pInfo.team_short, pInfo.Pozycja, gw) : {{ text: '—', fdr: 0 }};
      const xpObj = pInfo ? getPlayerGwXptsObj(pInfo.player, gw) : {{ t: 0, b: [0,0,0,0,0,0,0,0,0] }};
      const inactive = !isNaN(boundGw) && (isSquad ? (gw >= boundGw) : (gw < boundGw));
      const benched = !inactive && pInfo && isBenchInGw(pInfo.player, gw);

      let disp, colorCls;
      if (planerCellMode === 'num') {{
        disp = fx.fdr || '—';
        colorCls = 'fdr-' + fx.fdr;
      }} else if (planerCellMode === 'xpts') {{
        disp = pInfo ? xpObj.t.toFixed(1) : '—';
        colorCls = pInfo ? xptsTierClass(xpObj.t) : 'fdr-0';
      }} else {{
        disp = fx.text;
        colorCls = 'fdr-' + fx.fdr;
      }}

      const badge = benched ? `<span class="badge-mini">Ł</span>` : '';
      const cls = `cell-fix ${{colorCls}} ${{inactive ? 'cell-inactive' : ''}} ${{benched ? 'cell-bench' : ''}}`;
      const tipTxt = pInfo ? `${{fx.text}} · Prognoza: ${{xpObj.t.toFixed(2)}} xPts (kliknij: przełącz XI / Ławka w GW${{gw}})` : '';
      const dataAttrs = pInfo
        ? `data-player="${{escHtml(pInfo.player)}}" data-gw="${{gw}}" onclick="toggleBenchInGw(this.dataset.player, Number(this.dataset.gw))"`
        : '';
      html += `<td class="${{cls}}" ${{dataAttrs}} title="${{escHtml(tipTxt)}}">${{disp}}${{badge}}</td>`;
    }});

    const gwField = isSquad ? 'outGw' : 'inGw';
    const gwVal = escHtml(r[gwField] || '');
    const gwPrefix = isSquad ? 'OUT' : 'IN';
    const extraBtn = !isSquad ? `<button class="act-btn" title="Przenieś do właściwej strefy w składzie" onclick="promoteTargetToSquad(${{idx}})">⬆️</button> ` : '';

    html += `
      <td class="${{dec.cls}}" title="${{escHtml(dec.tip)}}">${{dec.text}}</td>
      <td class="text-center">
        <input class="p-gw-in" type="number" min="1" max="38" value="${{gwVal}}" placeholder="${{gwPrefix}}"
               title="${{isSquad ? 'Numer kolejki sprzedaży (OUT)' : 'Numer kolejki zakupu (IN)'}}"
               onchange="updatePlanerField('${{section}}', ${{idx}}, '${{gwField}}', this.value)">
      </td>
      <td class="text-center">${{extraBtn}}<button class="act-btn danger" title="Usuń wiersz" onclick="deletePlanerRow('${{section}}', ${{idx}})">✕</button></td>
    </tr>`;
  }});
  return html;
}}

function renderPlanerMainTable() {{
  sortSquadByPosition();
  const totalCols = 6 + planerGWs.length + 3;

  const counts = {{ GKP: 0, DEF: 0, MID: 0, FWD: 0 }};
  planerState.squad.forEach(r => {{
    const p = findExactPlayer(r.player);
    if (p && counts[p.Pozycja] !== undefined) counts[p.Pozycja]++;
  }});
  const pillsHtml = `<span class="pos-pills">
    <span class="pos-pill p-GKP">GKP: ${{counts.GKP}}</span>
    <span class="pos-pill p-DEF">DEF: ${{counts.DEF}}</span>
    <span class="pos-pill p-MID">MID: ${{counts.MID}}</span>
    <span class="pos-pill p-FWD">FWD: ${{counts.FWD}}</span>
  </span>`;

  let html = `<thead><tr>
    <th class="sticky-col">Zawodnik (wybór z listy)</th>
    <th>Status${{tipIcon('PLR_STATUS')}}</th>
    <th>Klub</th><th>Poz</th><th>Cena</th>
    <th class="xpts-hdr">xPts 6GW${{tipIcon('K_XPTS_6GW')}}</th>`;
  planerGWs.forEach(gw => {{
    const hi = gw === selectedLineupGw ? 'gw-now' : '';
    html += `<th class="${{hi}}" onclick="selectLineupGw(${{gw}})" title="Kliknij, aby zobaczyć przymiarkę na GW${{gw}}">GW${{gw}}</th>`;
  }});
  html += `<th>Decyzja${{tipIcon('PLR_DEC')}}</th><th>OUT / IN${{tipIcon('PLR_OUTIN')}}</th><th>Akcje</th></tr></thead><tbody>`;

  html += `<tr class="sec-divider-row"><td colspan="${{totalCols}}">👕 TWÓJ SKŁAD (podzielony na strefy pozycji) ${{pillsHtml}}</td></tr>`;
  html += buildPlanerRowsHtml('squad');

  html += `<tr class="sec-divider-row"><td colspan="${{totalCols}}">🎯 CELE TRANSFEROWE — IN (kliknij ⬆️, aby przenieść gracza prosto do jego strefy pozycji wyżej)</td></tr>`;
  html += buildPlanerRowsHtml('targets');

  document.getElementById('tbl-planer-main').innerHTML = html + '</tbody>';
  lastPlacedPlayer = null;
}}

function getActivePlayersForGw(gw) {{
  const activePlayers = [];
  const seen = new Set();

  planerState.squad.forEach(r => {{
    const outGw = parseInt(r.outGw, 10);
    if (!isNaN(outGw) && gw >= outGw) return;
    const pInfo = findExactPlayer(r.player);
    if (pInfo && !seen.has(pInfo.player)) {{
      seen.add(pInfo.player);
      activePlayers.push({{ ...pInfo, status_planer: r.status, source: 'Skład' }});
    }}
  }});
  planerState.targets.forEach(r => {{
    const inGw = parseInt(r.inGw, 10);
    if (isNaN(inGw) || gw < inGw) return;
    const pInfo = findExactPlayer(r.player);
    if (pInfo && !seen.has(pInfo.player)) {{
      seen.add(pInfo.player);
      activePlayers.push({{ ...pInfo, status_planer: r.status, source: 'IN' }});
    }}
  }});
  return activePlayers;
}}

// Optymalna Auto-ławka po najwyższej sumie xPts z zachowaniem legalnej formacji FPL
function autoPickBenchForGw() {{
  const gw = selectedLineupGw;
  const active = getActivePlayersForGw(gw).map(p => {{
    const xpObj = getPlayerGwXptsObj(p.player, gw);
    const isSlup = p.status_planer === '🪵 Słup';
    let effScore = xpObj.t;
    if (xpObj.t <= 0.05) effScore = -100.0;
    else if (isSlup) effScore = xpObj.t - 2.0;
    return {{ ...p, xp: xpObj.t, effScore }};
  }});

  const gkps = active.filter(p => p.Pozycja === 'GKP').sort((a, b) => b.effScore - a.effScore || b.Cena - a.Cena);
  const defs = active.filter(p => p.Pozycja === 'DEF').sort((a, b) => b.effScore - a.effScore || b.Cena - a.Cena);
  const mids = active.filter(p => p.Pozycja === 'MID').sort((a, b) => b.effScore - a.effScore || b.Cena - a.Cena);
  const fwds = active.filter(p => p.Pozycja === 'FWD').sort((a, b) => b.effScore - a.effScore || b.Cena - a.Cena);

  const picked = new Set();
  if (gkps.length >= 1) picked.add(gkps[0].player);

  let bestScore = -1e9;
  let bestOut = [];
  for (let d = 3; d <= Math.min(5, defs.length); d++) {{
    for (let m = 2; m <= Math.min(5, mids.length); m++) {{
      const f = 10 - d - m;
      if (f < 1 || f > Math.min(3, fwds.length)) continue;
      const cand = [...defs.slice(0, d), ...mids.slice(0, m), ...fwds.slice(0, f)];
      const sc = cand.reduce((s, x) => s + x.effScore, 0);
      if (sc > bestScore) {{
        bestScore = sc;
        bestOut = cand;
      }}
    }}
  }}

  if (bestOut.length) {{
    bestOut.forEach(x => picked.add(x.player));
  }} else {{
    const outAll = active.filter(p => p.Pozycja !== 'GKP').sort((a, b) => b.effScore - a.effScore);
    outAll.slice(0, 10).forEach(x => picked.add(x.player));
  }}

  planerState.benchMap[String(gw)] = active.filter(p => !picked.has(p.player)).map(p => p.player);
  savePlanerState();
  renderPlaner();
  showToast(`⚡ Ustawiono optymalną XI pod najwyższe xPts na GW${{gw}}!`);
}}

function selectLineupGw(gw) {{
  selectedLineupGw = gw;
  renderPlaner();
}}

function renderLineupTables() {{
  let pills = '<b style="margin-right:4px;font-size:12px;">Wybierz kolejkę:</b>';
  planerGWs.forEach(gw => {{
    pills += `<button class="gw-pill ${{gw===selectedLineupGw?'active':''}}" onclick="selectLineupGw(${{gw}})">GW${{gw}}</button>`;
  }});
  document.getElementById('planerGwPills').innerHTML = pills;

  const activePlayers = getActivePlayersForGw(selectedLineupGw);
  const xi = [], bench = [];

  activePlayers.forEach(p => {{
    const fx = getPosFixture(p.team_short, p.Pozycja, selectedLineupGw);
    const xpObj = getPlayerGwXptsObj(p.player, selectedLineupGw);
    const item = {{ ...p, fx, xp: xpObj.t, brk: xpObj.b, v: xpObj.v || 0, cv: xpObj.cv || 0 }};
    if (isBenchInGw(p.player, selectedLineupGw)) bench.push(item);
    else xi.push(item);
  }});
  xi.sort((a, b) => POS_RANK[a.Pozycja] - POS_RANK[b.Pozycja] || b.xp - a.xp);
  bench.sort((a, b) => POS_RANK[a.Pozycja] - POS_RANK[b.Pozycja] || b.xp - a.xp);

  const capPlayer = xi.length ? xi.reduce((best, cur) => (cur.xp > best.xp ? cur : best), xi[0]) : null;

  function buildMiniTable(list, isXi) {{
    let h = `<thead><tr><th>Poz</th><th>Zawodnik</th><th>Klub</th><th>Cena</th><th>GW${{selectedLineupGw}}</th><th class="xpts-hdr">xPts</th><th>Akcja</th></tr></thead><tbody>`;
    if (!list.length) {{
      h += `<tr><td colspan="7" style="color:#888;padding:12px;">Brak zawodników</td></tr>`;
    }} else {{
      let prevP = null;
      list.forEach(p => {{
        const dot = statusDotHtml(p.status, p.chance, p.news);
        const inTag = p.source === 'IN' ? `<span style="font-size:10px;background:#107c41;color:#fff;padding:1px 4px;border-radius:3px;margin-right:4px;">IN</span>` : '';
        const capTag = (isXi && capPlayer && capPlayer.player === p.player && p.xp > 0) ? `<span class="cap-badge" title="Sugerowany kapitan (najwyższe xPts w XI)">C</span>` : '';
        const btnLbl = isXi ? '→ Ławka' : '← Do XI';
        const sepCls = (prevP !== null && prevP !== p.Pozycja) ? 'zone-border-top' : '';
        prevP = p.Pozycja;
        const note = (selectedLineupGw === nextGwNum && p.chance < 100) ? `Flaga dostępności: ${{p.chance}}%` : '';
        const tipHtml = encodeURIComponent(buildXptsReceiptHtml(p.brk, `${{p.player}} — GW${{selectedLineupGw}} (${{p.fx.text}})`, p.xp, note, Math.sqrt(p.v || 0)));
        h += `<tr class="zone-${{p.Pozycja}} ${{sepCls}}">
          <td><b>${{p.Pozycja}}</b></td>
          <td class="text-left">${{dot}}${{inTag}}${{escHtml(p.player)}}${{capTag}}</td>
          <td>${{p.team_short}}</td>
          <td>£${{p.Cena.toFixed(1)}}</td>
          <td class="fdr-${{p.fx.fdr}} cell-fix">${{p.fx.text}}</td>
          <td class="xpts-cell" data-tip-html="${{tipHtml}}" onclick="event.stopPropagation(); toggleInlineTip(this)" onmouseenter="showInlineTip(this)" onmouseleave="hideTip()">${{p.xp.toFixed(2)}}</td>
          <td><button class="act-btn" data-player="${{escHtml(p.player)}}" data-gw="${{selectedLineupGw}}" onclick="toggleBenchInGw(this.dataset.player, Number(this.dataset.gw))">${{btnLbl}}</button></td>
        </tr>`;
      }});
    }}
    return h + '</tbody>';
  }}

  document.getElementById('tbl-lineup-xi').innerHTML = buildMiniTable(xi, true);
  document.getElementById('tbl-lineup-bench').innerHTML = buildMiniTable(bench, false);
  document.getElementById('xiCountBadge').innerText = `${{xi.length}} / 11`;
  document.getElementById('benchCountBadge').innerText = `${{bench.length}} graczy`;
  document.getElementById('lineupGwInfo').innerText = `Aktywna kadra w GW${{selectedLineupGw}}: ${{activePlayers.length}} graczy`;

  const cntGKP = xi.filter(x => x.Pozycja === 'GKP').length;
  const cntDEF = xi.filter(x => x.Pozycja === 'DEF').length;
  const cntMID = xi.filter(x => x.Pozycja === 'MID').length;
  const cntFWD = xi.filter(x => x.Pozycja === 'FWD').length;
  const totalCost = activePlayers.reduce((s, p) => s + p.Cena, 0);
  const xiXpts = xi.reduce((s, p) => s + p.xp, 0);
  const capTotal = xiXpts + (capPlayer ? capPlayer.xp : 0);
  const capLabel = capPlayer ? capPlayer.web_name : '—';

  // Łączna wariancja XI z Kapitanem (4x dla C + korelacja CS/GC graczy z tego samego klubu)
  let teamVarCap = 0.0;
  for (let i = 0; i < xi.length; i++) {{
    const pi = xi[i];
    const mi = (capPlayer && pi.player === capPlayer.player) ? 2.0 : 1.0;
    teamVarCap += (mi * mi) * (pi.v || 0);
    for (let j = i + 1; j < xi.length; j++) {{
      const pj = xi[j];
      if (pi.team_short === pj.team_short && (pi.cv || 0) > 0 && (pj.cv || 0) > 0) {{
        const mj = (capPlayer && pj.player === capPlayer.player) ? 2.0 : 1.0;
        teamVarCap += 2.0 * mi * mj * pi.cv * pj.cv;
      }}
    }}
  }}
  const teamSdCap = Math.sqrt(Math.max(0, teamVarCap));
  const teamRng = calcTeamRange(capTotal, teamSdCap);
  const rngTip = `Korytarz P20–P80 (60% typowych kolejek) z uwzględnieniem kapitana (×4 do wariancji) i korelacji czystych kont z tego samego klubu. Odchylenie std (σ): ±${{teamSdCap.toFixed(1)}} pkt.`;

  const clubCounts = {{}};
  activePlayers.forEach(p => {{ clubCounts[p.team_short] = (clubCounts[p.team_short] || 0) + 1; }});
  const overClubs = Object.entries(clubCounts).filter(([k, v]) => v > 3).map(([k, v]) => `${{k}}(${{v}})`);

  const okXI = xi.length === 11;
  const okForm = (cntGKP === 1 && cntDEF >= 3 && cntDEF <= 5 && cntMID >= 2 && cntMID <= 5 && cntFWD >= 1 && cntFWD <= 3);
  const okClubs = overClubs.length === 0;

  document.getElementById('lineupValidation').innerHTML = `
    <span class="${{okXI ? 'val-ok' : 'val-err'}}">${{okXI ? '✅' : '⚠️'}} Skład XI: ${{xi.length}}/11</span>
    <span class="${{okForm ? 'val-ok' : 'val-err'}}">${{okForm ? '✅' : '⚠️'}} Formacja: ${{cntGKP}}-${{cntDEF}}-${{cntMID}}-${{cntFWD}}</span>
    <span class="${{okClubs ? 'val-ok' : 'val-err'}}">${{okClubs ? '✅ Max 3 z klubu OK' : '❌ Limit 3 z klubu: ' + overClubs.join(', ')}}</span>
    <span>💰 Kadra: <b>£${{totalCost.toFixed(1)}}m</b></span>
    <span class="val-xpts">🎯 Prognoza XI (GW${{selectedLineupGw}}): ${{xiXpts.toFixed(1)}} pkt</span>
    <span class="val-cap">© z Kapitanem (${{escHtml(capLabel)}}): ${{capTotal.toFixed(1)}} pkt</span>
    <span class="val-rng" title="${{escHtml(rngTip)}}">📉 ${{teamRng.lo.toFixed(0)}} – 📈 ${{teamRng.hi.toFixed(0)}} pkt (σ ±${{teamSdCap.toFixed(1)}})</span>
  `;
}}

function renderPlaner() {{
  renderPlanerMainTable();
  renderLineupTables();
}}

renderPL();
initPlayersFilter();
renderPlayers();
renderFDR();
renderKokpit();
renderScanner();
renderPlaner();
</script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_app)

print("GOTOWE! Wygenerowano świeży plik index.html z silnikiem xPts.")
