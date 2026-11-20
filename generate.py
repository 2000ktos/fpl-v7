import requests
import pandas as pd
import numpy as np
import json
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
# POBIERANIE FORMY Z OSTATNICH 5 ZAKOŃCZONYCH KOLEJEK
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
                l5_stats[eid] = {'min': 0, 'xg': 0.0, 'xa': 0.0}
            l5_stats[eid]['min'] += int(st.get('minutes', 0) or 0)
            l5_stats[eid]['xg'] += float(st.get('expected_goals', 0.0) or 0.0)
            l5_stats[eid]['xa'] += float(st.get('expected_assists', 0.0) or 0.0)
    except Exception as e:
        print(f"Ostrzeżenie: nie udało się pobrać kolejki GW{gw_id} dla L5 ({e})")

# ==============================================================================
# 1. TABELA PIŁKARZY
# ==============================================================================
df_p = pd.DataFrame()
df_p['id'] = elements_df['id'].astype(int)
df_p['player'] = (elements_df['first_name'].astype(str) + " " + elements_df['second_name'].astype(str)).str.strip()
df_p['web_name'] = elements_df['web_name'].astype(str).str.strip()
df_p['team'] = elements_df['team'].map(id_to_team)
df_p['team_short'] = elements_df['team'].map(id_to_short)
df_p['team_id'] = elements_df['team'].astype(int)
df_p['apps'] = elements_df['starts'].astype(int) if 'starts' in elements_df.columns else 0
df_p['min'] = elements_df['minutes'].astype(int)
df_p['G'] = elements_df['goals_scored'].astype(int)
df_p['A'] = elements_df['assists'].astype(int)
df_p['xG'] = elements_df['expected_goals'].astype(float)
df_p['NPxG'] = df_p['xG']
df_p['xA'] = elements_df['expected_assists'].astype(float)
df_p['xGChain'] = (
    elements_df['expected_goal_involvements'].astype(float)
    if 'expected_goal_involvements' in elements_df.columns
    else (df_p['xG'] + df_p['xA'])
)
df_p['xG90'] = np.where(df_p['min'] > 0, (df_p['xG'] / df_p['min']) * 90.0, 0.0)
df_p['xA90'] = np.where(df_p['min'] > 0, (df_p['xA'] / df_p['min']) * 90.0, 0.0)
df_p['Pozycja'] = elements_df['element_type'].map(pos_map)
df_p['Posiadanie'] = elements_df['selected_by_percent'].astype(float) / 100.0
df_p['Cena'] = elements_df['now_cost'].astype(float) / 10.0

df_p['min_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('min', 0)).astype(int)
df_p['xg_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('xg', 0.0)).astype(float)
df_p['xa_l5'] = df_p['id'].map(lambda i: l5_stats.get(int(i), {}).get('xa', 0.0)).astype(float)

df_players = df_p[df_p['min'] > 0].copy()
max_price_slider = round(max(16.0, float(df_p['Cena'].max()) + 1.0), 1)

df_all_catalog = df_p[['player', 'web_name', 'team', 'team_short', 'Pozycja', 'Cena']].copy()
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
finished_fix = fixtures_df[
    (fixtures_df['finished'] == True) &
    (fixtures_df['team_h_score'].notna()) &
    (fixtures_df['team_a_score'].notna())
].copy()

xg_by_team = df_p.groupby('team_id')['xG'].sum().to_dict()
gkp_df = elements_df[(elements_df['element_type'] == 1) & (elements_df['minutes'] > 0)].copy()
gkp_df['xgc_f'] = gkp_df['expected_goals_conceded'].astype(float)
gkp_df['min_f'] = gkp_df['minutes'].astype(float)
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
    mod_ppda = 0.5 if r['PPDA'] < med_ppda else (-0.5 if r['PPDA'] > 15 else 0.0)
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
# 4. KOKPIT
# ==============================================================================
print("4/5 Przeliczanie Kokpitu i Skanera...")

scenariusz_map = {
    "MM": ("🚧 Elitarny Pressing (Ciężko o punkty, mało miejsca)", 0.85),
    "MD": ("🎁 Samobójczy Pressing (Dziurawi. Autostrada na kontry!)", 1.25),
    "DM": ("🧱 Elitarny Autobus (Szczelni. Bicie głową w mur)", 0.80),
    "DD": ("🎪 Chłopcy do bicia (Słaby blok. Trening strzelecki)", 1.20)
}

gw_weights_6 = [1.0, 0.85, 0.72, 0.61, 0.52, 0.44]
gw_weights_sum = sum(gw_weights_6)

kokpit_rows = []
for _, p in df_players.iterrows():
    minuty = float(p['min'])
    min_l5 = float(p['min_l5'])
    sr_min = minuty / max_matches
    sr_min_l5 = min_l5 / l5_denom if l5_gws else 0.0

    if sr_min < 50.0 and sr_min_l5 < 50.0:
        continue

    zaw = p['player']
    klub = p['team']
    poz = p['Pozycja']
    posiadanie = float(p['Posiadanie'])
    cena = float(p['Cena'])

    xgi90 = ((p['NPxG'] + p['xA']) / minuty * 90.0) if minuty > 0 else 0.0
    xg_l5 = float(p['xg_l5'])
    xa_l5 = float(p['xa_l5'])
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
        if xgi90_l5 >= 0.10:
            trend_code, trend_icon = "UP", "📈"
        else:
            trend_code, trend_icon = "STABLE", "➡️"

    xgc90_team = team_to_xga.get(klub, 0.0) / team_to_matches.get(klub, 1.0)

    if poz == "FWD": w1 = "🔥 Elita" if xgi90 >= 0.6 else ("✅ Grywalny" if xgi90 >= 0.4 else "❌ Odrzuć")
    elif poz == "MID": w1 = "🔥 Elita" if xgi90 >= 0.5 else ("✅ Grywalny" if xgi90 >= 0.3 else "❌ Odrzuć")
    elif poz == "DEF": w1 = "🔥 Elita" if xgi90 >= 0.25 else ("✅ Grywalny" if xgi90 >= 0.1 else "❌ Odrzuć")
    else: w1 = "Brak pozycji"

    ocena_obr = "Brak Danych" if xgc90_team == 0 else ("🛡️ Mur (xGC < 1.30)" if xgc90_team <= 1.3 else "⚠️ Dziurawi")

    if poz in ["DEF", "GKP"]: w2 = "✅ Solidny Tył" if xgc90_team <= 1.3 else "❌ Dziurawa obrona"
    elif poz in ["MID", "FWD"]: w2 = "🔥 Elita!" if xgi90 >= 0.5 else ("✅ Grywalny" if xgi90 >= 0.35 else "❌ Za słabe xGI")
    else: w2 = "❓ Zła pozycja"

    status_eo = "🗡️ Super Diff (Miecz)" if posiadanie < 0.10 else "🛡️ Szablon (Tarcza)"

    m_list, xgc_list, ev_cs_list, cs_prob_list = [], [], [], []
    for gw_num in rolling_gws:
        fx = team_fixtures.get(klub, {}).get(gw_num, {'text': '', 'opp': '', 'ha': '', 'fdr_atk': 0, 'fdr_def': 0, 'matches': []})
        if fx['matches']:
            xgc_v = sum(
                (short_to_xga.get(o, 0.0) / short_to_matches.get(o, 1.0)) * (1.15 if h == "H" else 0.85)
                for o, h in fx['matches']
            )
            cs_matches = []
            for o, h in fx['matches']:
                opp_xg90 = short_to_xg.get(o, xgc90_team) / short_to_matches.get(o, 1.0)
                ha_def_mod = 0.85 if h == "H" else 1.15
                opp_xg_ha = opp_xg90 * ha_def_mod
                lam_m = ((xgc90_team + opp_xg90) / 2.0) * ha_def_mod
                bonus_cs = 1.15 if (xgc90_team < 1.5 and opp_xg_ha < 1.5) else 1.0
                cs_m = min(1.0, float(np.exp(-lam_m) * bonus_cs))
                cs_matches.append(cs_m)
            cs_prob_gw = 1.0 - float(np.prod([1.0 - c for c in cs_matches]))
            ev_cs_gw = float(sum(cs_matches) * 4.0)
            fdr_pos = fx['fdr_atk'] if poz in ["MID", "FWD"] else fx['fdr_def']
        else:
            xgc_v, cs_prob_gw, ev_cs_gw, fdr_pos = 0.0, 0.0, 0.0, 0

        m_list.append({'text': fx['text'], 'opp': fx['opp'], 'ha': fx['ha'], 'xgc': round(xgc_v, 2), 'fdr': fdr_pos})
        xgc_list.append(xgc_v)
        cs_prob_list.append(cs_prob_gw)
        ev_cs_list.append(ev_cs_gw)

    while len(m_list) < 6:
        m_list.append({'text': '', 'opp': '', 'ha': '', 'xgc': 0.0, 'fdr': 0})
        xgc_list.append(0.0)
        cs_prob_list.append(0.0)
        ev_cs_list.append(0.0)

    opp1, ha1, q_xgc1 = m_list[0]['opp'], m_list[0]['ha'], xgc_list[0]

    ppda_opp1 = short_to_ppda.get(opp1, 0.0)
    xga90_opp1 = short_to_xga.get(opp1, 0.0) / short_to_matches.get(opp1, 1.0)
    szyfr = ("D" if ppda_opp1 > med_ppda else "M") + ("D" if xga90_opp1 > med_npxgc90 else "M")
    scenariusz, booster_val = scenariusz_map.get(szyfr, ("Brak danych", 1.0))

    szansa_cs = cs_prob_list[0]

    if q_xgc1 == 0 and ev_cs_list[0] == 0:
        ev_gw = 0.0
    elif poz in ["DEF", "GKP"]:
        ev_gw = ev_cs_list[0]
    elif poz == "MID":
        ev_gw = xgi90 * (q_xgc1 / 1.5) * 4.0 * booster_val
    elif poz == "FWD":
        ev_gw = xgi90 * (q_xgc1 / 1.5) * 3.5 * booster_val
    else:
        ev_gw = 0.0

    if sum(xgc_list) == 0 and sum(ev_cs_list) == 0:
        ev_6gw = 0.0
    else:
        w_avg = sum(xgc_list[i] * gw_weights_6[i] for i in range(6)) / gw_weights_sum
        if poz in ["DEF", "GKP"]:
            ev_6gw = sum(ev_cs_list[i] * gw_weights_6[i] for i in range(6)) / gw_weights_sum
        elif poz == "MID":
            ev_6gw = xgi90 * (w_avg / 1.5) * 4.0
        elif poz == "FWD":
            ev_6gw = xgi90 * (w_avg / 1.5) * 3.5
        else:
            ev_6gw = 0.0

    if ev_6gw == 0: radar = "Brak Danych"
    elif poz == "FWD": radar = "🛒 Priorytet Kupna" if ev_6gw >= 2.1 else ("✅ Dobra Opcja" if ev_6gw >= 1.4 else "❌ Pozbądź się")
    elif poz == "MID": radar = "🛒 Priorytet Kupna" if ev_6gw >= 2.0 else ("✅ Dobra Opcja" if ev_6gw >= 1.2 else "❌ Pozbądź się")
    elif poz in ["DEF", "GKP"]: radar = "🛒 Priorytet Kupna" if ev_6gw >= 1.4 else ("✅ Dobra Opcja" if ev_6gw >= 0.8 else "❌ Pozbądź się")
    else: radar = "Brak pozycji"

    if l5_gws and sr_min >= 50.0 and sr_min_l5 < 35.0:
        status_min = "⚠️ Spadek minut (L5)"
    elif sr_min >= 70.0 or sr_min_l5 >= 70.0:
        status_min = "🟢 Pewniak (>70m)"
    else:
        status_min = "🟡 Rotacja (50-70m)"

    kokpit_rows.append({
        'Zawodnik': zaw, 'Klub': klub, 'Cena': round(cena, 1), 'Minuty': int(minuty),
        'xGI90': round(xgi90, 2),
        'Min_L5': int(min_l5), 'xG_L5': round(xg_l5, 2), 'xGI90_L5': round(xgi90_l5, 2),
        'Trend_Code': trend_code, 'Trend_Icon': trend_icon,
        'xGC90_Team': round(xgc90_team, 2), 'Werdykt1': w1,
        'Ocena_Obrony': ocena_obr, 'Szansa_CS': round(szansa_cs * 100, 1), 'EV_GW': round(ev_gw, 2),
        'Pozycja': poz, 'Posiadanie': round(posiadanie * 100, 1), 'Werdykt2': w2, 'Status_EO': status_eo,
        'm1': m_list[0], 'm2': m_list[1], 'm3': m_list[2], 'm4': m_list[3], 'm5': m_list[4], 'm6': m_list[5],
        'EV_6GW': round(ev_6gw, 2), 'Radar': radar, 'Status_Min': status_min,
        'Szyfr': szyfr, 'Scenariusz': scenariusz, 'Booster': booster_val
    })

kokpit_rows.sort(key=lambda x: x['EV_6GW'], reverse=True)

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
# 6. DOMYŚLNY STAN PLANERA
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

players_cols = ['player', 'team', 'apps', 'min', 'G', 'A', 'xG', 'NPxG', 'xA', 'xGChain', 'xG90', 'xA90', 'Pozycja', 'Posiadanie', 'Cena']
df_players_out = df_players[players_cols].copy()
for c in ['xG', 'NPxG', 'xA', 'xGChain', 'xG90', 'xA90']:
    df_players_out[c] = df_players_out[c].round(2)
df_players_out['Cena'] = df_players_out['Cena'].round(1)

json_pl = df_pl_out.to_json(orient='records')
json_players = df_players_out.to_json(orient='records')
json_catalog = df_all_catalog.to_json(orient='records')
json_fdr = json.dumps(fdr_matrix)
json_team_fix_short = json.dumps(team_fixtures_short)
json_gw_meta = json.dumps(gw_meta)
json_kokpit = json.dumps(kokpit_rows)
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
    font-size: 12.5px; line-height: 1.48; max-width: 340px; min-width: 190px;
    box-shadow: 0 10px 26px rgba(0,0,0,0.32); border: 1px solid rgba(255,255,255,0.14);
    pointer-events: none; text-align: left; font-weight: 400; white-space: normal;
  }}
  #fplTooltip b {{ color: #86efac; font-weight: 700; }}
  #fplTooltip .tip-title {{ font-weight: 700; color: #ffffff; margin-bottom: 4px; font-size: 13px; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 3px; }}
  #fplTooltip .tip-muted {{ color: #cbd5e1; font-size: 11.5px; display: block; margin-top: 5px; }}

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
  table.excel-table td {{ border: 1px solid var(--excel-border); padding: 4px 7px; white-space: nowrap; text-align: right; }}
  table.excel-table td.text-left {{ text-align: left; font-weight: 500; }}
  table.excel-table td.text-center {{ text-align: center; }}
  table.excel-table tr:nth-child(even) td {{ background-color: #fafafa; }}
  table.excel-table tr:hover td {{ background-color: #e8f4ee !important; }}
  table.excel-table td.sticky-col, table.excel-table th.sticky-col {{
    position: sticky; left: 0; z-index: 2; background: #f3f2f1;
  }}
  table.excel-table th.sticky-col {{ z-index: 4; background: #dcdcdc; }}

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

  tr.zone-GKP td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #DAE3F3 !important; }}
  tr.zone-DEF td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #FBE5D6 !important; }}
  tr.zone-MID td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #EDEDED !important; }}
  tr.zone-FWD td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #FFF2CC !important; }}
  tr.zone-NEW td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #ffffff !important; }}

  tr.zone-GKP:hover td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #c8d7f0 !important; }}
  tr.zone-DEF:hover td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #f8d4bc !important; }}
  tr.zone-MID:hover td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #dedede !important; }}
  tr.zone-FWD:hover td:not(.cell-fix):not([class*="dec-"]) {{ background-color: #ffe8a3 !important; }}

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
    max-height: 250px; overflow-y: auto; width: 290px; font-size: 12.5px;
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
  .lineup-tables-grid {{ display: grid; grid-template-columns: 1.25fr 1fr; gap: 14px; padding: 12px; align-items: start; }}
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

  .val-bar {{ display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 12px; background: #f3f6f4; border-top: 1px solid #e0e0e0; font-size: 12.5px; }}
  .val-ok {{ color: #0f5132; font-weight: 700; }}
  .val-err {{ color: #b00020; font-weight: 700; }}

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
        <label style="cursor:pointer;"><input type="checkbox" id="kShowTech" onchange="renderKokpit()"> Pokaż ukryte (xGC 2-6, Szyfr, Booster)</label>
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
      <b>🗓️ Planer Składu (strefy GKP / DEF / MID / FWD z auto-sortowaniem)</b>
      <div class="toolbar-group">
        <button class="mode-btn active" id="pViewTxt" onclick="setPlanerCellMode('text', this)">Rywale (EVE-H)</button>
        <button class="mode-btn" id="pViewNum" onclick="setPlanerCellMode('num', this)">Trudność (1–5)</button>
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
              <button class="act-btn" onclick="autoPickBenchForGw()" title="Automatycznie posadź na ławce 1 bramkarza i 3 graczy z najtrudniejszym meczem / statusem Słup">⚡ Auto-ławka (11+4)</button>
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
const rollingGWs = {json_rolling_gws};
const planerGWs = {json_planer_gws};
const dataScanner = {json_scanner};
const dataChips = {json_chip_matrix};
const nextGwNum = {next_gw_num};
const defaultSquad = {json_def_squad};
const defaultTargets = {json_def_targets};

// ============================================================================
// SYSTEM DYMKÓW (TOOLTIPÓW) ⓘ — komputer (hover) + telefon (tap)
// ============================================================================
const TIPS = {{
  TOP_L5: {{
    title: 'Okno formy (L5)',
    body: 'Ostatnie 5 zakończonych kolejek, na bazie których liczone są kolumny formy L5 i strzałki trendu w Kokpicie.'
  }},
  TOP_XGC: {{
    title: 'Ligowa mediana xGC/90',
    body: 'Środkowa wartość oczekiwanych bramek traconych na mecz w Premier League (punkt odniesienia dla FDR i Scenariuszy meczowych).'
  }},
  TOP_PPDA: {{
    title: 'Ligowa mediana PPDA',
    body: 'Środkowa wartość intensywności pressingu w lidze — oddziela drużyny pressujące wysoko od broniących głębiej.'
  }},

  // Zakładka 1: Tabela Premier League
  PL_XG: {{
    title: 'xG (Expected Goals)',
    body: 'Oczekiwane bramki zdobyte. Suma jakości wszystkich oddanych strzałów drużyny — pokazuje, ile goli powinna była strzelić.'
  }},
  PL_NPXG: {{
    title: 'NPxG (Non-Penalty xG)',
    body: 'Oczekiwane bramki bez rzutów karnych — lepiej oddaje siłę ataku z gry.<span class="tip-muted">Uwaga: podczas przerwy Understatu tymczasowo równe xG.</span>'
  }},
  PL_XGA: {{
    title: 'xGA (Expected Goals Against)',
    body: 'Oczekiwane bramki stracone. Suma jakości strzałów dopuszczonych przez obronę — im niższa wartość, tym szczelniejsza defensywa.'
  }},
  PL_NPXGA: {{
    title: 'NPxGA (Non-Penalty xGA)',
    body: 'Oczekiwane bramki stracone bez rzutów karnych.<span class="tip-muted">Uwaga: podczas przerwy Understatu tymczasowo równe xGA.</span>'
  }},
  PL_PPDA: {{
    title: 'PPDA (Intensywność pressingu)',
    body: 'Liczba podań, na jakie zespół pozwala rywalowi na jego połowie, zanim spróbuje odebrać piłkę. <b>Im niższa wartość, tym agresywniejszy pressing</b> (poniżej 10 = elita pressingu, powyżej 14 = cofnięty blok).<span class="tip-muted">Tymczasowo zamrożone po GW8 do powrotu Understatu.</span>'
  }},
  PL_OPPDA: {{
    title: 'OPPDA (Odporność na pressing)',
    body: 'Odwrotność PPDA — średnia liczba podań, jaką drużyna wymienia na własnej połowie, zanim przeciwnik zaatakuje ją pressingiem. <b>Im wyższa wartość</b>, tym łatwiej zespół rozgrywa piłkę (albo rywale celowo cofają się przeciwko niemu głęboko w obronę).'
  }},
  PL_TAKT: {{
    title: 'Taktyczne xGC90',
    body: 'Skorygowane zagrożenie defensywne na mecz (<b>xGA / mecze × mnożnik stylu</b>). Zwykłe xGA nie mówi, jak drużyna broni, więc algorytm nakłada korektę za styl pressingu:<br>• ostry pressing (PPDA &lt; 11) i szczelna obrona (&lt; 1.2) → <b>×0.85</b> (duszą rywala)<br>• ostry pressing (PPDA &lt; 11), dziurawa obrona (≥ 1.2) → <b>×1.20</b> (samobójczy pressing, autostrada na kontry)<br>• głęboki blok (PPDA &gt; 14) i szczelna obrona (&lt; 1.2) → <b>×0.90</b> (szczelny autobus)<br>• głęboki blok (PPDA &gt; 14) i słaba obrona (≥ 1.2) → <b>×1.05</b> (pasywni i dziurawi).<br><b>Im niższa liczba, tym trudniej strzelić temu zespołowi gola.</b>'
  }},
  PL_XGD: {{
    title: 'xGD (Różnica xG na mecz)',
    body: 'Średnia różnica oczekiwanych bramek na mecz: <b>(NPxG − NPxGA) / mecze</b>. Pokazuje realną siłę netto drużyny niezależnie od szczęścia w wykończeniu. Wartość <b>dodatnia (+)</b> oznacza przewagę jakościową; <b>ujemna (−)</b> — że zespół częściej jest zdominowany.'
  }},
  PL_FDR: {{
    title: 'FDR (Wskaźnik trudności rywala)',
    body: 'Własny wskaźnik trudności rywala (<b>1 = najłatwiejszy, 5 = najtrudniejszy</b>). Zamiast sztywnych ocen z FPL liczony jest na żywo z siły zespołu: <b>xGD</b> korygowane za pressing (+0.5 gdy zespół pressuje mocniej niż mediana ligi, lub −0.5 gdy jest bardzo pasywny przy PPDA &gt; 15). Wynik dzielony jest na progi 1–5 względem ligowej mediany straconego xG.'
  }},

  // Zakładka 2: Tabela Piłkarzy
  P_XGCHAIN: {{
    title: 'xGChain',
    body: 'Całkowity udział w akcjach bramkowych (wskaźnik podglądowy do oceny potencjału ofensywnego — nie wchodzi do wzorów EV). Docelowo oznacza sumę xG każdej akcji, w której piłkarz dotknął piłki, nawet 2–3 podania przed strzałem.<span class="tip-muted">Tymczasowo, podczas przerwy Understatu, kolumna pokazuje oficjalne xGI z FPL (xG + xA).</span>'
  }},

  // Zakładka 3: FDR
  FDR_ALL: {{
    title: 'FDR Ogólny',
    body: 'Ogólna trudność rywala wyliczona na podstawie jego bilansu jakości (xGD) i intensywności pressingu (PPDA). <b>Im wyższa liczba (1–5), tym trudniejszy dla Ciebie mecz</b> (na wyjeździe +1, maks. 5).'
  }},
  FDR_ATK: {{
    title: 'Trudność dla Ataku (MID / FWD)',
    body: 'Trudność meczu dla Twoich graczy ofensywnych wyliczona na podstawie szczelności obrony rywala (NPxGA na mecz). <b>Im wyższa liczba (1–5), tym trudniejszy mecz dla Twojego ataku</b> (na wyjeździe +1, maks. 5).'
  }},
  FDR_DEF: {{
    title: 'Trudność dla Obrony (DEF / GKP)',
    body: 'Trudność meczu dla Twoich obrońców i bramkarzy wyliczona na podstawie siły ataku rywala (NPxG na mecz). <b>Im wyższa liczba (1–5), tym trudniejszy mecz o czyste konto</b> (na wyjeździe +1, maks. 5).'
  }},

  // Zakładka 4: Kokpit
  K_XGI90: {{
    title: 'xGI90 (Sezon)',
    body: 'Oczekiwany udział przy golach (<b>NPxG + xA</b>) w przeliczeniu na pełne 90 minut za cały sezon. Pokazuje bazowy potencjał ofensywny piłkarza.'
  }},
  K_MIN_L5: {{
    title: 'Min L5 (Minuty z 5 GW)',
    body: 'Suma minut z ostatnich 5 zakończonych kolejek (maks. 450). Żółte tło (<b>&lt; 175 min</b>) ostrzega przed rotacją, kontuzją lub utratą miejsca w składzie.'
  }},
  K_XG_L5: {{
    title: 'xG L5 (Forma strzelecka)',
    body: 'Suma oczekiwanych bramek (xG) z ostatnich 5 kolejek — pokazuje, czy gracz w ostatnim czasie regularnie dochodzi do sytuacji bramkowych.'
  }},
  K_XGI90_L5: {{
    title: 'xGI90 L5 (Trend formy)',
    body: 'Aktualna forma ofensywna na 90 minut z ostatnich 5 kolejek porównana ze średnią z całego sezonu:<br>📈 <b>zwyżka formy</b> (co najmniej +20% vs sezon)<br>➡️ <b>forma stabilna</b><br>📉 <b>spadek formy</b> (co najmniej −20% vs sezon)<br>⏸️ <b>za mało minut</b> do oceny (&lt; 90 min w L5).'
  }},
  K_XGC_TEAM: {{
    title: 'xGC/90 Drużyny',
    body: 'Ogólne xGC całej drużyny w przeliczeniu na jeden mecz. <b>Im niższa wartość, tym szczelniejsza defensywa zespołu.</b>'
  }},
  K_W1: {{
    title: 'Werdykt ofensywy',
    body: 'Ocena czysto ofensywna oparta na <b>xGI90</b> (liczona również dla obrońców — pomaga wyłapać groźnych wahadłowych i stoperów przy stałych fragmentach).'
  }},
  K_OBR: {{
    title: 'Ocena obrony',
    body: 'Szybka ocena defensywy zespołu na podstawie xGC/90 drużyny: <b>🛡️ Mur</b> przy xGC/90 ≤ 1.30, powyżej <b>⚠️ Dziurawi</b>.'
  }},
  K_CS: {{
    title: 'Szansa na CS (Czyste konto)',
    body: 'Prawdopodobieństwo czystego konta w najbliższej kolejce z <b>rozkładu Poissona</b>. Łączy xGC/90 Twojej drużyny z siłą ataku rywala (xG/90), koryguje za boisko (×0.85 u siebie / ×1.15 na wyjeździe) i dodaje +15% bonusu, gdy oba wskaźniki są poniżej 1.5.'
  }},
  K_EV_GW: {{
    title: 'EV GW (Predykcja na najbliższą kolejkę)',
    body: 'Prognoza <b>punktów dodatkowych</b> na najbliższą kolejkę (<b>nie zawiera</b> standardowych 2 pkt za występ, bonusów BPS ani obron bramkarza).<br>• <b>MID / FWD:</b> xGI90 × (GC Rywala H/A ÷ 1.5) × mnożnik pozycji (4.0 / 3.5) × Booster scenariusza<br>• <b>DEF / GKP:</b> Szansa na CS × 4 pkt.'
  }},
  K_W2: {{
    title: 'Werdykt (Poz)',
    body: 'Werdykt ogólny dostosowany do pozycji zawodnika: dla <b>DEF / GKP</b> ocenia szczelność obrony drużyny (xGC/90), a dla <b>MID / FWD</b> produkcję ofensywną (xGI90).'
  }},
  K_EO: {{
    title: 'Status EO (Posiadanie)',
    body: 'Rola zawodnika względem reszty graczy FPL:<br>• <b>🗡️ Super Diff (Miecz)</b> — poniżej 10% posiadania (pozwala gonić w tabeli)<br>• <b>🛡️ Szablon (Tarcza)</b> — od 10% w górę (chroni Twoją pozycję).'
  }},
  K_GC_OPP: {{
    title: 'GC Rywala (H/A)',
    body: 'Oczekiwane bramki tracone na mecz przez najbliższego rywala, <b>już skorygowane o mnożnik boiska</b>: ×1.15 gdy grasz u siebie (H) lub ×0.85 na wyjeździe (A).<span class="tip-muted">Korekta za styl pressingu (Booster) wchodzi osobno dopiero w EV GW, żeby nie mnożyć jej podwójnie.</span>'
  }},
  K_EV_6GW: {{
    title: 'EV 6GW (Predykcja na 6 kolejek)',
    body: 'Średnia ważona prognoza punktów dodatkowych na <b>6 najbliższych kolejek</b> (bliższe mecze ważą więcej niż odległe; bez 2 pkt za występ i bonusów). Dla <b>MID / FWD</b> bazuje na obronach 6 rywali (z korektą H/A), a dla <b>DEF / GKP</b> na szansach czystego konta w tych 6 meczach.'
  }},
  K_SCEN: {{
    title: 'Przewidywany Scenariusz',
    body: 'Taktyczny profil najbliższego rywala wyznaczony z porównania jego pressingu (<b>PPDA</b>) i obrony (<b>xGA/90</b>) z medianą ligi. Nakłada mnożnik (<b>Booster</b>) do EV GW dla ataku:<br>• 🎁 Samobójczy Pressing → <b>×1.25</b><br>• 🎪 Chłopcy do bicia → <b>×1.20</b><br>• 🚧 Elitarny Pressing → <b>×0.85</b><br>• 🧱 Elitarny Autobus → <b>×0.80</b>.'
  }},

  // Zakładka 5: Skaner Wildcard i Free Hit
  S_FH_SC: {{
    title: 'Skaner Free Hit (Wynik 1 GW)',
    body: 'Suma siły ofensywnej <b>5 najlepszych klubów</b> w tej kolejce (z Tabeli Chipów niżej). Im wyższa wartość, tym lepsze mecze mają faworyci.'
  }},
  S_FH_VR: {{
    title: 'Werdykt Free Hit',
    body: 'Ocena opłacalności chipu Free Hit w tej jednej kolejce. <b>💣 WYBUCHOWA</b> zapala się po przekroczeniu progu statystycznego (średnia + odchylenie standardowe).'
  }},
  S_WC_SC: {{
    title: 'Skaner Wildcard (Średnia 5 GW)',
    body: 'Średni wynik z <b>5 kolejnych kolejek</b> (od tej kolejki włącznie). Pokazuje łączną jakość kalendarza na dłuższe okno.'
  }},
  S_WC_VR: {{
    title: 'Werdykt Wildcard',
    body: '<b>💣 ODPALAJ WILDCARD!</b> wymaga spełnienia dwóch warunków: średnia 5-kolejkowa powyżej progu (średnia + SD) <b>oraz</b> min. 3 z 5 kolejek co najmniej na poziomie ligowej mediany.'
  }},

  // Zakładka 6: Planer
  PLR_STATUS: {{
    title: 'Status gracza w Planerze',
    body: 'Określa, jak Planer traktuje piłkarza:<br>• <b>💎 Premium</b> — wyłączony z alarmu sprzedaży (trzymasz niezależnie od meczów)<br>• <b>🪵 Słup</b> — tani rezerwowy na ławkę (bez alarmu sprzedaży; priorytet przy Auto-ławce)<br>• <b>♻️ Rotacja</b> — zwykły gracz oceniany pod kątem terminarza.'
  }},
  PLR_DEC: {{
    title: 'Decyzja (Alarm kalendarzowy)',
    body: 'Automatycznie ostrzega, jeśli w ciągu najbliższych 12 kolejek gracz ma serię <b>3 trudnych meczów pod rząd</b> (trudność 4 lub 5 dopasowana do pozycji). Nie dotyczy graczy ze statusem 💎 Premium i 🪵 Słup.'
  }},
  PLR_OUTIN: {{
    title: 'Kolumna OUT / IN',
    body: 'Wpisz numer kolejki sprzedaży (<b>OUT</b>) w składzie albo zakupu (<b>IN</b>) w celach. Kafelki poza czasem gry w zespole wyszarzają się, a Tabela 2 na dole automatycznie składa aktualną kadrę na wybraną kolejkę.<span class="tip-muted">Wskazówka: kliknij dowolny kafelek meczu, aby posadzić gracza na ławce (Ł).</span>'
  }}
}};

let pinnedTipEl = null;

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

function showTip(anchorEl) {{
  const key = anchorEl.getAttribute('data-tip');
  const data = TIPS[key];
  if (!data) return;
  const box = document.getElementById('fplTooltip');
  box.innerHTML = `<div class="tip-title">${{data.title}}</div><div>${{data.body}}</div>`;
  positionTooltip(anchorEl);
}}

function hideTip(force) {{
  if (!force && pinnedTipEl) return;
  pinnedTipEl = null;
  document.getElementById('fplTooltip').style.display = 'none';
}}

function toggleTip(anchorEl) {{
  if (pinnedTipEl === anchorEl) {{
    hideTip(true);
  }} else {{
    pinnedTipEl = anchorEl;
    showTip(anchorEl);
  }}
}}

document.addEventListener('click', (e) => {{
  if (pinnedTipEl && !e.target.classList.contains('info-icon')) hideTip(true);
}});
window.addEventListener('resize', () => hideTip(true));
document.addEventListener('scroll', () => hideTip(true), true);

let plSort = {{ col: 'points', asc: false }};
let pSort = {{ col: 'G', asc: false }};
let kSort = {{ col: 'EV_6GW', asc: false }};
let fdrMode = 'fdr_overall';
let planerCellMode = 'text';
let selectedLineupGw = planerGWs[0] || nextGwNum;
let lastPlacedPlayer = null;

const POS_RANK = {{ GKP: 1, DEF: 2, MID: 3, FWD: 4 }};
const STORAGE_KEY = 'fpl_v7_planer_state_v3';

function escHtml(s) {{
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}}

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
// 2. TABELA PIŁKARZY
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
  const cols = ['player','team','apps','min','G','A','xG','NPxG','xA','xGChain','xG90','xA90','Pozycja','Posiadanie','Cena'];
  let html = '<thead><tr><th>#</th>' + cols.map(c =>
    `<th onclick="sortPlayers('${{c}}')">${{c}}${{c === 'xGChain' ? tipIcon('P_XGCHAIN') : ''}} ${{pSort.col===c ? (pSort.asc?'▲':'▼') : ''}}</th>`
  ).join('') + '</tr></thead><tbody>';
  rows.forEach((r, idx) => {{
    html += `<tr><td class="text-center">${{idx+1}}</td>`;
    cols.forEach(c => {{
      let val = r[c];
      let cls = '';
      if (c === 'player' || c === 'team') cls = 'text-left';
      else if (c === 'Pozycja') cls = 'text-center';
      else if (c === 'Posiadanie') val = (r[c] * 100).toFixed(1) + '%';
      html += `<td class="${{cls}}">${{escHtml(val)}}</td>`;
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
// 4. KOKPIT
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
  const showTech = document.getElementById('kShowTech').checked;

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
    return true;
  }});

  rows.sort((a, b) => cmpVal(getKokpitSortValue(a, kSort.col), getKokpitSortValue(b, kSort.col), kSort.asc));
  document.getElementById('kCount').innerText = `Gracze w Kokpicie: ${{rows.length}} (>=50m sezon lub L5)`;

  let cols = [
    {{ k: 'Zawodnik', lbl: 'Zawodnik', cls: 'text-left sticky-col' }},
    {{ k: 'Klub', lbl: 'Klub', cls: 'text-left' }},
    {{ k: 'Cena', lbl: 'Cena' }},
    {{ k: 'Minuty', lbl: 'Minuty' }},
    {{ k: 'xGI90', lbl: 'xGI90', tip: 'K_XGI90' }},
    {{ k: 'Min_L5', lbl: 'Min L5', thCls: 'l5-hdr', cls: 'l5-col', isMinL5: true, tip: 'K_MIN_L5' }},
    {{ k: 'xG_L5', lbl: 'xG L5', thCls: 'l5-hdr', cls: 'l5-col', fmt: v => Number(v).toFixed(2), tip: 'K_XG_L5' }},
    {{ k: 'xGI90_L5', lbl: 'xGI90 L5', thCls: 'l5-hdr', isL5Trend: true, tip: 'K_XGI90_L5' }},
    {{ k: 'xGC90_Team', lbl: 'xGC/90 Drużyny', tip: 'K_XGC_TEAM' }},
    {{ k: 'Werdykt1', lbl: 'Werdykt (Atak)', cls: 'text-left', tip: 'K_W1' }},
    {{ k: 'Ocena_Obrony', lbl: 'Ocena obrony', cls: 'text-left', tip: 'K_OBR' }},
    {{ k: 'Szansa_CS', lbl: 'Szansa na CS', fmt: v => v + '%', tip: 'K_CS' }},
    {{ k: 'EV_GW', lbl: 'EV GW', tip: 'K_EV_GW' }},
    {{ k: 'Pozycja', lbl: 'Pozycja', cls: 'text-center' }},
    {{ k: 'Posiadanie', lbl: 'Posiadanie', fmt: v => v + '%' }},
    {{ k: 'Werdykt2', lbl: 'Werdykt (Poz)', cls: 'text-left', tip: 'K_W2' }},
    {{ k: 'Status_EO', lbl: 'Status EO', cls: 'text-left', tip: 'K_EO' }},
    {{ k: 'm1', lbl: rollingGWs[0] || 'Mecz 1', isFix: true }},
    {{ k: 'xgc1', lbl: 'GC Rywala (H/A)', tip: 'K_GC_OPP' }},
    {{ k: 'm2', lbl: rollingGWs[1] || 'Mecz 2', isFix: true }},
  ];
  if (showTech) cols.push({{ k: 'xgc2', lbl: 'xGC 2' }});
  cols.push({{ k: 'm3', lbl: rollingGWs[2] || 'Mecz 3', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc3', lbl: 'xGC 3' }});
  cols.push({{ k: 'm4', lbl: rollingGWs[3] || 'Mecz 4', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc4', lbl: 'xGC 4' }});
  cols.push({{ k: 'm5', lbl: rollingGWs[4] || 'Mecz 5', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc5', lbl: 'xGC 5' }});
  cols.push({{ k: 'm6', lbl: rollingGWs[5] || 'Mecz 6', isFix: true }});
  if (showTech) cols.push({{ k: 'xgc6', lbl: 'xGC 6' }});

  cols.push(
    {{ k: 'EV_6GW', lbl: 'EV 6GW', tip: 'K_EV_6GW' }},
    {{ k: 'Radar', lbl: 'Radar', cls: 'text-left' }},
    {{ k: 'Status_Min', lbl: 'Status minutowy', cls: 'text-left' }}
  );
  if (showTech) cols.push({{ k: 'Szyfr', lbl: 'Szyfr', cls: 'text-center' }});
  cols.push({{ k: 'Scenariusz', lbl: `Przewidywany Scenariusz (${{rollingGWs[0]}})`, isScen: true, tip: 'K_SCEN' }});
  if (showTech) cols.push({{ k: 'Booster', lbl: 'Booster' }});

  let html = '<thead><tr><th>#</th>' + cols.map(c => {{
    const sticky = c.k === 'Zawodnik' ? 'sticky-col' : '';
    const extraTh = c.thCls || '';
    return `<th class="${{sticky}} ${{extraTh}}" onclick="sortKokpit('${{c.k}}')">${{c.lbl}}${{tipIcon(c.tip)}} ${{kSort.col===c.k ? (kSort.asc?'▲':'▼') : ''}}</th>`;
  }}).join('') + '</tr></thead><tbody>';

  rows.forEach((r, idx) => {{
    html += `<tr><td class="text-center">${{idx+1}}</td>`;
    cols.forEach(c => {{
      if (c.isFix) {{
        html += `<td class="fdr-${{r[c.k].fdr}}">${{r[c.k].text}}</td>`;
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
// 6. PLANER
// ============================================================================
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
  menu.style.left = Math.min(rect.left, window.innerWidth - 300) + 'px';
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
  document.getElementById('pViewTxt').classList.remove('active');
  document.getElementById('pViewNum').classList.remove('active');
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
    const stOpts = ['', '💎 Premium', '🪵 Słup', '♻️ Rotacja'].map(s =>
      `<option value="${{s}}" ${{r.status===s?'selected':''}}>${{s || '—'}}</option>`
    ).join('');

    html += `<tr class="${{rowClasses.join(' ')}}">
      <td class="text-left sticky-col">
        <div class="p-combo-wrap">
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
      <td>${{price}}</td>`;

    planerGWs.forEach(gw => {{
      const fx = pInfo ? getPosFixture(pInfo.team_short, pInfo.Pozycja, gw) : {{ text: '—', fdr: 0 }};
      const inactive = !isNaN(boundGw) && (isSquad ? (gw >= boundGw) : (gw < boundGw));
      const benched = !inactive && pInfo && isBenchInGw(pInfo.player, gw);
      const disp = planerCellMode === 'num' ? (fx.fdr || '—') : fx.text;
      const badge = benched ? `<span class="badge-mini">Ł</span>` : '';
      const cls = `cell-fix fdr-${{fx.fdr}} ${{inactive ? 'cell-inactive' : ''}} ${{benched ? 'cell-bench' : ''}}`;
      const dataAttrs = pInfo
        ? `data-player="${{escHtml(pInfo.player)}}" data-gw="${{gw}}" onclick="toggleBenchInGw(this.dataset.player, Number(this.dataset.gw))"`
        : '';
      html += `<td class="${{cls}}" ${{dataAttrs}} title="${{pInfo ? 'Kliknij: przełącz Skład XI / Ławka w GW'+gw : ''}}">${{disp}}${{badge}}</td>`;
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
  const totalCols = 5 + planerGWs.length + 3;

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
    <th>Klub</th><th>Poz</th><th>Cena</th>`;
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
      activePlayers.push({{ ...pInfo, status: r.status, source: 'Skład' }});
    }}
  }});
  planerState.targets.forEach(r => {{
    const inGw = parseInt(r.inGw, 10);
    if (isNaN(inGw) || gw < inGw) return;
    const pInfo = findExactPlayer(r.player);
    if (pInfo && !seen.has(pInfo.player)) {{
      seen.add(pInfo.player);
      activePlayers.push({{ ...pInfo, status: r.status, source: 'IN' }});
    }}
  }});
  return activePlayers;
}}

function autoPickBenchForGw() {{
  const gw = selectedLineupGw;
  const active = getActivePlayersForGw(gw).map(p => ({{
    ...p,
    fx: getPosFixture(p.team_short, p.Pozycja, gw)
  }}));
  const newBench = [];

  const gkps = active.filter(p => p.Pozycja === 'GKP').sort((a, b) => b.fx.fdr - a.fx.fdr || a.Cena - b.Cena);
  while (gkps.length > 1) {{
    newBench.push(gkps.shift().player);
  }}

  const outfield = active.filter(p => p.Pozycja !== 'GKP');
  outfield.sort((a, b) => {{
    const sa = a.status === '🪵 Słup' ? 1 : 0;
    const sb = b.status === '🪵 Słup' ? 1 : 0;
    if (sb !== sa) return sb - sa;
    if (b.fx.fdr !== a.fx.fdr) return b.fx.fdr - a.fx.fdr;
    return a.Cena - b.Cena;
  }});

  const counts = {{ DEF: 0, MID: 0, FWD: 0 }};
  outfield.forEach(p => counts[p.Pozycja]++);
  const mins = {{ DEF: 3, MID: 2, FWD: 1 }};

  for (const p of outfield) {{
    if (newBench.length >= (active.length - 11)) break;
    if (counts[p.Pozycja] - 1 >= mins[p.Pozycja]) {{
      newBench.push(p.player);
      counts[p.Pozycja]--;
    }}
  }}

  planerState.benchMap[String(gw)] = newBench;
  savePlanerState();
  renderPlaner();
  showToast(`⚡ Ustawiono automatyczną ławkę na GW${{gw}}`);
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
    const item = {{ ...p, fx }};
    if (isBenchInGw(p.player, selectedLineupGw)) bench.push(item);
    else xi.push(item);
  }});
  xi.sort((a, b) => POS_RANK[a.Pozycja] - POS_RANK[b.Pozycja] || a.fx.fdr - b.fx.fdr);
  bench.sort((a, b) => POS_RANK[a.Pozycja] - POS_RANK[b.Pozycja] || a.fx.fdr - b.fx.fdr);

  function buildMiniTable(list, isXi) {{
    let h = `<thead><tr><th>Poz</th><th>Zawodnik</th><th>Klub</th><th>Cena</th><th>GW${{selectedLineupGw}}</th><th>Akcja</th></tr></thead><tbody>`;
    if (!list.length) {{
      h += `<tr><td colspan="6" style="color:#888;padding:12px;">Brak zawodników</td></tr>`;
    }} else {{
      let prevP = null;
      list.forEach(p => {{
        const inTag = p.source === 'IN' ? `<span style="font-size:10px;background:#107c41;color:#fff;padding:1px 4px;border-radius:3px;margin-right:4px;">IN</span>` : '';
        const btnLbl = isXi ? '→ Ławka' : '← Do XI';
        const sepCls = (prevP !== null && prevP !== p.Pozycja) ? 'zone-border-top' : '';
        prevP = p.Pozycja;
        h += `<tr class="zone-${{p.Pozycja}} ${{sepCls}}">
          <td><b>${{p.Pozycja}}</b></td>
          <td class="text-left">${{inTag}}${{escHtml(p.player)}}</td>
          <td>${{p.team_short}}</td>
          <td>£${{p.Cena.toFixed(1)}}</td>
          <td class="fdr-${{p.fx.fdr}} cell-fix">${{p.fx.text}}</td>
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
  const xiFdrs = xi.map(x => x.fx.fdr).filter(v => v > 0);
  const avgFdr = xiFdrs.length ? (xiFdrs.reduce((a, b) => a + b, 0) / xiFdrs.length).toFixed(2) : '—';

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
    <span>💰 Wartość kadry: <b>£${{totalCost.toFixed(1)}}m</b></span>
    <span>📊 Śr. trudność XI w GW${{selectedLineupGw}}: <b>${{avgFdr}}</b></span>
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

print("GOTOWE! Wygenerowano świeży plik index.html.")
