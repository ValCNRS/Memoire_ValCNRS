# -*- coding: utf-8 -*-
"""
Tableau de bord - Observatoire des lieux de baignade
Projet de recherche CNRS / OHM Vallée du Rhône
"""

import io
import requests
from bs4 import BeautifulSoup
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# =====================================================
# --- 1. CONFIGURATION ET INTERFACE (CSS ADAPTATIF) ---
# =====================================================
st.set_page_config(
    page_title="🔎 Plongez au cœur de la recherche !", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* 📝 JUSTIFIER LE TEXTE DES PARAGRAPHES ET DES LISTES */
    .stMarkdown p, .stMarkdown li {
        text-align: justify;
    }
    
    /* 💻 RÉGLAGES PAR DÉFAUT (ORDINATEUR) */
    html, body, [class*="st-"] { font-size: 18px !important; }
    [data-testid="stMetricLabel"] { font-size: 20px !important; }
    [data-testid="stMetricValue"] { font-size: 45px !important; }

    /* 📱 RÉGLAGES MOBILE (Écrans de moins de 768px de large) */
    @media (max-width: 768px) {
        html, body, [class*="st-"] { font-size: 13px !important; }
        [data-testid="stMetricLabel"] { font-size: 12px !important; }
        [data-testid="stMetricValue"] { font-size: 24px !important; }
        
        .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 1.5rem !important;
        }
        
        div[data-testid="stVerticalBlock"] {
            gap: 0.8rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

URL_NODE = "https://framaforms.org/node/1434338"

# Récupération sécurisée des identifiants via vos secrets Streamlit
USERNAME = st.secrets["frama_user"]
PASSWORD = st.secrets["frama_password"]


# =====================================================
# --- 2. FONCTION DE RÉCUPÉRATION DES DONNÉES ---
# =====================================================
@st.cache_data(ttl=60)
def load_realtime_data():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    # Étape A : Connexion à l'espace d'administration
    login_url = "https://framaforms.org/user/login"
    login_page = session.get(login_url)
    soup_login = BeautifulSoup(login_page.text, 'html.parser')
    form_build_input = soup_login.find('input', {'name': 'form_build_id'})
    
    if form_build_input is None:
        st.warning("⚠️ Impossible de se connecter à Framaforms pour le moment (Sécurité anti-spam temporaire).")
        return None
        
    form_build_id = form_build_input['value']
    
    login_data = {
        "name": USERNAME, 
        "pass": PASSWORD, 
        "form_build_id": form_build_id, 
        "form_id": "user_login", 
        "op": "Se connecter"
    }
    
    login_response = session.post(login_url, data=login_data)
    
    if "Se déconnecter" not in login_response.text:
        st.error("❌ Échec de la connexion à Framaforms. Vérifiez vos identifiants dans les secrets.")
        return None
    
    # Étape B : Extraction de la table HTML (avec pagination sécurisée)
    url_table = f"{URL_NODE}/webform-results/table"
    all_dfs = []  
    page_num = 0  
    
    # SÉCURITÉ 1 : Limite à 50 pages maximum pour éviter de faire planter l'application
    while page_num < 50:
        current_url = f"{url_table}?page={page_num}"
        response = session.get(current_url)
        
        try:
            tables = pd.read_html(io.StringIO(response.text))
            
            if not tables:
                break
                
            df_page = tables[0]
            
            if len(df_page) == 0:
                break
                
            if "Actions" in df_page.columns:
                df_page = df_page.drop(columns=["Actions"])
                
            # SÉCURITÉ 2 : Si la page lue est exactement identique à la précédente, on tourne en rond, on s'arrête.
            if len(all_dfs) > 0 and df_page.equals(all_dfs[-1]):
                break
                
            all_dfs.append(df_page)
            
            # SÉCURITÉ 3 : On cherche dans le code de la page s'il y a un bouton "suivant"
            soup_page = BeautifulSoup(response.text, 'html.parser')
            # Sur Drupal, le bouton "suivant" porte la classe "pager-next"
            if not soup_page.find(class_='pager-next'):
                break # Pas de bouton suivant trouvé = c'était la dernière page
            
            page_num += 1
            
        except ValueError:
            # Fin des tableaux trouvés par Pandas
            break
        except Exception as e:
            st.error(f"❌ Erreur lors de la lecture de la page {page_num+1} Framaforms : {e}")
            break

    if not all_dfs:
        st.error("❌ Aucun tableau trouvé ou impossible de lire les données.")
        return None
        
    df_final = pd.concat(all_dfs, ignore_index=True)
    return df_final


# --- CHARGEMENT INITIAL ---
df_raw = load_realtime_data()

if df_raw is None:
    st.error("Impossible de charger le tableau de bord.")
    st.stop()


# =====================================================
# --- 3. NETTOYAGE ET RÈGLES STATISTIQUES ---
# =====================================================
df = df_raw.copy()

# 🛑 SÉCURITÉ : Vérifier si le formulaire est vide avant de chercher les colonnes
colonnes_test = [c for c in df.columns if "plage" in c.lower()]
formulaire_est_vide = len(df) == 0 or len(colonnes_test) == 0

if not formulaire_est_vide:
    # A. Extraction et traduction du Temps (Heure, Jour, Mois)
    col_temps = [c for c in df.columns if "Soumis" in c or "Date" in c]
    if col_temps:
        date_str = df[col_temps[0]].astype(str).str.replace(' - ', ' ')
        df['Date_Complete'] = pd.to_datetime(date_str, dayfirst=True, errors='coerce')
        
        df['Heure'] = df['Date_Complete'].dt.hour
        
        jours_fr = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
        df['Jour'] = df['Date_Complete'].dt.dayofweek.map(jours_fr)
        
        mois_fr = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
        df['Mois'] = df['Date_Complete'].dt.month.map(mois_fr)
    else:
        df['Heure'], df['Jour'], df['Mois'] = 12, "Inconnu", "Inconnu"

    # B. Identification des colonnes et application du barème des tranches
    paires_questions = {
        'plage': {
            'choix': [c for c in df.columns if "combien" in c.lower() and "plage" in c.lower()][0],
            'exact': [c for c in df.columns if "exact" in c.lower() and "plage" in c.lower()][0]
        },
        'eau': {
            'choix': [c for c in df.columns if "combien" in c.lower() and "taille" in c.lower()][0],
            'exact': [c for c in df.columns if "exact" in c.lower() and "taille" in c.lower()][0]
        },
        'nage': {
            'choix': [c for c in df.columns if "combien" in c.lower() and "nager" in c.lower()][0],
            'exact': [c for c in df.columns if "exact" in c.lower() and "nager" in c.lower()][0]
        }
    }

    for zone_name, cols in paires_questions.items():
        df[f'nb_{zone_name}'] = pd.to_numeric(df[cols['exact']], errors='coerce').fillna(0)
        choix_txt = df[cols['choix']].astype(str).str.strip()
        
        df.loc[choix_txt == "0 personne", f'nb_{zone_name}'] = 0
        df.loc[choix_txt.str.contains("20 et 40"), f'nb_{zone_name}'] = 30
        df.loc[choix_txt.str.contains("40 et 60"), f'nb_{zone_name}'] = 50
        df.loc[choix_txt.str.contains("Plus de 60"), f'nb_{zone_name}'] = 60


# =====================================================
# --- 4. BARRE LATÉRALE : NAVIGATION ET FILTRES -------
# =====================================================
st.sidebar.title("📌 Menu principal")

# 🧭 Choix de la page
page = st.sidebar.radio("Aller à la page :", ["📊 Fréquentation & Activités", "💧 Qualité de l'eau"])

# ⚙️ Les filtres d'analyse ne s'affichent QUE s'il y a des données
if page == "📊 Fréquentation & Activités" and not formulaire_est_vide:
    st.sidebar.write("---")
    st.sidebar.title("⚙️ Filtres d'analyse")
    st.sidebar.markdown("Modifiez les menus ci-dessous pour filtrer l'ensemble du site.")

    # 1️⃣ Filtre AMÉLIORÉ pour le lieu d'observation
    col_lieu = [c for c in df.columns if "endroit" in c.lower()]
    
    if col_lieu:
        nom_col_lieu = col_lieu[0]
        liste_lieux_brute = [l for l in df[nom_col_lieu].unique() if pd.notna(l) and str(l).strip() != ""]
        
        if liste_lieux_brute:
            # On prépare le menu avec des groupes globaux très pratiques
            options_lieux = [
                "Tous les lieux", 
                "Lac des Allivoz", 
                "Parc de la Feyssine"
            ]
            
            # On ajoute ensuite chaque panneau tel quel
            for l in sorted(liste_lieux_brute):
                options_lieux.append(str(l))
            
            lieu_choisi_affiche = st.sidebar.selectbox("📍 Lieu d'observation :", options=options_lieux)
            
            # On applique la règle de filtrage selon ce que l'utilisateur a cliqué
            if lieu_choisi_affiche == "Lac des Allivoz":
                df = df[df[nom_col_lieu].astype(str).apply(lambda x: any(n in x for n in ["1", "2", "3", "4"]))]
            
            elif lieu_choisi_affiche == "Parc de la Feyssine":
                df = df[df[nom_col_lieu].astype(str).apply(lambda x: any(n in x for n in ["5", "6", "7"]))]
            
            elif lieu_choisi_affiche != "Tous les lieux":
                # Si c'est un panneau spécifique, on filtre directement !
                df = df[df[nom_col_lieu] == lieu_choisi_affiche]

st.sidebar.write("---")
st.sidebar.subheader("✉️ Nous contacter")
st.sidebar.write("Une question sur le projet ou sur les données ?")
st.sidebar.markdown("👉 **[Remplir le formulaire de contact](https://framaforms.org/formulaire-de-contact-plongez-au-coeur-de-la-recherche-1779879062)**")


# =====================================================
# --- 5. COMPTAGE DES ACTIVITÉS SÉLECTIONNÉES ---------
# =====================================================
df_activites = pd.DataFrame(columns=["Activité", "Nombre d'observations"]) # Tableau vide par défaut

if not formulaire_est_vide:
    col_activites_liste = [c for c in df.columns if "activités" in c.lower()]
    if col_activites_liste:
        col_activites = col_activites_liste[0]
        liste_activites_possibles = ["Baignade / nage", "Barbecue", "Bronzage / sieste", "Pêche", "Plongeons / sauts dans l'eau", "Promenade avec chien"]

        totaux_activites = {}
        for act in liste_activites_possibles:
            totaux_activites[act] = df[col_activites].str.contains(act, na=False).sum()

        df_activites = pd.DataFrame(list(totaux_activites.items()), columns=["Activité", "Nombre d'observations"])


# =====================================================
# --- 6. STRUCTURE DU TABLEAU DE BORD STREAMLIT -------
# =====================================================

# -----------------------------------------------------
# 🏠 CAS N°1 : PAGE FRÉQUENTATION
# -----------------------------------------------------
if page == "📊 Fréquentation & Activités":

    st.title("🔎 Plongez au cœur de la recherche !")
    
    st.markdown("""
    ## 🏞️ Lacs et rivières autour de Lyon : découvrez les résultats de notre enquête !
    Comment le public s'approprie-t-il les milieux aquatiques ?
    Ce premier volet de notre étude caractérise la fréquentation et les pratiques (sport, détente, recherche de fraîcheur) liées aux milieux aquatiques en ville et en périphérie. 
    
    La force de cette démarche ? Nos données sont directement issues d'**observations réalisées par les participants**.
    
    ### 🔬 Le cadre du projet
    Cette enquête s'inscrit dans un projet de recherche en **science participative**. Elle est financée et soutenue conjointement par l'**Observatoire Hommes-Milieux de la Vallée du Rhône** et le **CNRS**.
    """)
    
    # --- AFFICHAGE DES CARTES DES SITES ---
    st.subheader("📍 Nos sites d'étude")
    col_map1, col_map2 = st.columns(2)
    
    with col_map1:
        st.image("images/CarteAllivoz.png", caption="Lac des Allivoz (Grand Parc Miribel-Jonage)")
        
    with col_map2:
        st.image("images/CarteFeyssine.png", caption="Parc de la Feyssine (Villeurbanne)")
    
    
    if formulaire_est_vide:
        # 🛑 Ce qui s'affiche s'il n'y a aucune donnée
        st.write("---")
        st.info("⏳ **Aucun résultat pour le moment !** Dès qu'un premier participant remplira le questionnaire, les statistiques et les graphiques s'afficheront automatiquement ici.")
    
    else:
        # ✅ Ce qui s'affiche normalement
        st.write("---")
        st.info("👈 **Outils d'analyse :** Cliquez sur la flèche en haut à gauche de votre écran pour ouvrir le menu et filtrer les données.")
        
        # --- SECTION 1 : LES METRICS ---
        st.subheader("📊 Indicateurs de participations")
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Formulaires", value=f"{len(df)} 📨") 
        with col2:
            total_visiteurs = int(df['nb_plage'].sum() + df['nb_eau'].sum() + df['nb_nage'].sum())
            st.metric(label="Usagers estimés", value=total_visiteurs) 
        
        # --- SECTION 2 : GRAPHIQUE DE LA FRÉQUENTATION MOYENNE ---
        st.write("---")
        st.subheader("📈 Profil moyen de la fréquentation")
        
        df['Total_personnes'] = df['nb_plage'] + df['nb_eau'] + df['nb_nage']
        
        # Bouton "Mode d'affichage" conservé au centre
        mode_affichage = st.radio(
            "📅 Mode d'affichage :", 
            options=["Par heure", "Par jour", "Par mois"],
            horizontal=True
        )
        
        if len(df) == 0:
            st.info("⚠️ Aucune donnée disponible pour le filtre sélectionné.")
        else:
            # PRÉPARATION DES DONNÉES ET COULEURS
            noms_categories = {
                'nb_plage': 'Sur la plage', 
                'nb_eau': "Dans l'eau (jusqu'à la taille)", 
                'nb_nage': 'Nageurs'
            }
            couleurs_categories = ['#E2B15B', '#87CEEB', '#1F618D'] # Sable, Bleu clair, Bleu foncé
            
            # Liste des colonnes à convertir en nombres entiers pour éviter le bug des jours/mois
            colonnes_a_arrondir = ['nb_plage', 'nb_eau', 'nb_nage', 'Total_Moyenne', 'Total_Ecart_Type']

            # 🔀 AIGUILLAGE SELON LE MODE D'AFFICHAGE CHOISI (HEURE, JOUR, MOIS)
            if mode_affichage == "Par heure":
                
                df_grp = df.groupby('Heure').agg(
                    nb_plage=('nb_plage', 'mean'),
                    nb_eau=('nb_eau', 'mean'),
                    nb_nage=('nb_nage', 'mean'),
                    Total_Moyenne=('Total_personnes', 'mean'),
                    Total_Ecart_Type=('Total_personnes', 'std')
                ).reset_index()
                
                df_grp[colonnes_a_arrondir] = df_grp[colonnes_a_arrondir].fillna(0).round(0).astype(int)
                df_grp = df_grp.rename(columns=noms_categories)
            
                fig_bar = px.bar(
                    df_grp, 
                    x='Heure', 
                    y=list(noms_categories.values()), 
                    title="Répartition moyenne du public par heure", 
                    color_discrete_sequence=couleurs_categories
                )
                
                fig_bar.add_trace(go.Scatter(
                    x=df_grp['Heure'],
                    y=df_grp['Total_Moyenne'],
                    mode='markers',
                    marker=dict(color='rgba(0,0,0,0)'), 
                    error_y=dict(
                        type='data',
                        array=df_grp['Total_Ecart_Type'],
                        visible=True,
                        color='#E74C3C', 
                        thickness=1,   # <-- Épaisseur réduite
                        width=3        # <-- Largeur des chapeaux réduite
                    ),
                    showlegend=False,
                    hoverinfo='skip'
                ))
                
                fig_bar.update_traces(width=0.8, selector=dict(type='bar'))
                
                fig_bar.update_layout(
                    font=dict(size=11), 
                    xaxis_title="Heure de la journée (H)", 
                    yaxis_title="Nombre de personnes (Moyenne)", 
                    legend_title_text="Catégorie de public",
                    legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
                    height=450, 
                    margin=dict(l=10, r=10, t=50, b=100), 
                    xaxis=dict(tickmode='linear', tick0=0, dtick=2, range=[0, 24], fixedrange=True), 
                    yaxis=dict(range=[0, 100], fixedrange=True)
                )

            elif mode_affichage == "Par jour":
                
                df_grp = df.groupby('Jour').agg(
                    nb_plage=('nb_plage', 'mean'),
                    nb_eau=('nb_eau', 'mean'),
                    nb_nage=('nb_nage', 'mean'),
                    Total_Moyenne=('Total_personnes', 'mean'),
                    Total_Ecart_Type=('Total_personnes', 'std')
                ).reset_index()
                
                df_grp[colonnes_a_arrondir] = df_grp[colonnes_a_arrondir].fillna(0).round(0).astype(int)
                df_grp = df_grp.rename(columns=noms_categories)
                
                ordre_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                
                fig_bar = px.bar(
                    df_grp, 
                    x='Jour', 
                    y=list(noms_categories.values()), 
                    title="Répartition moyenne du public par jour", 
                    color_discrete_sequence=couleurs_categories
                )
                
                fig_bar.add_trace(go.Scatter(
                    x=df_grp['Jour'],
                    y=df_grp['Total_Moyenne'],
                    mode='markers',
                    marker=dict(color='rgba(0,0,0,0)'),
                    error_y=dict(
                        type='data',
                        array=df_grp['Total_Ecart_Type'],
                        visible=True,
                        color='#E74C3C', 
                        thickness=1,   # <-- Épaisseur réduite
                        width=3        # <-- Largeur des chapeaux réduite
                    ),
                    showlegend=False,
                    hoverinfo='skip'
                ))
                
                fig_bar.update_traces(width=0.6, selector=dict(type='bar')) 
                
                fig_bar.update_layout(
                    font=dict(size=11), 
                    xaxis_title="Jour de la semaine", 
                    yaxis_title="Nombre de personnes (Moyenne)", 
                    legend_title_text="Catégorie de public",
                    legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
                    height=450, 
                    margin=dict(l=10, r=10, t=50, b=100), 
                    xaxis=dict(categoryorder='array', categoryarray=ordre_jours, fixedrange=True), 
                    yaxis=dict(range=[0, 100], fixedrange=True)
                )

            else:
                # Mode Mensuel (Focus sur la saison estivale)
                ordre_mois = ["Juin", "Juillet", "Août"]
                df_estival = df[df['Mois'].isin(ordre_mois)]
                
                df_grp = df_estival.groupby('Mois').agg(
                    nb_plage=('nb_plage', 'mean'),
                    nb_eau=('nb_eau', 'mean'),
                    nb_nage=('nb_nage', 'mean'),
                    Total_Moyenne=('Total_personnes', 'mean'),
                    Total_Ecart_Type=('Total_personnes', 'std')
                ).reset_index()
                
                df_grp[colonnes_a_arrondir] = df_grp[colonnes_a_arrondir].fillna(0).round(0).astype(int)
                df_grp = df_grp.rename(columns=noms_categories)
                
                fig_bar = px.bar(
                    df_grp, 
                    x='Mois', 
                    y=list(noms_categories.values()), 
                    title="Répartition moyenne du public par mois", 
                    color_discrete_sequence=couleurs_categories
                )
                
                fig_bar.add_trace(go.Scatter(
                    x=df_grp['Mois'],
                    y=df_grp['Total_Moyenne'],
                    mode='markers',
                    marker=dict(color='rgba(0,0,0,0)'),
                    error_y=dict(
                        type='data',
                        array=df_grp['Total_Ecart_Type'],
                        visible=True,
                        color='#E74C3C', 
                        thickness=1,   # <-- Épaisseur réduite
                        width=3        # <-- Largeur des chapeaux réduite
                    ),
                    showlegend=False,
                    hoverinfo='skip'
                ))
                
                fig_bar.update_traces(width=0.4, selector=dict(type='bar'))
                
                fig_bar.update_layout(
                    font=dict(size=11), 
                    xaxis_title="Mois de la saison estivale", 
                    yaxis_title="Nombre de personnes (Moyenne)", 
                    legend_title_text="Catégorie de public",
                    legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
                    height=450, 
                    margin=dict(l=10, r=10, t=50, b=100), 
                    xaxis=dict(categoryorder='array', categoryarray=ordre_mois, fixedrange=True), 
                    yaxis=dict(range=[0, 100], fixedrange=True)
                )

            # --- Ligne rouge d'incertitude (S'applique aux trois graphiques) ---
            fig_bar.add_hline(
                y=60, 
                line_dash="dash", 
                line_color="#E74C3C", 
                annotation_text="⚠️ Seuil d'estimation (> 60 personnes)", 
                annotation_position="top left",
                annotation_font=dict(color="#E74C3C", size=11)
            )

            st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': True})
        
        # --- SECTION 3 : GRAPHIQUE DES ACTIVITÉS ---
        st.write("---")
        st.subheader("📋🏖️ Activités observées sur le site")
        if len(df_activites) > 0:
            
            # Règle dynamique pour empêcher les virgules si peu d'observations
            max_obs = df_activites["Nombre d'observations"].max()
            xaxis_config = dict(fixedrange=True)
            if max_obs <= 10:
                xaxis_config['dtick'] = 1  # Force l'axe à avancer de 1 en 1
            
            fig_activities = px.bar(
                df_activites.sort_values(by="Nombre d'observations", ascending=True), 
                y='Activité', 
                x="Nombre d'observations", 
                color='Activité', 
                text_auto=True, 
                title="Nombre d'observations par activité", 
                orientation='h', 
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            
            fig_activities.update_layout(
                font=dict(size=11), 
                showlegend=False, 
                xaxis_title="Nombre total d'observations", 
                yaxis_title=None, 
                margin=dict(l=10, r=10, t=50, b=10), 
                height=350, 
                xaxis=xaxis_config, 
                yaxis=dict(fixedrange=True)
            )
            st.plotly_chart(fig_activities, use_container_width=True, config={'displayModeBar': True})


# -----------------------------------------------------
# 💧 CAS N°2 : PAGE "QUALITÉ DE L'EAU"
# -----------------------------------------------------
elif page == "💧 Qualité de l'eau":

    st.title("💧 Qualité de l'eau des lacs et rivières en ville et en périphérie")
    
    st.markdown("""
    ## Comprendre les enjeux de la qualité de l'eau autour de Lyon
    
    Ce second volet de notre projet de recherche explore comment le public se représente et perçoit la qualité de l'eau des lacs et rivières. Pour cela, une journée d'étude a été mise en place le 18 juillet 2026 au lac des Allivoz pour réaliser des expérimentations autour de la qualité de l'eau avec le public, tout en portant à la connaissance des participants les enjeux environnementaux associés.
    
    **Voici ce qu'il faut savoir pour réduire les risques de la baignade en eau libre liés à la qualité de l'eau :**
    """)

    st.write("---")

    # Intégration du texte scientifique
    st.markdown("""
    ### 🔬 La qualité sanitaire et écologique de l’eau

    **🦠 Les agents pathogènes (bactéries et virus)**
    * **D'où viennent-ils ?** Ces pathogènes d’origine fécale sont amenés dans l’eau lors de fortes pluies, par ruissellement sur les surfaces contaminés (villes et surfaces agricoles) ou par débordement des systèmes d’égouts et de traitements des eaux usées (réseaux unitaires). Cela peut provoquer des infections ou des gastro-entérites.
    * **Ce que dit la réglementation :** La directive européenne impose de surveiller deux FIB (Fecal Indicator Bacteria / bactéries indicatrices de pollution fécale) : Escherichia coli (E. coli) et les entérocoques intestinaux. 
    * **L'angle mort de la surveillance :** Bien que ces bactéries servent de bon système d'alarme en cas de pollutions ponctuelles (après un orage), elles ne permettent pas de détecter correctement les virus pathogènes (comme les norovirus et les adénovirus) à plus long terme. En effet, ces différents agents pathogènes évoluent ensuite différemment dans le milieu aquatique. Ces virus représentent pourtant 84 % du risque global d'infection. Ils survivent plus longtemps et une très faible dose suffit à rendre malade.
    * **Le défi technique :** Les autorités ne mesurent pas les virus en continu car cela nécessite des méthodes coûteuses et complexes.

    **🟢 Les cyanobactéries**
    * **Qu'est-ce que c’est ?** Ce sont des organismes qui, lorsqu'ils se multiplient massivement, créent des HAB (Harmful Algal Blooms / développements d’algues nuisibles). L'eau prend alors une couleur verte et devient trouble. 
    * **Le risque :** Elles libèrent des cyanotoxines (classées en hépatotoxines, neurotoxines et dermatotoxines). Le contact ou l'ingestion de cette eau peut causer des irritations, des troubles gastro-intestinaux ou de la fièvre, même si les accidents graves restent rares. 
    * **La cause :** Les cyanobactéries se nourrissent d'un apport excessif de nutriments (azote et phosphore) issus de l'agriculture et des rejets urbains. Le changement climatique aggrave ce phénomène. 

    **🧪 La pollution chimique de l'eau**
    * **Les causes :** Elle provient de l'activité humaine et de phénomènes naturels. On y retrouve des métaux lourds (plomb, cadmium, arsenic, chrome, etc.), des composés inorganiques (nitrates, phosphates), des pesticides, ou encore des polluants émergents comme les PFAS et les microplastiques. Des variations extrêmes de pH peuvent aussi survenir. 
    * **Faut-il s'inquiéter ?** Bien que ces produits soient toxiques à long terme lors d’expositions chroniques, l'OMS précise que leurs concentrations dans les eaux de baignade sont généralement insuffisantes pour provoquer des maladies aiguës à court terme. Le risque chimique est donc relégué au second plan derrière le risque microbiologique par les autorités sanitaires.

    **🐟 La qualité écologique de l’eau**
    La présence humaine provoque le dérangement de la faune sauvage (oiseaux, poissons). Le piétinement des berges fait disparaître la végétation, ce qui met la terre à nu, augmentant ainsi la turbidité de l'eau et favorisant l'eutrophisation. L'aménagement des berges reste l'impact le plus lourd car il détruit directement les habitats naturels.

    ---
    
    ### 👁️ Quel lien avec la turbidité ?
    
    Les baigneurs associent souvent une eau claire à une eau "propre", mais le lien entre turbidité (présence de particules en suspension qui rendent l'eau trouble) et qualité microbiologique est plus complexe. Une eau très claire peut être contaminée par des bactéries ou des virus invisibles, tandis qu'une eau un peu trouble n'est pas forcément dangereuse :
    * **Attention au milieu urbain !** Cette règle ne fonctionne pas toujours en ville. Une fuite de canalisation d'égout peut libérer énormément de bactéries sans amener de sédiments. L'eau reste alors très claire mais devient extrêmement contaminée. 
    * A l’inverse, des cours d’eau peuvent être turbides sans pour autant être dangereuses pour la santé (exemple : turbidité de l’eau liée à la fonte de glacier, etc…) ; le contexte géographique et saisonnier est donc essentiel à prendre en compte.
    
    En réalité, **la turbidité est un indicateur indirect** : elle peut être associée à une augmentation du risque microbiologique (par exemple après un épisode de pluie qui entraîne des matières fécales et des sédiments vers la zone de baignade), mais elle ne permet pas, à elle seule, de conclure à la présence ou à l'absence de micro-organismes pathogènes. C'est pourquoi les autorités sanitaires combinent généralement les mesures de turbidité avec des analyses microbiologiques, des données météorologiques, des informations sur les rejets et des modèles de prévision pour évaluer le risque sanitaire.

    ---

    ### ✅ Les recommandations

    **Avant la baignade**
    * Vérifiez que la baignade est autorisée et consultez les informations affichées sur le site.
    * Évitez de vous baigner après de fortes pluies ou un orage : les eaux de ruissellement et les débordements de réseaux d’égouts peuvent dégrader temporairement la qualité de l'eau.
    * Respectez les éventuelles fermetures temporaires, même si l'eau paraît claire.
    * De façon générale, la baignade est plutôt déconseillée si la transparence de l’eau est inférieure à 1 mètre, c’est-à-dire qu’on n’a plus la capacité de voir ses pieds lorsque l’eau nous arrive à la taille.

    **Pendant la baignade**
    * Évitez d'avaler de l'eau.
    * Surveillez particulièrement les jeunes enfants, qui avalent plus facilement de l'eau.
    * Ne vous baignez pas si vous avez une maladie infectieuse, afin de limiter la contamination de l'eau.
    * Évitez la baignade si vous avez des plaies importantes ou des blessures récentes.

    **Après la baignade**
    * Prenez une douche si des installations sont disponibles.
    * Lavez-vous les mains avant de manger.
    * Rincez-vous les yeux si nécessaire.
    * Changez de vêtements mouillés rapidement.

    **Situations où il vaut mieux renoncer**
    * Dans les 24 à 72 heures suivant un épisode de fortes pluies (selon les recommandations locales).
    * Si l'eau présente une pollution visible (déchets, mousse anormale, hydrocarbures).
    * En présence d'une prolifération d'algues ou de cyanobactéries : une eau de couleur verte doit alerter.
    * Lorsque les autorités déconseillent ou interdisent la baignade.
    
    **Les jeunes enfants, les personnes âgées, les femmes enceintes et les personnes immunodéprimées** doivent être particulièrement attentifs aux recommandations sanitaires, car les conséquences d'une infection peuvent être plus importantes.

    **Quelques idées reçues**
    * Une eau claire n'est pas forcément exempte de micro-organismes.
    * Une eau un peu trouble n'est pas systématiquement dangereuse.
    * L'absence d'odeur ne garantit pas une bonne qualité microbiologique.
    * Les panneaux d'information et les analyses de la qualité de l'eau sont plus fiables que l'aspect visuel de la rivière.
    """)


# =====================================================
# --- 7. SECTION PARTENAIRES ET LOGOS -----------------
# =====================================================
st.write("---") 

# On crée 5 colonnes avec des proportions stratégiques.
col_vide_gauche, col_logo1, col_logo2, col_logo3, col_vide_droite = st.columns([1.5, 1, 1, 1, 1.5], vertical_alignment="center")

with col_logo1:
    st.image("images/Logo_Centre_national_de_la_recherche_scientifique_(2023-).svg", width=100)

with col_logo2:
    st.image("images/logo_OHM_vr.png", width=130) 

with col_logo3:
    st.image("images/Logo_Rouge_Université-lumiere-lyon_2_2025.png", width=130)
